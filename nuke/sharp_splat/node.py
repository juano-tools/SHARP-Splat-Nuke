"""Nodo SHARP Splat (Group): un cuadro del plate -> Gaussian splats HDR con SHARP-HDR -> SplatRender.

Entradas: plate (la imagen) y cam (opcional: una cámara propia para vistas nuevas, en el mundo
nivelado). Salida: el render de los splats. "Generar" corre SHARP en el cuadro elegido y rearma
el interior; el piso se nivela solo y la escena queda en metros.
"""

import base64
import json
import os
import threading
import time

import nuke

from . import __version__, core

GREEN, AMBER = "#7fd1a8", "#f2a65a"  # los colores del ícono

KEEP = ("plate", "cam", "Output1")  # lo único del interior que Generar no borra
CARD_KNOBS = ("sharp_pick", "sharp_card_radius", "sharp_card_size", "sharp_card_spin", "sharp_card_upright")  # mueven la card viva
EXPORTS = ["Cámara", "Cámara + splats", "Cámara + splats + proxy", "Escena completa (con SplatRender)"]

# Ajustes de SharpHDR_Predict: nombre visible, descripción y rango (los min/max de SHARP-HDR).
SECTIONS = {"opacity": "splats", "export_proxy_obj": "malla proxy", core.ISOLATION_FROM: "aislar objeto (solo en ese modo)"}
PARAMS = {
    "opacity": ("opacidad", "Multiplica la opacidad de todos los splats. Más alto = superficies más sólidas,\n"
                "con menos huecos que dejan ver a través.", 0.1, 5),
    "thickness": ("tamaño", "Multiplica el tamaño de todos los splats. Súbelo un poco si aparecen huecos\n"
                  "al mover la cámara.", 0.5, 3),
    "sharpness": ("nitidez", "Enfoque (unsharp mask) que se aplica al color HDR antes de pasarlo a los splats.", 0, 1),
    "export_proxy_obj": ("crear proxy", "Escribe una malla liviana (.obj) hecha con la profundidad de los splats,\n"
                         "para proyectar o hacer layout. Se saca con 'Cámara + splats + proxy'.", 0, 1),
    "proxy_grid_res": ("resolución", "Vértices a lo ancho de la malla proxy.", 32, 512),
    "alpha_clip": ("umbral alpha", "Borra los splats donde el alpha está bajo este valor.", 0, 0.99),
    "edge_erode": ("achicar borde (px)", "Achica el matte estos píxeles para que no se cuele el fondo en el borde.", 0, 15),
    "black_clip": ("quitar negros", "Borra los splats casi negros bajo este valor (halos oscuros o fondo que se cuela).", 0, 0.5),
    "prune_occluded": ("limpiar por profundidad", "Activa los filtros de profundidad: profundidad del objeto,\n"
                       "salto en el borde y límite lejano.", 0, 1),
    "surface_depth_thickness": ("profundidad del objeto", "Conserva los splats hasta esta proporción de profundidad detrás\n"
                                "de la superficie del frente; borra las capas ocultas de atrás.", 1.01, 3),
    "far_clip": ("límite lejano", "Borra los splats más lejos que este múltiplo de la profundidad media del objeto.", 1.05, 10),
    "max_splat_size": ("tamaño máximo", "Borra los splats más grandes que este múltiplo del tamaño medio en pantalla.", 0.2, 10),
    "depth_edge_inpaint": ("radio del borde (px)", "Radio para estimar la superficie del frente cerca del borde del matte.", 0, 20),
    "depth_jump_threshold": ("salto en el borde", "Salto de profundidad relativo que, en el borde del matte, se toma como un corte:\n"
                             "esos splats se borran. También corta caras de la malla proxy.", 0, 1),
    "max_anisotropy": ("estiramiento máximo", "Limita cuánto se puede alargar un splat. Quita las 'cortinas' estiradas en los bordes.", 1.1, 15),
    "edge_color_decontaminate": ("limpiar color del borde", "Pasadas de relleno de color en el borde para quitar el color del fondo que se cuela.", 0, 12),
    "grazing_cos_clip": ("quitar los de canto", "Borra los splats del borde que se ven casi de canto\n"
                         "(coseno con el rayo de vista bajo este valor).", 0, 0.6),
}
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
    g["sharp_status"].setValue("<span style='color:%s'>%s</span>" % (GREEN, text))


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
    add(nuke.Text_Knob("sharp_header", "",
                       "<span style='font-size:15pt; color:%s'><b>SHARP</b></span>"
                       "<span style='font-size:15pt; color:%s'> Splat</span>"
                       "<span style='color:#888'>&nbsp;&nbsp;v%s</span><br>"
                       "<span style='color:#aaa'>un cuadro del plate &rarr; Gaussian splats HDR en metros</span>"
                       % (GREEN, AMBER, __version__)))
    add(nuke.Text_Knob("sharp_div0", ""))
    add(nuke.Text_Knob("sharp_status", "estado", "sin generar"),
        tip="Versión generada, cuánto tardó y el resultado de la nivelación.")
    add(nuke.Int_Knob("sharp_frame", "cuadro"), tip="Cuadro del plate que SHARP convierte en splats.")
    g["sharp_frame"].setValue(nuke.frame())
    add(nuke.PyScript_Knob("sharp_frame_now", "usar el actual",
                           "nuke.thisNode()['sharp_frame'].setValue(nuke.frame())"), newline=False,
        tip="Pone el cuadro en que está el timeline.")
    add(nuke.Enumeration_Knob("sharp_mode", "modo", core.MODES),
        tip="Escena completa: todo el cuadro.\n"
            "Aislar objeto: solo lo que está dentro del alpha del plate (los ajustes de 'aislar objeto' afinan el borde).")
    k = add(nuke.Double_Knob("sharp_focal", "focal (mm)"),
            tip="Focal del lente con que se filmó. Junto con el ancho del sensor define el campo de visión:\n"
                "si está mal, la escena sale deformada y con la escala equivocada.")
    k.setRange(0, 100)
    k = add(nuke.Double_Knob("sharp_filmback", "ancho sensor (mm)"),
            tip="Ancho del sensor que corresponde al cuadro completo de la imagen (filmback).\n"
                "Si se grabó con recorte, es el ancho del área grabada, no el del sensor entero.")
    k.setRange(0, 50)
    add(nuke.Text_Knob("sharp_meta", "metadata", "-"),
        tip="Qué encontró en la metadata de cámara del plate y qué falta escribir a mano.")
    add(nuke.PyScript_Knob("sharp_read_meta", "Leer metadata", _cmd("fill_lens_force")),
        tip="Vuelve a llenar focal y ancho de sensor con la metadata del plate (pisa lo escrito).")
    add(nuke.Text_Knob("sharp_div1", ""))
    add(nuke.PyScript_Knob("sharp_generate", "<span style='color:%s'><b>&#9654; Generar</b></span>" % GREEN, _cmd("generate")),
        tip="Corre SHARP en ComfyUI (vía GenFill) y rearma la escena. Unos 5 s; la primera vez, más.\n"
            "Después de cambiar cualquier ajuste de SHARP hay que volver a Generar.")

    def section(name, label, closed=True):  # grupo plegable; cierra el anterior si hay uno abierto
        if section.open:
            g.addKnob(nuke.Tab_Knob(section.open + "_end", None, nuke.TABENDGROUP))
        section.open = name
        if name:
            g.addKnob(nuke.Tab_Knob(name, label, nuke.TABBEGINCLOSEDGROUP if closed else nuke.TABBEGINGROUP))
    section.open = None

    for name, default in core.SETTINGS:
        if name in SECTIONS:
            section("sharp_grp_" + name, SECTIONS[name])
        label, tip, lo, hi = PARAMS[name]
        cls = nuke.Boolean_Knob if isinstance(default, bool) else nuke.Int_Knob if isinstance(default, int) else nuke.Double_Knob
        k = add(cls("sharp_" + name, label), tip=tip)  # el nombre interno sigue siendo el de SHARP-HDR
        if cls is nuke.Double_Knob:
            k.setRange(lo, hi)
        k.setValue(default)

    section("sharp_grp_scene", "escena", closed=False)
    add(nuke.Boolean_Knob("sharp_orient_on", "nivelar piso"),
        tip="Busca el piso bajo la cámara y lo deja horizontal en Y=0, con el origen bajo la cámara.\n"
            "El render desde la cámara de SHARP no cambia.")
    g["sharp_orient_on"].setValue(True)
    k = add(nuke.Double_Knob("sharp_cam_height", "altura cámara (m)"),
            tip="Escala la escena para que la cámara quede a esta altura del piso.\n"
                "0 = la escala de SHARP, que ya es métrica si el focal y el ancho de sensor son los reales.")
    k.setRange(0, 3)
    add(nuke.XYZ_Knob("sharp_adj_rot", "girar escena (°)"),
        tip="Se suma a la nivelación: X corrige el tilt, Z el roll e Y gira la escena\n"
            "sobre el eje vertical (por ejemplo, para alinear una calle con Z).")
    add(nuke.XYZ_Knob("sharp_adj_pos", "mover escena (m)"),
        tip="Se suma a la posición de la escena. Y sube o baja el piso.")
    section("sharp_grp_card", "card sobre una superficie", closed=False)
    add(nuke.Text_Knob("sharp_card_help", "",
                       "<span style='color:#aaa'>Aprieta Nueva card y arrastra el punto en el viewer sobre una superficie<br>"
                       "del plate (pared, piso, letrero): la card se pega a ella. La grilla muestra dónde queda.</span>"))
    add(nuke.XY_Knob("sharp_pick", "punto"),
        tip="Píxel del plate donde se pega la card. Se arrastra en el viewer con el panel abierto.")
    k = add(nuke.Double_Knob("sharp_card_radius", "radio de lectura (px)"),
            tip="Alrededor del punto, de dónde se lee la superficie para orientar la card.\n"
                "Más grande = más estable; más chico = sigue superficies pequeñas.")
    k.setRange(20, 600)
    k.setValue(120)
    add(nuke.WH_Knob("sharp_card_size", "tamaño (m)"), tip="Ancho y alto de la card, en metros.")
    g["sharp_card_size"].setValue([1, 1])
    k = add(nuke.Double_Knob("sharp_card_spin", "girar en el plano (°)"),
            tip="Gira la card sobre su superficie. En 0, en una pared el borde de abajo queda horizontal.")
    k.setRange(-180, 180)
    add(nuke.Boolean_Knob("sharp_card_upright", "enderezar"),
        tip="Paredes verticales y pisos horizontales exactos (en el mundo nivelado): quita el cabeceo que deja\n"
            "el ruido de profundidad. Desmárcalo para superficies inclinadas, como la carrocería de un auto.")
    g["sharp_card_upright"].setValue(True)
    add(nuke.Boolean_Knob("sharp_card_grid", "ver grilla"),
        tip="Dibuja la card viva como una grilla sobre la salida del nodo.")
    g["sharp_card_grid"].setValue(True)
    add(nuke.PyScript_Knob("sharp_card", "<span style='color:%s'><b>Nueva card</b></span>" % AMBER, _cmd("create_card")),
        newline=False,
        tip="Crea afuera un GeoCard pegado a la superficie bajo el punto, con un tamaño inicial según el radio.\n"
            "La última card creada sigue al punto; con otra Nueva card, la anterior queda fija.")
    section(None, None)
    add(nuke.Enumeration_Knob("sharp_export_what", "sacar", EXPORTS),
        tip="Crea afuera copias en el mundo nivelado, con los valores fijos, para manipularlas.\n"
            "La cámara se puede animar y conectar a la entrada 'cam' para ver la escena desde otro lado.")
    add(nuke.PyScript_Knob("sharp_export", "<span style='color:%s'><b>Crear</b></span>" % AMBER, _cmd("export")), newline=False,
        tip="Crea lo elegido en 'sacar', a la derecha del nodo.")
    add(nuke.Boolean_Knob("sharp_export_rec709", "splats en Rec.709 (previs)"),
        tip="Los splats que salen usan una copia del PLY con el color en Rec.709 de pantalla, para verlos\n"
            "en el viewer 3D como en el monitor. Solo previs: ese color ya no es lineal y no sirve para render.")
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
        _default_pick(g)
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
        elif k.name() == "sharp_orient_on" and _job(g).get("ply"):
            orient(g)
        elif k.name() in ("sharp_cam_height", "sharp_adj_rot", "sharp_adj_pos"):
            apply_orient(g)
        elif k.name() in CARD_KNOBS and _job(g).get("card"):
            update_card(g)
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
    """Hilo principal (botón). Exporta el cuadro, corre SHARP en otro hilo y rearma el interior."""
    if g.name() in _busy:
        nuke.message("%s ya está generando." % g.name())
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
    _status(g, "v%03d falló" % version)
    nuke.message("SHARP Splat falló:\n%s" % msg)


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
        # grilla de la card viva: textura llevada en 2D a las esquinas proyectadas (un plano en perspectiva
        # es un corner pin exacto). La Card2 + ScanlineRender clásica no dibujaba nada en 17.1.
        tex = nuke.nodes.Constant(channels="rgba", format="square_1K")
        grid = nuke.nodes.Grid(number=8, size=6)
        grid["color"].setValue([0.95, 0.6, 0.25, 1])  # como argumento al crear el nodo, Nuke lo ignora
        grid.setInput(0, tex)
        pin = nuke.nodes.CornerPin2D(name="SHARP_card_grilla", disable=True)
        for i, xy in enumerate(((0, 0), (1024, 0), (1024, 1024), (0, 1024)), 1):
            pin["from%d" % i].setValue(list(xy))
        pin.setInput(0, grid)
        mrg = nuke.nodes.Merge2(name="SHARP_grilla_over", mix=0.8)
        mrg.setInput(0, sr)
        mrg.setInput(1, pin)
        mrg["disable"].setExpression("!parent.sharp_card_grid || SHARP_card_grilla.disable")
        out.setInput(0, mrg)
        for n in nuke.allNodes():
            nuke.autoplace(n)
    job["cam"] = cam.name()
    _save_job(g, job)
    _wire_cam(g)
    _default_pick(g)
    orient(g)


