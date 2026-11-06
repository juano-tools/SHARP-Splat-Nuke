"""Lo que no depende de Nuke: lente desde metadata, workflow de ComfyUI, lectura del PLY y piso.

Convenciones de SHARP-HDR (flip_for_nuke): camara en el origen mirando a -Z, Y arriba, metros.
"""

import os
import re

# Settings de SharpHDR_Predict, con el nombre del repo y su default. El tipo sale del default.
# Desde ISOLATION_FROM solo cuentan en modo "Aislar objeto".
SETTINGS = [
    ("opacity", 1.50), ("thickness", 1.15), ("sharpness", 0.30),
    ("export_proxy_obj", True), ("proxy_grid_res", 128),
    ("alpha_clip", 0.50), ("edge_erode", 2), ("black_clip", 0.105),
    ("prune_occluded", True), ("surface_depth_thickness", 1.15), ("far_clip", 1.45),
    ("max_splat_size", 1.70), ("depth_edge_inpaint", 6), ("depth_jump_threshold", 0.08),
    ("max_anisotropy", 3.20), ("edge_color_decontaminate", 4), ("grazing_cos_clip", 0.14),
]
ISOLATION_FROM = "alpha_clip"
MODES = ["Escena completa", "Aislar objeto (alpha)"]


# --- lente ------------------------------------------------------------------------------------

def equiv_focal(focal, filmback, width, height):
    """ComfyUI-Sharp lee focal_length_mm como equivalente 35 mm en la DIAGONAL (convert_focallength),
    no como focal sobre filmback_width_mm. Esto da el valor que reproduce focal/filmback reales."""
    return focal / filmback * width * 43.2666 / (width ** 2 + height ** 2) ** 0.5


def _mm(v):
    """Primer numero del valor de metadata, en mm. Sony (RDD 18) guarda micras: > 1000 se divide."""
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    x = float(m.group()) if m else 0.0
    return x / 1000.0 if x > 1000 else x


def lens_from_metadata(md, width, height):
    """(focal_mm o None, filmback_mm o None, nota) desde la metadata de camara del plate.
    Asume que el cuadro completo es el area de sensor grabada; avisa si el aspecto no calza."""
    def pick(pattern, avoid=r"$^"):
        keys = sorted((k for k in md if re.search(pattern, k, re.I) and not re.search(avoid, k, re.I)),
                      key=lambda k: not re.search(r"effective|active", k, re.I))  # primero el area efectiva
        for k in keys:
            if _mm(md[k]) > 0:
                return _mm(md[k]), k
        return None, None
    focal, kf = pick(r"focal.?length", r"35|equiv")
    fb, kw = pick(r"(sensor|filmback|aperture).*width")
    fb_h, _ = pick(r"(sensor|filmback|aperture).*height")
    notes = []
    if fb:
        notes.append("filmback %.2f mm (%s)" % (fb, kw.split("/")[-1]))
        if fb_h and abs(fb / fb_h - float(width) / height) > 0.02 * width / height:
            notes.append("OJO: el aspecto del sensor no calza con la imagen (recorte?)")
    if focal:
        notes.append("focal %.1f mm (%s)" % (focal, kf.split("/")[-1]))
    return focal, fb, "; ".join(notes) or "sin datos de lente ni sensor"


# --- ComfyUI ----------------------------------------------------------------------------------

def comfy():
    """Cliente de ComfyUI de GenFill: mismo servidor, mismo arranque automatico de Comfy Desktop."""
    try:
        from genfill.backends import comfyui
    except ImportError:
        raise RuntimeError("SHARP Splat usa el cliente de ComfyUI de GenFill, y GenFill no esta instalado.")
    return comfyui


def build_workflow(c, exr, isolation, focal, filmback, prefix, colorspace, opts):
    g = c._Graph()
    model = g.add("LoadSharpModel", precision="auto")
    img = g.add("LoadEXR", filepath=exr, tonemap="linear", image_load_cap=0,
                skip_first_images=0, select_every_nth=1)
    pred = g.add("SharpHDR_Predict", model=model, image=img,
                 mode="Object Isolation" if isolation else "Full Scene",
                 alpha=c._out(img, 1) if isolation else None, invert_alpha=False,  # LoadEXR: alpha derecho
                 focal_length_mm=float(focal), filmback_width_mm=float(filmback),
                 output_prefix=prefix, working_colorspace=colorspace, **opts)
    for i in (0, 6, 7):  # ply_path, nuke_script_path, proxy_obj_path, para leerlos del historial
        g.add("PreviewAny", source=c._out(pred, i))
    return g.nodes


