"""Cliente mínimo de ComfyUI: lo abre sin ventana si está cerrado, encola un workflow y espera el resultado.

Busca ComfyUI en SHARP_SPLAT_COMFYUI_URL o en los puertos 8000 (Comfy Desktop) y 8188 (portable). Si no
responde, lo levanta con la primera instalación que encuentra: la carpeta de SHARP_SPLAT_COMFYUI_DIR,
Comfy Desktop 2 o el Comfy Desktop anterior, con el mismo comando que usa la app. Al cerrar Nuke cierra
el ComfyUI que abrió. ComfyUI tiene que correr en este PC: lee y escribe los archivos por ruta.
"""

import atexit
import json
import os
import shlex
import subprocess
import tempfile
import time
from urllib import request
from urllib.error import HTTPError, URLError

URLS = [os.environ["SHARP_SPLAT_COMFYUI_URL"].rstrip("/")] if os.environ.get("SHARP_SPLAT_COMFYUI_URL") else [
    "http://127.0.0.1:8000", "http://127.0.0.1:8188"]
PACKAGES = {"SharpHDR_Predict": "ComfyUI-SHARP-HDR", "LoadSharpModel": "ComfyUI-Sharp",
            "LoadEXR": "ComfyUI-HQ-Image-Save"}
DESKTOP2 = os.path.join(os.environ.get("APPDATA", ""), "Comfy Desktop")  # Comfy Desktop 2
DESKTOP1 = os.path.join(os.environ.get("APPDATA", ""), "ComfyUI")        # la app anterior
LOG = os.path.join(tempfile.gettempdir(), "sharp_splat_comfyui.log")
START_TIMEOUT = 300
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_url = None     # el que respondió la última vez
_server = None  # PID del ComfyUI que abrió SHARP Splat


class Graph(object):
    """Workflow en formato API. add() devuelve la primera salida del nodo."""

    def __init__(self):
        self.nodes = {}

    def add(self, class_type, **inputs):
        nid = str(len(self.nodes) + 1)
        self.nodes[nid] = {"class_type": class_type, "inputs": {k: v for k, v in inputs.items() if v is not None}}
        return [nid, 0]


def out(ref, index):
    return [ref[0], index]


def _alive(url):
    try:
        request.urlopen(url + "/system_stats", timeout=1).close()
        return True
    except Exception:
        return False


def server():
    """URL de un ComfyUI que responde, o None."""
    global _url
    for u in ([_url] if _url else []) + [u for u in URLS if u != _url]:  # sin olvidar el que se está abriendo
        if _alive(u):
            _url = u
            return u
    return None


# --- cómo se abre cada instalación (copiado de Comfy Desktop 2: sources/*.getLaunchCommand y launch.ts) ---

def _args(text):
    return [a.strip('"') for a in shlex.split(text or "", posix=False)]


def _venv_python(folder):
    for name in (".venv", "venv", ".env", "env"):
        for exe in (("Scripts", "python.exe"), ("python.exe",)):
            p = os.path.join(folder, name, *exe)
            if os.path.isfile(p):
                return p
    return None


def _portable_root(path):
    """La carpeta con python_embeded: la indicada o una de sus subcarpetas."""
    subs = [os.path.join(path, e) for e in sorted(os.listdir(path))] if os.path.isdir(path) else []
    return next((p for p in [path] + subs if os.path.isdir(os.path.join(p, "python_embeded"))), None)


def _main_py(path):
    return next((p for p in (os.path.join(path, "main.py"), os.path.join(path, "ComfyUI", "main.py"))
                 if os.path.isfile(p)), None)


def _from_folder(folder, launch_args=None, python=None):
    """(argv, cwd) de un ComfyUI portable, o de una carpeta con main.py y su venv (instalación manual o git)."""
    root = _portable_root(folder)
    if root:
        return ([os.path.join(root, "python_embeded", "python.exe"), "-s", os.path.join(root, "ComfyUI", "main.py")]
                + _args("--windows-standalone-build --disable-auto-launch" if launch_args is None else launch_args), root)
    main = _main_py(folder)
    python = python or (main and (_venv_python(os.path.dirname(main)) or _venv_python(folder)))
    if not (main and python and os.path.isfile(python)):
        return None
    return [python, "-s", "main.py"] + _args(launch_args), os.path.dirname(main)