def _default_pick(g):
    """El punto empieza en el centro del plate, solo si sigue en 0."""
    if "sharp_pick" in g.knobs() and g.input(0) is not None and g["sharp_pick"].value() == [0.0, 0.0]:
        g["sharp_pick"].setValue([g.input(0).width() / 2.0, g.input(0).height() / 2.0])


def create_card(g):
    """Botón Nueva card. Crea un GeoCard afuera, lo deja como la card que sigue al punto y le da un
    tamaño inicial que cubre el radio de lectura."""
    job = _job(g)
    if not job.get("cam"):
        nuke.message("Primero aprieta Generar.")
        return None
    with nuke.root():
        c = nuke.nodes.GeoCard()
        c.setName("%s_card1" % g.name(), uncollide=True)
        c["image_aspect"].setValue(False)  # card de 1 x 1: el tamaño va en scaling
        c["rot_order"].setValue("ZXY")
        c.setXYpos(g.xpos() + 200, g.ypos() + 60)
    job["card"] = c.name()
    _save_job(g, job)
    fit = update_card(g, quiet=False)
    if not fit:
        nuke.delete(c)
        job.pop("card")
        _save_job(g, job)
        return None
    side = 2 * g["sharp_card_radius"].value() * fit["distance"] / fit["f_px"]
    g["sharp_card_size"].setValue([side, side])
    update_card(g)  # en la GUI el knobChanged ya lo hizo; sin GUI hace falta
    return c