def generate(exr, isolation, focal, filmback, prefix, colorspace, opts, progress=None):
    """Cualquier hilo. Devuelve {"nk", "ply", "obj"} con lo que escribio SHARP-HDR ("obj" puede faltar)."""
    c = comfy()
    c.wait_for_server(progress)
    if progress:
        progress(0.3, "SHARP (la primera vez baja y carga el modelo)...")
    # Sin `cancelled` a proposito: el /interrupt de c.run desincroniza el worker de comfy-env
    # de ComfyUI-Sharp y la corrida siguiente queda colgada (medido 2026-11-04).
    # shortcut: no se puede cancelar a mitad (~6 s); si comfy-env lo arregla, pasar cancelled.
    hist = c.run(build_workflow(c, exr, isolation, focal, filmback, prefix, colorspace, opts))
    paths = {}
    for out in hist.get("outputs", {}).values():
        text = out.get("text")
        if text:
            f = str(text[0] if isinstance(text, (list, tuple)) else text)
            if os.path.isfile(f):
                paths[f.rsplit(".", 1)[-1].lower()] = f.replace("\\", "/")
    if "nk" in paths and "ply" in paths:
        return paths
    raise RuntimeError("SHARP-HDR no devolvio el .nk o el .ply (revisa la consola de ComfyUI).")


# --- piso -------------------------------------------------------------------------------------

def read_ply(path):
    """xyz y opacity (logit) del PLY de SHARP-HDR (binario, un solo elemento vertex)."""
    import numpy as np
    types = {"float": "<f4", "double": "<f8", "uchar": "u1", "int": "<i4"}
    props = []
    with open(path, "rb") as f:
        while True:
            line = f.readline().decode("ascii").strip()
            if line.startswith("property"):
                props.append(line.split()[1:])
            if line == "end_header":
                break
        a = np.fromfile(f, dtype=[(n, types[t]) for t, n in props])
    return np.stack([a["x"], a["y"], a["z"]], 1).astype(np.float64), a["opacity"].astype(np.float64)


def floor_orient(P, opacity, iters=1500, seed=0):
    """Piso por RANSAC en los splats bajo la camara.
    Devuelve (rx, rz, altura) de un Axis ZXY/SRT que deja ese piso en Y=0, con el origen bajo la camara."""
    import numpy as np
    d = -P[:, 2]
    # shortcut: busca el piso bajo la camara (Y < -0.5); en planos cenitales no hay piso asi y falla
    Q = P[(opacity > 0) & (P[:, 1] < -0.5) & (d > 0) & (d < 40)]  # opacity > 0 = alpha > 0.5
    if len(Q) < 100:
        raise RuntimeError("No encontre piso bajo la camara.")
    rng = np.random.default_rng(seed)
    S = Q[rng.choice(len(Q), min(len(Q), 50000), replace=False)]
    tol = lambda X: 0.02 * np.maximum(-X[:, 2], 1)  # el error de depth crece con la distancia
    best, plane = 0, None
    for _ in range(iters):
        a, b, c = S[rng.choice(len(S), 3, replace=False)]
        n = np.cross(b - a, c - a)
        length = np.linalg.norm(n)
        if length < 1e-9:
            continue
        n = n / length * (1 if n[1] >= 0 else -1)
        if n[1] < 0.85:  # solo planos casi horizontales (< 32 grados)
            continue
        k = int((np.abs((S - a) @ n) < tol(S)).sum())
        if k > best:
            best, plane = k, (n, a)
    if plane is None:
        raise RuntimeError("No encontre piso bajo la camara.")
    n, a = plane
    inl = Q[np.abs((Q - a) @ n) < tol(Q)]
    c = inl.mean(0)
    n = np.linalg.svd(inl - c, full_matrices=False)[2][2]
    n = n if n[1] >= 0 else -n
    rz = np.arctan2(n[0], n[1])                  # Rz lleva la normal al plano YZ...
    rx = -np.arctan2(n[2], np.hypot(n[0], n[1]))  # ...y Rx la deja en +Y
    return float(np.degrees(rx)), float(np.degrees(rz)), float(-(n @ c))
