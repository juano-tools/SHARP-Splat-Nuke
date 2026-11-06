"""Lo que no depende de Nuke: lente desde metadata, workflow de ComfyUI, lectura del PLY y piso.

Convenciones de SHARP-HDR (flip_for_nuke): cámara en el origen mirando a -Z, Y arriba, metros.
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
    """Primer número del valor de metadata, en mm. Sony (RDD 18) guarda micras: > 1000 se divide."""
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    x = float(m.group()) if m else 0.0
    return x / 1000.0 if x > 1000 else x


def lens_from_metadata(md, width, height):
    """(focal_mm o None, filmback_mm o None, nota) desde la metadata de cámara del plate.
    Asume que el cuadro completo es el área de sensor grabada; avisa si el aspecto no calza."""
    def pick(pattern, avoid=r"$^"):
        keys = sorted((k for k in md if re.search(pattern, k, re.I) and not re.search(avoid, k, re.I)),
                      key=lambda k: not re.search(r"effective|active", k, re.I))  # primero el área efectiva
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
        raise RuntimeError("SHARP Splat usa el cliente de ComfyUI de GenFill, y GenFill no está instalado.")
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
    raise RuntimeError("SHARP-HDR no devolvió el .nk o el .ply (revisa la consola de ComfyUI).")


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


SH_C0 = 0.28209479177387814  # color = 0.5 + SH_C0 * f_dc
ACESCG_TO_REC709 = [[1.70505, -0.62179, -0.08326], [-0.13026, 1.14080, -0.01055], [-0.02400, -0.12897, 1.15297]]


def _ply_raw(src):
    """(header en bytes, arreglo estructurado con todas las propiedades) de un PLY binario de un elemento."""
    import numpy as np
    types = {"float": "<f4", "double": "<f8", "uchar": "u1", "int": "<i4"}
    with open(src, "rb") as f:
        header = b""
        while not header.rstrip().endswith(b"end_header"):
            line = f.readline()
            if not line:
                raise RuntimeError("PLY sin end_header: %s" % src)
            header += line
        props = [l.split()[1:] for l in header.decode("ascii").splitlines() if l.startswith("property")]
        return header, np.fromfile(f, dtype=[(n, types[t]) for t, n in props])


def to_world(P, R, s, T):
    """Del espacio de SHARP al mundo nivelado (Axis SHARP_mundo: SRT, rot_order ZXY)."""
    import numpy as np
    return (s * P) @ np.asarray(R).T + np.asarray(T)


def fit_box(W, cam_pos, k=3.0):
    """Caja (xmin, ymin, zmin, xmax, ymax, zmax) con los splats a menos de k veces la distancia mediana
    a la cámara: deja fuera lo que SHARP manda lejos (cielo, luces quemadas)."""
    import numpy as np
    d = np.linalg.norm(W - np.asarray(cam_pos), axis=1)
    Q = W[d < k * np.median(d)]
    return [round(float(v), 2) for v in np.r_[Q.min(0), Q.max(0)]]


def crop_ply(src, dst, box, R, s, T):
    """Copia de src con solo los splats dentro de box (mundo nivelado, metros). Devuelve (quedan, total)."""
    import numpy as np
    header, a = _ply_raw(src)
    W = to_world(np.stack([a["x"], a["y"], a["z"]], 1).astype(np.float64), R, s, T)
    keep = np.all((W >= box[:3]) & (W <= box[3:]), 1)
    if not keep.any():  # un PLY sin splats rompe el GeoReference ("Error translating PLY to USD")
        raise RuntimeError("La caja quedó vacía: no hay splats dentro.")
    header = re.sub(rb"element vertex \d+", b"element vertex %d" % keep.sum(), header)
    with open(dst + ".tmp", "wb") as f:  # a medio escribir no queda con el nombre final
        f.write(header)
        a[keep].tofile(f)
    os.replace(dst + ".tmp", dst)
    return int(keep.sum()), len(a)


def preview_ply(src, acescg=True):
    """Copia del PLY con el color en Rec.709 de pantalla (gamma 2.4, recortado a 0-1), para ver los splats
    en el viewer 3D como en el monitor. Solo previs: el color deja de ser lineal. Se crea una vez por PLY."""
    import numpy as np
    dst = src[:-4] + "_rec709.ply"
    if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return dst
    header, a = _ply_raw(src)
    lin = 0.5 + SH_C0 * np.stack([a["f_dc_%d" % i] for i in range(3)], 1).astype(np.float64)
    if acescg:
        lin = lin @ np.array(ACESCG_TO_REC709).T
    disp = np.clip(lin, 0, 1) ** (1 / 2.4)
    for i in range(3):
        a["f_dc_%d" % i] = (disp[:, i] - 0.5) / SH_C0
    with open(dst, "wb") as f:
        f.write(header)
        a.tofile(f)
    return dst


def _ransac_plane(Q, tol, accept=None, iters=1500, seed=0, max_samples=50000, weights=None):
    """Plano dominante de Q (N x 3): RANSAC + ajuste por SVD de los inliers. tol(X) = tolerancia por punto.
    accept(n, a) filtra candidatos (normal, punto del plano); weights = peso de cada punto en el puntaje
    (por defecto todos 1). Devuelve (normal, centroide de los inliers) o None."""
    import numpy as np
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(Q), min(len(Q), max_samples), replace=False)
    S = Q[pick]
    tol_s = tol(S)
    w_s = np.ones(len(S)) if weights is None else np.asarray(weights)[pick]
    best, plane = 0, None
    for _ in range(iters):
        a, b, c = S[rng.choice(len(S), 3, replace=False)]
        n = np.cross(b - a, c - a)
        length = np.linalg.norm(n)
        if length < 1e-9:
            continue
        n = n / length
        if accept and not accept(n, a):
            continue
        k = float(w_s[np.abs((S - a) @ n) < tol_s].sum())
        if k > best:
            best, plane = k, (n, a)
    if plane is None:
        return None
    n, a = plane
    inl = Q[np.abs((Q - a) @ n) < tol(Q)]
    c = inl.mean(0)
    return np.linalg.svd(inl - c, full_matrices=False)[2][2], c


def floor_orient(P, opacity):
    """Piso por RANSAC en los splats bajo la cámara.
    Devuelve (rx, rz, altura) de un Axis ZXY/SRT que deja ese piso en Y=0, con el origen bajo la cámara."""
    import numpy as np
    d = -P[:, 2]
    # shortcut: busca el piso bajo la cámara (Y < -0.5); en planos cenitales no hay piso así y falla
    Q = P[(opacity > 0) & (P[:, 1] < -0.5) & (d > 0) & (d < 40)]  # opacity > 0 = alpha > 0.5
    plane = _ransac_plane(Q, lambda X: 0.02 * np.maximum(-X[:, 2], 1),  # el error de depth crece con la distancia
                          accept=lambda n, a: abs(n[1]) >= 0.85) if len(Q) >= 100 else None  # casi horizontal (< 32°)
    if plane is None:
        raise RuntimeError("No encontré piso bajo la cámara.")
    n, c = plane
    n = n if n[1] >= 0 else -n
    rz = np.arctan2(n[0], n[1])                  # Rz lleva la normal al plano YZ...
    rx = -np.arctan2(n[2], np.hypot(n[0], n[1]))  # ...y Rx la deja en +Y
    return float(np.degrees(rx)), float(np.degrees(rz)), float(-(n @ c))


# --- cards ------------------------------------------------------------------------------------

def rot_zxy(rx, ry, rz):
    """Matriz de rotación de Nuke con rot_order ZXY (grados): R = Ry · Rx · Rz (medido en Nuke 17.1)."""
    import numpy as np
    a, b, c = np.radians([rx, ry, rz])
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def euler_zxy(R):
    """Inversa de rot_zxy: (rx, ry, rz) en grados."""
    import numpy as np
    rx = np.arcsin(np.clip(-R[1, 2], -1, 1))
    return tuple(float(v) for v in np.degrees([rx, np.arctan2(R[0, 2], R[2, 2]), np.arctan2(R[1, 0], R[1, 1])]))


def card_at_point(P, cam_pos, cam_R, f_px, size, pick, spin=0.0, radius_px=120.0, upright=True):
    """Card pegada a la superficie bajo el píxel pick (Nuke: origen abajo a la izquierda).
    P = posiciones (mundo) de lo que se ve alrededor del punto. Ajusta un plano a P, pone el centro donde
    el rayo del punto corta ese plano y orienta la card con la superficie: en paredes, el borde de abajo
    queda horizontal en el mundo; en pisos y techos, alineado con la cámara. spin gira en el plano (grados).
    Devuelve translate, rotate (ZXY), distancia a la cámara y la fracción de P en el plano."""
    import numpy as np
    if len(P) < 20:
        raise RuntimeError("Hay muy poca superficie bajo el punto.")
    cam_pos, cam_R = np.asarray(cam_pos, float), np.asarray(cam_R, float)
    W, H = size
    d = cam_R @ np.array([(pick[0] - W / 2.0) / f_px, (pick[1] - H / 2.0) / f_px, -1.0])
    dn = d / np.linalg.norm(d)
    # 1) mapa de profundidad de la capa visible: ventanas en grilla dentro del radio; en cada una, el
    #    percentil 25 de la distancia de sus splats. Los splats sueltos forman estelas a lo largo del rayo
    #    (ruido de SHARP ~2 %) y con ellos los planos de canto ganaban; la capa visible no tiene ese problema.
    V = P - cam_pos
    rng_ = np.linalg.norm(V, axis=1)
    loc = V @ cam_R  # coordenadas de cámara
    u = W / 2.0 + f_px * loc[:, 0] / -loc[:, 2]
    v = H / 2.0 + f_px * loc[:, 1] / -loc[:, 2]
    step = radius_px / 4.0
    pts, wts, px_d = [], [], []
    for gy in np.arange(-4, 5):
        for gx in np.arange(-4, 5):
            cx, cy = pick[0] + gx * step, pick[1] + gy * step
            dd = np.hypot(cx - pick[0], cy - pick[1])
            if dd > radius_px:
                continue
            m = (np.abs(u - cx) < 0.6 * step) & (np.abs(v - cy) < 0.6 * step)
            if m.sum() < 5:
                continue
            idx = np.flatnonzero(m)
            pts.append(P[idx[np.argsort(rng_[idx])[(len(idx) - 1) // 4]]])  # el splat real del percentil 25
            px_d.append(dd)
    if len(pts) < 6:
        raise RuntimeError("Hay muy poca superficie bajo el punto.")
    pts, px_d = np.array(pts), np.array(px_d)
    Vp = pts - cam_pos
    tp = np.linalg.norm(Vp, axis=1)
    rays = Vp / tp[:, None]
    wts = np.exp(-0.5 * (px_d / (0.5 * radius_px)) ** 2)  # más peso cerca del punto
    front = pts[np.argmin(px_d)]
    front_t = np.linalg.norm(front - cam_pos)
    # 2) plano: error medido a lo largo del rayo (ahí está el ruido); pasa por la superficie bajo el punto
    #    y no se ve de canto (> ~3,5° respecto del rayo). RANSAC chico + ajuste en profundidad inversa.
    k = 0.01  # ruido de la capa visible; con 2-3 % el letrero volvía a quedar oblicuo (medido)

    def ray_err(n, a, X=pts, R_=rays):
        return np.abs((X - a) @ n) / np.maximum(np.abs(R_ @ n), 1e-3)

    ok = lambda n, a: ray_err(n, a, front[None], dn[None])[0] < 2 * k * front_t and abs(n @ dn) > 0.06
    rng = np.random.default_rng(0)
    best, plane = 0.0, None
    for _ in range(300):
        p0, p1, p2 = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(p1 - p0, p2 - p0)
        if np.linalg.norm(n) < 1e-9:
            continue
        n = n / np.linalg.norm(n)
        if not ok(n, p0):
            continue
        score = float(wts[ray_err(n, p0) < k * tp].sum())
        if score > best:
            best, plane = score, (n, p0)
    if plane is None:
        raise RuntimeError("No hay una superficie clara bajo el punto: muévelo o cambia el radio.")
    inl = ray_err(*plane) < k * tp
    if inl.sum() >= 3:
        # para un plano n·(p - cam) = d0: 1/t = (n/d0)·r̂, lineal en n/d0
        sw = np.sqrt(wts[inl])
        av = np.linalg.lstsq(rays[inl] * sw[:, None], sw / tp[inl], rcond=None)[0]
        n, c = av / np.linalg.norm(av), cam_pos + av / np.dot(av, av)
        if abs(n @ dn) <= 0.06 or not ok(n, c):
            n, c = plane  # el ajuste fino se fue de canto o se alejó del punto: queda el de RANSAC
    else:
        n, c = plane
    if upright:  # en el mundo nivelado: casi horizontal -> horizontal; si no, vertical (quita el cabeceo de ruido)
        up = np.array([0.0, 1.0, 0.0])
        n = up * np.sign(n @ up) if abs(n @ up) > 0.7 else (n - (n @ up) * up) / np.linalg.norm(n - (n @ up) * up)
        c = front
    n = n if n @ (cam_pos - c) > 0 else -n  # la cara mira a la cámara
    t = ((c - cam_pos) @ n) / (d @ n)
    if t <= 0:
        raise RuntimeError("El punto no apunta a la superficie.")
    up = np.array([0.0, 1.0, 0.0])
    x = np.cross(up, n) if abs(n @ up) < 0.95 else cam_R[:, 0] - (cam_R[:, 0] @ n) * n
    x /= np.linalg.norm(x)
    y = np.cross(n, x)
    a = np.radians(spin)
    x, y = np.cos(a) * x + np.sin(a) * y, -np.sin(a) * x + np.cos(a) * y
    fit = float(np.sum(wts * (ray_err(n, c) < k * tp)) / wts.sum())  # cerca del punto pesa más
    return dict(translate=(cam_pos + t * d).tolist(), rotate=euler_zxy(np.c_[x, y, n]),
                distance=float(t * np.linalg.norm(d)), fit=fit)
