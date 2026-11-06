"""Nodo SHARP Splat (Group): un cuadro del plate -> Gaussian splats HDR con SHARP-HDR -> SplatRender.

Entradas: plate (la imagen) y cam (opcional: una camara propia para vistas nuevas, en el mundo
nivelado). Salida: el render de los splats. "Generar" corre SHARP en el cuadro elegido y rearma
el interior; el piso se nivela solo y la escena queda en metros.
"""

import base64
import json
import os
import threading
import time

import nuke

from . import core

KEEP = ("plate", "cam", "Output1")  # lo unico del interior que Generar no borra
_busy = set()  # Groups con una corrida en curso


def _cmd(fn):
    return "import sharp_splat.node as n; n.%s(nuke.thisNode())" % fn


def _job(g):
    v = g["sharp_job"].value()
    # base64: un String_Knob evalua TCL y un JSON con { } [ ] se rompe al reabrir el .nk
    return json.loads(base64.b64decode(v)) if v else {}


def _save_job(g, job):
    g["sharp_job"].setValue(base64.b64encode(json.dumps(job).encode()).decode())


def _status(g, text):
    g["sharp_status"].setValue(text)


# --- creacion ---------------------------------------------------------------------------------

def _add_knobs(g):
    def add(k, newline=True, tip=None):
        if newline:
            k.setFlag(nuke.STARTLINE)
        if tip:
            k.setTooltip(tip)
        g.addKnob(k)
        return k

    g.addKnob(nuke.Tab_Knob("sharp_tab", "SHARP"))
    add(nuke.Text_Knob("sharp_status", "estado", "sin generar"))
    add(nuke.Int_Knob("sharp_frame", "cuadro"), tip="Cuadro del plate que SHARP convierte en splats.")
    g["sharp_frame"].setValue(nuke.frame())
    add(nuke.PyScript_Knob("sharp_frame_now", "cuadro actual",
                           "nuke.thisNode()['sharp_frame'].setValue(nuke.frame())"), newline=False)
    add(nuke.Enumeration_Knob("sharp_mode", "modo", core.MODES),
        tip="Aislar objeto usa el alpha del plate y deja solo lo que esta dentro.")
    for name, label, hi in (("sharp_focal", "focal (mm)", 100), ("sharp_filmback", "filmback ancho (mm)", 50)):
        k = add(nuke.Double_Knob(name, label))
        k.setRange(0, hi)
    add(nuke.Text_Knob("sharp_meta", "metadata", "-"))
    add(nuke.PyScript_Knob("sharp_read_meta", "Leer metadata", _cmd("fill_lens_force")),
        tip="Llena focal y filmback con lo que traiga la metadata de camara del plate.")
    add(nuke.Text_Knob("sharp_div1", ""))
    add(nuke.PyScript_Knob("sharp_generate", "<b>Generar</b>", _cmd("generate")),
        tip="Corre SHARP en ComfyUI (via GenFill) y rearma la escena. Unos 5 s; la primera vez, mas.")

    add(nuke.Text_Knob("sharp_div_set", "settings de SHARP"))
    for name, default in core.SETTINGS:
        if name == core.ISOLATION_FROM:
            add(nuke.Text_Knob("sharp_div_iso", "aislar objeto"))
        cls = nuke.Boolean_Knob if isinstance(default, bool) else nuke.Int_Knob if isinstance(default, int) else nuke.Double_Knob
        k = add(cls("sharp_" + name, name))
        if cls is nuke.Double_Knob:
            k.setRange(0, max(1.0, 2 * default))  # el slider de fabrica es 0-1
        k.setValue(default)

    add(nuke.Text_Knob("sharp_div_scene", "escena"))
    add(nuke.Boolean_Knob("sharp_orient_on", "nivelar piso"),
        tip="Busca el piso bajo la camara y lo deja en Y=0, con el origen bajo la camara.\n"
            "El render desde la camara de SHARP no cambia.")
    g["sharp_orient_on"].setValue(True)
    k = add(nuke.Double_Knob("sharp_cam_height", "altura camara (m)"),
            tip="Escala la escena para que la camara quede a esta altura del piso.\n"
                "0 = la escala de SHARP, que ya es metrica si el focal y el filmback son los reales.")
    k.setRange(0, 3)
    add(nuke.PyScript_Knob("sharp_export_cam", "Sacar camara", _cmd("export_camera")),
        tip="Crea afuera una camara igual a la de SHARP, en el mundo nivelado.\n"
            "Animala (o una copia) y conectala a la entrada 'cam' para ver la escena desde otro lado.")
    hidden = nuke.String_Knob("sharp_job", "")
    hidden.setFlag(nuke.INVISIBLE)
    g.addKnob(hidden)


