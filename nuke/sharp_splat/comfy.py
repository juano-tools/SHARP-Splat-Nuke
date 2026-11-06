"""Cliente mínimo de ComfyUI: encola un workflow, espera y devuelve su historial.

Busca ComfyUI en SHARP_SPLAT_COMFYUI_URL o, si no está definida, en los puertos de Comfy Desktop
(8000) y de ComfyUI portable o manual (8188). ComfyUI tiene que correr en este PC: lee y escribe
los archivos por ruta.
"""

import json
import os
import time
from urllib import request
from urllib.error import HTTPError, URLError

URLS = [os.environ["SHARP_SPLAT_COMFYUI_URL"].rstrip("/")] if os.environ.get("SHARP_SPLAT_COMFYUI_URL") else [
    "http://127.0.0.1:8000", "http://127.0.0.1:8188"]
PACKAGES = {"SharpHDR_Predict": "ComfyUI-SHARP-HDR", "LoadSharpModel": "ComfyUI-Sharp",
            "LoadEXR": "ComfyUI-HQ-Image-Save"}
_url = None  # el que respondió la última vez


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
    if _url and _alive(_url):
        return _url
    _url = next((u for u in URLS if _alive(u)), None)
    return _url


def wait_for_server(progress=None):
    if server():
        return
    try:  # si está GenFill (solo en el estudio), sabe abrir Comfy Desktop sin ventana
        from genfill.backends import comfyui as genfill_comfy
        if progress:
            progress(0.02, "Abriendo ComfyUI...")
        genfill_comfy.wait_for_server(progress)
    except Exception:
        pass
    if not server():
        raise RuntimeError("ComfyUI no responde en %s. Ábrelo y vuelve a apretar Generar. Si usa otra dirección, "
                           "defínela en la variable de entorno SHARP_SPLAT_COMFYUI_URL." % " ni en ".join(URLS))


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
    req = request.Request(server() + path, data=body, method="POST" if body is not None else "GET",
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