def _desktop2_install(inst, settings, home):
    """(argv, cwd) de una instalación de Comfy Desktop 2, o None si no es local o le falta algo."""
    root, source, launch_args = inst.get("installPath"), inst.get("sourceId"), inst.get("launchArgs")
    if not root or inst.get("status", "installed") != "installed":
        return None
    if source == "standalone":
        adopted = inst.get("adopted") is True  # adoptada: reusa la carpeta de la app anterior
        python = inst.get("adoptedPythonPath") if adopted else os.path.join(root, "ComfyUI", ".venv", "Scripts", "python.exe")
        if not (python and os.path.isfile(python) and os.path.isfile(os.path.join(root, "ComfyUI", "main.py"))):
            return None
        argv, cwd = [python, "-s", os.path.join("ComfyUI", "main.py")], root
        base = inst.get("adoptedBaseDir") if adopted else None
        if base:
            argv += ["--base-directory", base, "--user-directory", os.path.join(base, "user")]
            if "--database-url" not in (launch_args or ""):
                argv += ["--database-url", "sqlite:///" + os.path.join(base, "user", "comfyui.db")]
        argv += _args(launch_args)
    elif source == "portable":
        cmd = _from_folder(root, launch_args) if _portable_root(root) else None
        if not cmd:
            return None
        argv, cwd = cmd
    elif source == "git":
        venv = inst.get("venvPath") or ""
        python = next((p for p in (os.path.join(venv, "Scripts", "python.exe"), os.path.join(venv, "python.exe"))
                       if venv and os.path.isfile(p)), None)
        cmd = python and _from_folder(root, launch_args or "", python=python)
        if not cmd:
            return None
        argv, cwd = cmd
    else:
        return None  # nube, o la app anterior registrada (se abre con ventana): esa la cubre _desktop1
    yaml = os.path.join(home, "instance-model-paths", "%s.yaml" % inst.get("id"))
    if os.path.isfile(yaml):  # carpetas de modelos: Desktop lo reescribe en cada arranque
        argv += ["--extra-model-paths-config", yaml]
    for flag, kind in (("--input-directory", "input"), ("--output-directory", "output")):
        shared = inst.get("useShared" + kind.title()) is not False
        path = (settings.get(kind + "Dir") or os.path.join(os.path.expanduser("~"), "ComfyUI-Shared", kind)) if shared             else inst.get(kind + "Dir")
        if path:
            os.makedirs(path, exist_ok=True)
            argv += [flag, path]
    return argv, cwd


def _desktop2(home=DESKTOP2):
    """La instalación local de Comfy Desktop 2 abierta más recientemente."""
    try:
        with open(os.path.join(home, "installations.json"), encoding="utf-8") as f:
            installs = json.load(f)
        settings = {}
        if os.path.isfile(os.path.join(home, "settings.json")):
            with open(os.path.join(home, "settings.json"), encoding="utf-8") as f:
                settings = json.load(f)
    except (OSError, ValueError):
        return None
    for inst in sorted(installs, key=lambda i: i.get("lastLaunchedAt") or 0, reverse=True):
        cmd = _desktop2_install(inst, settings, home)
        if cmd:
            return cmd
    return None


def _desktop1(home=DESKTOP1, programs=os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ComfyUI")):
    """La app anterior (Comfy Desktop 1): el código viene con la app y los datos van en basePath."""
    try:
        with open(os.path.join(home, "config.json"), encoding="utf-8") as f:
            base = json.load(f)["basePath"]
    except (OSError, ValueError, KeyError):
        return None
    res = os.path.join(programs, "resources", "ComfyUI")
    python = os.path.join(base, ".venv", "Scripts", "python.exe")
    if not (os.path.isfile(python) and os.path.isfile(os.path.join(res, "main.py"))):
        return None
    argv = [python, os.path.join(res, "main.py"), "--user-directory", os.path.join(base, "user"),
            "--input-directory", os.path.join(base, "input"), "--output-directory", os.path.join(base, "output"),
            "--front-end-root", os.path.join(res, "web_custom_versions", "desktop_app"), "--base-directory", base,
            "--database-url", "sqlite:///" + os.path.join(base, "user", "comfyui.db").replace("\\", "/"),
            "--port", "8000"]
    yaml = os.path.join(home, "extra_models_config.yaml")
    if os.path.isfile(yaml):
        argv += ["--extra-model-paths-config", yaml]
    return argv, base


def launch_command():
    """(argv, cwd, puerto) para abrir ComfyUI sin ventana, o None si no hay una instalación conocida."""
    folder = os.environ.get("SHARP_SPLAT_COMFYUI_DIR")
    cmd = _from_folder(folder) if folder else (_desktop2() or _desktop1())
    if not cmd:
        return None
    argv, cwd = cmd
    port = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--port=")), None) or next(
        (int(argv[i + 1]) for i, a in enumerate(argv[:-1]) if a == "--port"), None)
    if port is None:
        port = 8188
        argv += ["--port", str(port)]
    return argv + ["--disable-auto-launch"], cwd, port


# --- abrir y cerrar ---------------------------------------------------------------------------