def create():
    """Menu Nodes > 3D > SHARP Splat. Se conecta al nodo seleccionado."""
    sel = nuke.selectedNodes()
    g = nuke.nodes.Group()
    g.setName("SHARP_Splat1", uncollide=True)
    with g:
        nuke.nodes.Input(name="plate")  # Input 0
        nuke.nodes.Input(name="cam")    # Input 1
        nuke.nodes.Output(name="Output1")
    _add_knobs(g)
    g["knobChanged"].setValue("import sharp_splat.node as n; n.knob_changed()")
    g["tile_color"].setValue(0x3A5A40FF)
    if sel:
        g.setInput(0, sel[-1])
        g.setXYpos(sel[-1].xpos(), sel[-1].ypos() + 120)
        fill_lens(g)
    for n in nuke.selectedNodes():
        n.setSelected(False)
    g.setSelected(True)
    g.showControlPanel()
    return g


def knob_changed():
    g, k = nuke.thisNode(), nuke.thisKnob()
    try:
        if k.name() == "inputChange":
            _wire_cam(g)
            fill_lens(g)
        elif k.name() in ("sharp_orient_on", "sharp_cam_height") and _job(g).get("ply"):
            orient(g)
    except ValueError:
        pass  # llega con el nodo muriendo al cerrar el script
    except Exception as exc:
        _status(g, "error: %s" % exc)


# --- lente ------------------------------------------------------------------------------------

def fill_lens(g, force=False):
    """Focal y filmback desde la metadata del plate; solo pisa lo que este en 0, salvo con force."""
    src = g.input(0)
    if src is None:
        return
    focal, fb, note = core.lens_from_metadata(src.metadata(), src.width(), src.height())
    missing = [label for v, label in ((focal, "focal"), (fb, "filmback")) if not v]
    _status_meta = note + (" | falta: %s" % ", ".join(missing) if missing else "")
    g["sharp_meta"].setValue(_status_meta)
    for knob, v in (("sharp_focal", focal), ("sharp_filmback", fb)):
        if v and (force or not g[knob].value()):
            g[knob].setValue(round(v, 3))


def fill_lens_force(g):
    fill_lens(g, force=True)


# --- generar ----------------------------------------------------------------------------------

def _job_dir(g, frame):
    script = nuke.root().name()
    base = os.path.dirname(script) if script and script != "Root" else os.path.join(
        os.environ.get("TEMP", "C:/temp"), "sharp_splat")
    d = os.path.join(base, "sharp_splat", "%s_f%04d_%s" % (g.name(), frame, time.strftime("%Y%m%d_%H%M%S")))
    os.makedirs(d)
    return d.replace("\\", "/")


def _export_frame(src, frame, folder):
    """Hilo principal. rgba del plate en el cuadro, en el working space (raw)."""
    exr = folder + "/plate_f%04d.exr" % frame
    with nuke.root():
        w = nuke.nodes.Write(file=exr, file_type="exr", raw=True, channels="rgba")
        w.setInput(0, src)
        try:
            nuke.execute(w, frame, frame)
        finally:
            nuke.delete(w)
    return exr


def generate(g):
    """Hilo principal (boton). Exporta el cuadro, corre SHARP en otro hilo y rearma el interior."""
    if g.name() in _busy:
        nuke.message("%s ya esta generando." % g.name())
        return
    src = g.input(0)
    if src is None:
        nuke.message("Conecta la imagen a la entrada 'plate'.")
        return
    focal, filmback = g["sharp_focal"].value(), g["sharp_filmback"].value()
    if focal <= 0 or filmback <= 0:
        nuke.message("Falta el focal o el filmback.\n'Leer metadata' los llena si vienen en el plate.")
        return
    isolation = g["sharp_mode"].value().startswith("Aislar")
    if isolation and "rgba.alpha" not in src.channels():
        nuke.message("Para aislar, el plate tiene que traer alpha.")
        return
    frame = int(g["sharp_frame"].value())
    opts = {n: (bool if isinstance(d, bool) else type(d))(g["sharp_" + n].value()) for n, d in core.SETTINGS}
    exr = _export_frame(src, frame, _job_dir(g, frame))
    root = nuke.root()
    colorspace = root["workingSpaceLUT"].value() if "workingSpaceLUT" in root.knobs() else "linear"
    job = _job(g)
    version = job.get("version", 0) + 1
    prefix = "sharp_%s_f%04d_v%03d" % (g.name(), frame, version)
    sfocal = core.equiv_focal(focal, filmback, src.width(), src.height())  # lo que SHARP entiende por focal
    _status(g, "v%03d: calculando..." % version)
    _busy.add(g.name())
    t0 = time.time()

    def work():
        task = nuke.ProgressTask("SHARP Splat")

        def progress(frac, msg):
            task.setProgress(int(frac * 100))
            task.setMessage(msg)

        try:
            paths = core.generate(exr, isolation, sfocal, filmback, prefix, colorspace, opts, progress)
            progress(1.0, "Armando la escena...")
            job.update(version=version, frame=frame, exr=exr, ply=paths["ply"], obj=paths.get("obj", ""),
                       status="v%03d (%.0f s)" % (version, time.time() - t0))
            nuke.executeInMainThread(_build, args=(g, paths["nk"], job))
        except Exception as exc:
            nuke.executeInMainThread(_fail, args=(g, version, str(exc)))
        finally:
            _busy.discard(g.name())
            del task

    threading.Thread(target=work, daemon=True).start()