_proj_cache = {}  # (ply, f_px, W, H) -> splats proyectados por la cámara de SHARP (fija por corrida)


def _projected(ply, f_px, W, H):
    key = (ply, f_px, W, H)
    if key not in _proj_cache:
        import numpy as np
        P, op = core.read_ply(ply)
        P = P[(op > 0) & (P[:, 2] < -1e-3)]
        u = W / 2.0 + f_px * P[:, 0] / -P[:, 2]
        v = H / 2.0 + f_px * P[:, 1] / -P[:, 2]
        on = (u >= 0) & (u < W) & (v >= 0) & (v < H)
        _proj_cache.clear()  # shortcut: solo el último PLY en memoria (~30 MB); con varios nodos alternados se relee
        _proj_cache[key] = (u[on], v[on], P[on])
    return _proj_cache[key]


def update_card(g, quiet=True):
    """Pega la card viva (y la grilla) a la superficie bajo el punto. Toma los splats que la cámara de SHARP
    ve dentro del radio (el pase P de SplatRender 17.1v2 sale corrido (W-H)/2 en vertical: no se usa),
    los lleva al mundo y ajusta un plano. quiet = el error va al label de la card. Devuelve el ajuste o None."""
    import numpy as np
    job = _job(g)
    with g:
        cam, ax, grid = nuke.toNode(job.get("cam", "")), nuke.toNode("SHARP_mundo"), nuke.toNode("SHARP_card_grilla")
    if grid is not None and grid.Class() != "CornerPin2D":
        grid = None  # nodo de la 0.7 (Card2 + ScanlineRender, no dibujaba): la grilla nueva llega con Generar
    card = nuke.toNode(job.get("card", "")) if job.get("card") else None
    if card is None or cam is None or ax is None or g.input(0) is None:
        return None
    W, H = g.input(0).width(), g.input(0).height()
    f_px = cam["focal"].value() / cam["haperture"].value() * W
    u, v, P = _projected(job["ply"], f_px, W, H)
    (px, py), r = g["sharp_pick"].value(), g["sharp_card_radius"].value()
    idx = np.flatnonzero((np.abs(u - px) < r) & (np.abs(v - py) < r))
    idx = idx[(u[idx] - px) ** 2 + (v[idx] - py) ** 2 < r * r]
    R, s, T = core.rot_zxy(*ax["rotate"].value()), ax["uniform_scale"].value(), np.array(ax["translate"].value())
    try:
        upright = g["sharp_card_upright"].value() if "sharp_card_upright" in g.knobs() else True
        fit = core.card_at_point((s * P[idx]) @ R.T + T, T, R, f_px, (W, H), (px, py), g["sharp_card_spin"].value(), r,
                                 upright)
    except RuntimeError as exc:
        if not quiet:
            nuke.message(str(exc))
        card["label"].setValue("sin ajustar: %s" % exc)
        return None
    w, h = g["sharp_card_size"].value()
    card["translate"].setValue(fit["translate"])
    card["rotate"].setValue(list(fit["rotate"]))
    card["scaling"].setValue([w, h, 1])
    if grid is not None:
        # esquinas de la card (local ±w/2, ±h/2) proyectadas por la cámara de SHARP, en el orden de from1..4
        Rc, c = core.rot_zxy(*fit["rotate"]), np.array(fit["translate"])
        corners = [R.T @ (c + Rc @ np.array([sx * w / 2, sy * h / 2, 0]) - T) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        visible = g.input(1) is None and all(d[2] < 0 for d in corners)
        if visible:
            for i, d in enumerate(corners, 1):
                grid["to%d" % i].setValue([W / 2.0 + f_px * d[0] / -d[2], H / 2.0 + f_px * d[1] / -d[2]])
        grid["disable"].setValue(not visible)
    card["label"].setValue("%.2f x %.2f m, a %.1f m" % (w, h, fit["distance"]))
    return dict(fit, f_px=f_px)


def _wire_cam(g):
    """Con algo en la entrada 'cam' el SplatRender usa esa cámara; si no, la de SHARP."""
    job = _job(g)
    with g:
        sr, own = nuke.toNode("SplatRender"), nuke.toNode(job.get("cam", ""))
        if sr is not None and own is not None:
            sr.setInput(1, nuke.toNode("cam") if g.input(1) is not None else own)
    if job.get("card"):
        update_card(g)  # la grilla solo calza desde la cámara de SHARP: se apaga con otra cámara


# --- escena -----------------------------------------------------------------------------------

def orient(g):
    """Hilo principal. Busca el piso (si 'nivelar piso' está marcado), lo guarda y aplica."""
    job = _job(g)
    job["floor"], job["floor_note"] = None, "sin nivelar"
    if g["sharp_orient_on"].value():
        try:
            job["floor"] = core.floor_orient(*core.read_ply(job["ply"]))
        except RuntimeError as exc:
            job["floor_note"] = str(exc)
    _save_job(g, job)
    apply_orient(g)


def apply_orient(g):
    """Hilo principal, sin leer el PLY. Axis = piso guardado + escala de la altura + ajuste manual.
    El ajuste se suma a los ángulos: Y gira la escena en el mundo; X y Z corrigen tilt y roll."""
    job = _job(g)
    with g:
        ax = nuke.toNode("SHARP_mundo")
    if ax is None:
        return
    rx, rz, h = job.get("floor") or (0.0, 0.0, 0.0)
    height = g["sharp_cam_height"].value()
    s = height / h if height > 0 and h > 0 else 1.0  # escala uniforme desde la cámara: el render no cambia
    adj = lambda k: g[k].value() if k in g.knobs() else [0.0, 0.0, 0.0]  # nodos de la 0.2 no lo tienen
    ar, ap = adj("sharp_adj_rot"), adj("sharp_adj_pos")
    ax["rotate"].setValue([rx + ar[0], ar[1], rz + ar[2]])
    ax["uniform_scale"].setValue(s)
    ax["translate"].setValue([ap[0], h * s + ap[1], ap[2]])
    note = job.get("floor_note", "")
    if job.get("floor"):
        note = "cámara a %.2f m del piso, tilt %.1f, roll %.1f" % (h * s, rx, rz)
    _status(g, "%s | %s" % (job.get("status", ""), note))
    if job.get("card"):
        update_card(g)  # la card viva sigue al mundo


def _clone(src, name):
    """Copia afuera (contexto actual) con los knobs no default de src, sin entradas."""
    n = getattr(nuke.nodes, src.Class())()
    script = src.writeKnobs(nuke.WRITE_NON_DEFAULT_ONLY | nuke.TO_SCRIPT)
    n.readKnobs("\n".join(l for l in script.split("\n") if not l.startswith(("name ", "xpos ", "ypos ", "selected "))))
    n.setName(name, uncollide=True)
    return n


def _bake(node, ax, scale=True):
    """Transform fijo igual al del Axis SHARP_mundo (rot_order ZXY, SRT)."""
    node["rot_order"].setValue("ZXY")
    node["xform_order"].setValue("SRT")
    node["rotate"].setValue(ax["rotate"].value())
    node["translate"].setValue(ax["translate"].value())
    if scale:
        node["uniform_scale"].setValue(ax["uniform_scale"].value())


def export(g, what=None):
    """Boton Crear. Saca afuera lo elegido en 'sacar', en el mundo nivelado y con valores fijos.
    La cámara va sin la escala del mundo: escalar una cámara no cambia su imagen."""
    what = what or g["sharp_export_what"].value()
    job = _job(g)
    with g:
        cam, ax = nuke.toNode(job.get("cam", "")), nuke.toNode("SHARP_mundo")
        geo = (nuke.allNodes("GeoReference") or [None])[0]
        proxy = (nuke.allNodes("ReadGeo2") or [None])[0]
    if cam is None or ax is None or geo is None:
        nuke.message("Primero aprieta Generar.")
        return []
    full = what.startswith("Escena")
    base = g.name()
    made = []
    with nuke.root():
        c = _clone(cam, base + "_cam1")
        _bake(c, ax, scale=False)
        c["label"].setValue("cámara de %s" % base)
        made.append(c)
        gt = None
        if "splats" in what or full:
            gr = _clone(geo, base + "_splats1")
            if g["sharp_export_rec709"].value() if "sharp_export_rec709" in g.knobs() else False:
                ws = nuke.root()["workingSpaceLUT"].value().lower() if "workingSpaceLUT" in nuke.root().knobs() else ""
                gr["file_path"].setValue(core.preview_ply(geo["file_path"].value(), acescg="acescg" in ws or "ap1" in ws))
                gr["label"].setValue("Rec.709 (solo previs)")
            gt = nuke.nodes.GeoTransform()
            gt.setName(base + "_splats_mundo1", uncollide=True)
            gt.setInput(0, gr)
            _bake(gt, ax)
            made += [gr, gt]
        if ("proxy" in what or full) and proxy is not None:
            rg = _clone(proxy, base + "_proxy1")
            tg = nuke.nodes.TransformGeo()
            tg.setName(base + "_proxy_mundo1", uncollide=True)
            tg.setInput(0, rg)
            _bake(tg, ax)
            made += [rg, tg]
        if full and g.input(0) is not None:
            hold = nuke.nodes.FrameHold(first_frame=job["frame"])
            hold.setInput(0, g.input(0))
            bg = nuke.nodes.Multiply(channels="rgba", value=0, label="negro, formato del plate")
            bg.setInput(0, hold)
            sr = nuke.nodes.SplatRender()
            sr.setName(base + "_SplatRender1", uncollide=True)
            sr.setInput(0, bg)
            sr.setInput(1, c)
            sr.setInput(2, gt)
            made += [hold, bg, sr]
        # en columnas a la derecha del grupo, cada nodo bajo su entrada
        x0, y0 = g.xpos() + 200, g.ypos() - 150
        for i, n in enumerate(made):
            up = n.input(0) if n.inputs() and n.input(0) in made else None
            n.setXYpos(up.xpos() if up else x0 + 120 * i, up.ypos() + 70 if up else y0)
        if full:
            sr.setXYpos(gt.xpos(), gt.ypos() + 120)
        for n in nuke.selectedNodes():
            n.setSelected(False)
        for n in made:
            n.setSelected(True)
    return made