def _spawn(argv, cwd):
    """Abre argv sin ventana y fuera del árbol de procesos de Nuke (WMI); devuelve su PID.
    Como hijo de Nuke, el torch de ComfyUI no carga (c10.dll, WinError 1114; medido en GenFill, 2026-10-20).
    shortcut: solo Windows, como las instalaciones que sabe leer."""
    q = lambda s: "'%s'" % s.replace("'", "''")
    line = 'cmd.exe /c "set PYTHONIOENCODING=utf-8&& set PYTHONUTF8=1&& %s > "%s" 2>&1"' % (
        subprocess.list2cmdline(argv), LOG)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}; "
         "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
         "@{CommandLine=%s; CurrentDirectory=%s; ProcessStartupInformation=$si}; "
         "\"$($r.ReturnValue) $($r.ProcessId)\"" % (q(line), q(cwd))],
        capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout.split()
    if len(out) != 2 or out[0] != "0":
        raise RuntimeError("Windows no pudo abrir ComfyUI (Win32_Process.Create: %s)." % " ".join(out))
    return int(out[1])


def _running(pid):
    out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
    return '"%d"' % pid in out.stdout


def wait_for_server(progress=None):
    """Deja ComfyUI respondiendo: lo abre si está cerrado y espera hasta START_TIMEOUT."""
    global _server, _url
    if server():
        return
    if os.environ.get("SHARP_SPLAT_COMFYUI_URL"):
        raise RuntimeError("ComfyUI no responde en %s (SHARP_SPLAT_COMFYUI_URL). Ábrelo y vuelve a apretar Generar."
                           % URLS[0])
    if _server is None or not _running(_server):
        cmd = launch_command()
        if cmd is None:
            raise RuntimeError("ComfyUI está cerrado y no encontré cómo abrirlo. Ábrelo y vuelve a apretar Generar, o "
                               "define la variable de entorno SHARP_SPLAT_COMFYUI_DIR con la carpeta de tu ComfyUI.")
        argv, cwd, port = cmd
        _server, _url = _spawn(argv, cwd), "http://127.0.0.1:%d" % port
    t0 = time.time()
    while not _alive(_url):
        if not _running(_server):
            raise RuntimeError("ComfyUI se cerró al abrir. Revisa %s" % LOG)
        if time.time() - t0 > START_TIMEOUT:
            raise RuntimeError("ComfyUI no terminó de abrir en %d s. Revisa %s" % (START_TIMEOUT, LOG))
        if progress:
            progress(0.02, "Abriendo ComfyUI (la primera vez, cerca de un minuto)...")
        time.sleep(1)


@atexit.register
def _stop():
    """Al cerrar Nuke: cierra ComfyUI solo si lo abrió SHARP Splat (el cmd.exe y lo que corre debajo)."""
    if _server is not None:
        subprocess.run(["taskkill", "/PID", str(_server), "/T", "/F"], capture_output=True, timeout=15,
                       creationflags=NO_WINDOW)


# --- workflows --------------------------------------------------------------------------------

def _error(body):
    """Mensaje legible de una respuesta de error de ComfyUI, con el paquete que falta si es eso."""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return ""
    err = data.get("error")
    parts = [err.get("message", "")] if isinstance(err, dict) else []
    for info in (data.get("node_errors") or {}).values():
        parts += ["%s: %s %s" % (info.get("class_type", "?"), e.get("message", ""), e.get("details", ""))
                  for e in info.get("errors", [])]
    text = "; ".join(p.strip() for p in parts if p.strip())
    gone = "not found" in text or "does not exist" in text  # según la versión de ComfyUI
    missing = [pkg for node, pkg in PACKAGES.items() if gone and "'%s'" % node in text]
    if missing:
        text += "\nInstala %s con ComfyUI Manager y reinicia ComfyUI." % ", ".join(missing)
    return text


def _call(path, body=None):
    url = server()
    if not url:
        raise RuntimeError("ComfyUI dejó de responder.")
    req = request.Request(url + path, data=body, method="POST" if body is not None else "GET",
                          headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError("ComfyUI: %s" % (_error(exc.read()) or "HTTP %s" % exc.code))
    except (URLError, OSError) as exc:
        raise RuntimeError("ComfyUI dejó de responder (%s)." % exc)


def run(workflow):
    """Encola el workflow y espera a que termine. Devuelve su entrada del historial."""
    pid = _call("/prompt", json.dumps({"prompt": workflow}).encode("utf-8"))["prompt_id"]
    while True:
        hist = _call("/history/%s" % pid).get(pid) or {}
        status = hist.get("status") or {}
        if status.get("status_str") == "error":
            for kind, info in status.get("messages", []):
                if kind == "execution_error":
                    raise RuntimeError("ComfyUI, nodo %s: %s" % (info.get("node_type", ""),
                                                                 info.get("exception_message", "").strip()))
            raise RuntimeError("ComfyUI falló (revisa su consola).")
        if status.get("completed"):
            return hist
        time.sleep(0.5)