def _fail(g, version, msg):
    _status(g, "v%03d fallo" % version)
    nuke.message("SHARP Splat fallo:\n%s" % msg)


def _link(node, ax):
    node["rot_order"].setValue("ZXY")
    node["xform_order"].setValue("SRT")
    for k in ("translate", "rotate"):
        for i, c in enumerate("xyz"):
            node[k].setExpression("%s.%s.%s" % (ax.name(), k, c), i)
    node["uniform_scale"].setExpression("%s.uniform_scale" % ax.name())


def _build(g, nk, job):
    """Hilo principal. Rearma el interior con el .nk que escribio SHARP-HDR."""
    with g:
        for n in nuke.allNodes():
            if n.name() not in KEEP:
                nuke.delete(n)
        plate, out = nuke.toNode("plate"), nuke.toNode("Output1")
        before = set(nuke.allNodes())
        nuke.nodePaste(nk)
        new = [n for n in nuke.allNodes() if n not in before]
        cam = next(n for n in new if n.Class() == "Camera3")
        geo = next(n for n in new if n.Class() == "GeoReference")
        dot = next(n for n in new if n.Class() == "Dot" and "Splat Source" in n["label"].value())
        proxy = next((n for n in new if n.Class() == "ReadGeo2"), None)

        hold = nuke.nodes.FrameHold(first_frame=job["frame"])
        hold.setInput(0, plate)
        dot.setInput(0, hold)
        # negro con el formato del plate: sin input 0 el SplatRender usaria el formato del proyecto
        bg = nuke.nodes.Multiply(channels="rgba", value=0, label="negro, formato del plate")
        bg.setInput(0, hold)
        ax = nuke.nodes.Axis3(name="SHARP_mundo", label="piso nivelado")
        ax["rot_order"].setValue("ZXY")
        ax["xform_order"].setValue("SRT")
        cam.setInput(0, ax)  # input 0 de Camera3 = padre (con el 1 el render queda negro)
        gt = nuke.nodes.GeoTransform(name="SHARP_mundo_splats")
        gt.setInput(0, geo)
        _link(gt, ax)
        if proxy:
            tg = nuke.nodes.TransformGeo(name="SHARP_mundo_proxy")
            tg.setInput(0, proxy)
            _link(tg, ax)
        sr = nuke.nodes.SplatRender(name="SplatRender")
        sr.setInput(0, bg)
        sr.setInput(1, cam)
        sr.setInput(2, gt)
        out.setInput(0, sr)
        for n in nuke.allNodes():
            nuke.autoplace(n)
    job["cam"] = cam.name()
    _save_job(g, job)
    _wire_cam(g)
    orient(g)


def _wire_cam(g):
    """Con algo en la entrada 'cam' el SplatRender usa esa camara; si no, la de SHARP."""
    job = _job(g)
    with g:
        sr, own = nuke.toNode("SplatRender"), nuke.toNode(job.get("cam", ""))
        if sr is not None and own is not None:
            sr.setInput(1, nuke.toNode("cam") if g.input(1) is not None else own)


# --- escena -----------------------------------------------------------------------------------

def orient(g):
    """Hilo principal. Nivela el piso y aplica la altura de camara (escala uniforme desde la camara,
    asi que el render desde la camara de SHARP no cambia)."""
    job = _job(g)
    with g:
        ax = nuke.toNode("SHARP_mundo")
    if ax is None:
        return
    rx = rz = h = 0.0
    s, note = 1.0, "sin nivelar"
    if g["sharp_orient_on"].value():
        try:
            rx, rz, h = core.floor_orient(*core.read_ply(job["ply"]))
        except RuntimeError as exc:
            note = str(exc)
        else:
            height = g["sharp_cam_height"].value()
            s = height / h if height > 0 else 1.0
            note = "camara a %.2f m del piso, tilt %.1f, roll %.1f" % (h * s, rx, rz)
    ax["rotate"].setValue([rx, 0, rz])
    ax["uniform_scale"].setValue(s)
    ax["translate"].setValue([0, h * s, 0])
    _status(g, "%s | %s" % (job.get("status", ""), note))


def export_camera(g):
    """Camara afuera, igual a la de SHARP en el mundo nivelado (sin la escala, que no cambia la imagen)."""
    job = _job(g)
    with g:
        cam, ax = nuke.toNode(job.get("cam", "")), nuke.toNode("SHARP_mundo")
    if cam is None or ax is None:
        nuke.message("Primero aprieta Generar.")
        return
    with nuke.root():
        c = nuke.nodes.Camera3()
        c.setName("%s_cam1" % g.name(), uncollide=True)
        for k in ("focal", "haperture", "vaperture", "near", "far", "win_translate", "win_scale"):
            c[k].fromScript(cam[k].toScript())
        c["rot_order"].setValue("ZXY")
        c["rotate"].setValue(ax["rotate"].value())
        c["translate"].setValue(ax["translate"].value())
        c["label"].setValue("camara de %s (mundo)" % g.name())
        c.setXYpos(g.xpos() + 150, g.ypos() - 80)
    return c
