"""Flujo completo del nodo en Nuke 17 sin ventana (usa ComfyUI y la GPU):

    Nuke17.1.exe -i -t --nukex tests/nuke_node_test.py <plate.####.exr> <primer cuadro> <focal> <carpeta temporal>

Hace a mano lo que hace el botón Generar (sin hilos: en -t no hay bucle de eventos).
"""

import os
import sys
import time

import nuke

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nuke"))
from sharp_splat import core, node  # noqa: E402
assert set(node.PARAMS) == {n for n, _ in core.SETTINGS}, "cada ajuste de SHARP necesita nombre y descripción"

plate, first, focal, tmp = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
nuke.root()["colorManagement"].setValue("OCIO")
read = nuke.nodes.Read(file=plate, first=first, last=first)
nuke.root()["first_frame"].setValue(first)
nuke.root()["last_frame"].setValue(first)
nuke.frame(first)
nuke.scriptSaveAs(os.path.join(tmp, "sharp_test.nk").replace("\\", "/"), overwrite=1)  # el EXR va junto al script

read.setSelected(True)
g = node.create()
assert g.input(0) is read and g.inputs() >= 1, "plate tiene que ser la entrada 0"
print("RESULT meta:", g["sharp_meta"].value(), "| focal", g["sharp_focal"].value(), "filmback", g["sharp_filmback"].value())
if not g["sharp_focal"].value():
    g["sharp_focal"].setValue(focal)

# lo mismo que generate(), sin hilo
fb = g["sharp_filmback"].value()
opts = {n: (bool if isinstance(d, bool) else type(d))(g["sharp_" + n].value()) for n, d in core.SETTINGS}
t0 = time.time()
exr = node._export_frame(read, first, node._job_dir(g, first))
paths = core.generate(exr, False, core.equiv_focal(focal, fb, read.width(), read.height()), fb,
                      "sharp_%s_f%04d_v001" % (g.name(), first), nuke.root()["workingSpaceLUT"].value(), opts)
print("RESULT SHARP %.1f s" % (time.time() - t0))
node._build(g, paths["nk"], dict(version=1, frame=first, exr=exr, ply=paths["ply"], status="v001"))
print("RESULT status:", g["sharp_status"].value())
assert "cámara a" in g["sharp_status"].value(), "tenía que nivelar el piso"

pts = [(1920, 1080), (600, 700), (3000, 400), (1000, 1800)]
px = lambda n: [round(n.sample("rgba.red", x, y), 5) for x, y in pts]
ref = px(g)
print("RESULT formato", g.width(), g.height(), "render", ref, "plate", px(read))
assert (g.width(), g.height()) == (read.width(), read.height())

with g:  # valores pasados como argumento al crear nodos: Nuke ignora algunos en silencio
    kw = {"bg": nuke.allNodes("Multiply")[0]["value"].value(), "mix": nuke.toNode("SHARP_grilla_over")["mix"].value(),
          "grid": nuke.allNodes("Grid")[0]["color"].value(), "hold": nuke.allNodes("FrameHold")[0]["first_frame"].value()}
print("RESULT knobs al crear:", kw)
assert kw["bg"] in (0, [0, 0, 0, 0]) and abs(kw["mix"] - 0.8) < 1e-6 and kw["grid"][3] == 1 and kw["hold"] == first

# el render calza con el plate (sin corrimiento): todo lo de las cards depende de esto
import random  # noqa: E402
random.seed(1)
probe = [(random.uniform(200, 3640), random.uniform(1000, 1160)) for _ in range(150)]
err = {dy: sum(abs(g.sample("rgba.green", x, y) - read.sample("rgba.green", x, y + dy)) for x, y in probe)
       for dy in list(range(-96, 97, 8)) + [-840, 840]}
best = min(err, key=err.get)
print("RESULT corrimiento render/plate:", best, "px (error %.3f vs %.3f a +-840)" % (err[best], min(err[840], err[-840])))
assert best == 0, "el render tiene que calzar con el plate"

g["sharp_cam_height"].setValue(1.7)
node.orient(g)
assert px(g) == ref, ("la escala cambio el render", px(g), ref)
print("RESULT altura 1.7:", g["sharp_status"].value())

g["sharp_adj_rot"].setValue([0.5, 10, -0.3])  # ajuste manual: gira todo el mundo, cámara incluida
g["sharp_adj_pos"].setValue([1, 0.2, -2])
node.apply_orient(g)
with g:
    rot = nuke.toNode("SHARP_mundo")["rotate"].value()
assert abs(rot[1] - 10) < 1e-9 and max(abs(a - b) for a, b in zip(px(g), ref)) < 1e-3, ("el ajuste cambió el render", px(g), ref)
print("RESULT ajuste manual OK:", [round(v, 2) for v in rot])

import numpy as np  # noqa: E402

# card en la pared de ladrillo de la izquierda: vertical, con el borde de abajo horizontal
g["sharp_pick"].setValue([450, 1150])
card = node.create_card(g)
R = core.rot_zxy(*card["rotate"].value())
print("RESULT card pared:", card["label"].value(), "normal", R[:, 2].round(3), "eje x", R[:, 0].round(3))
assert abs(R[1, 2]) < 0.2 and abs(R[1, 0]) < 1e-6, "pared vertical y card nivelada"
before = card["translate"].value()
g["sharp_pick"].setValue([600, 1100])  # arrastrar el punto: la card viva lo sigue
t0 = time.time()
node.update_card(g)
print("RESULT reajuste en %.3f s" % (time.time() - t0))
assert card["translate"].value() != before
g["sharp_card_spin"].setValue(30)
node.update_card(g)
assert abs(core.rot_zxy(*card["rotate"].value())[1, 0]) > 0.3, "spin gira en el plano"
g["sharp_card_spin"].setValue(0)
node.update_card(g)

# el GeoCard real (puntos del USD) visto por la cámara de SHARP: centro en el punto, esquinas = la grilla
from pxr import Usd, UsdGeom  # noqa: E402
with g:
    grid, ax = nuke.toNode("SHARP_card_grilla"), nuke.toNode("SHARP_mundo")
    scam = nuke.toNode(node._job(g)["cam"])
    assert not grid["disable"].value() and not nuke.toNode("SHARP_grilla_over")["disable"].value()
Rw, Tw = core.rot_zxy(*ax["rotate"].value()), np.array(ax["translate"].value())
W, H = g.width(), g.height()
f_px = scam["focal"].value() / scam["haperture"].value() * W


def proj(p):
    d = Rw.T @ (np.asarray(p)[:3] - Tw)
    return np.array([W / 2 + f_px * d[0] / -d[2], H / 2 + f_px * d[1] / -d[2]])


prim = next(p for p in card.getStage().Traverse() if p.IsA(UsdGeom.Mesh))
lp = np.array(UsdGeom.Mesh(prim).GetPointsAttr().Get())
wp = np.c_[lp, np.ones(len(lp))] @ np.array(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
usd = [proj(wp[np.argmin(lp[:, 0] * sx + lp[:, 1] * sy)]) for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
pin = [np.array(grid["to%d" % i].value()) for i in range(1, 5)]
center = proj(wp[:, :3].mean(0))
print("RESULT GeoCard visto: centro", center.round(1), "punto", g["sharp_pick"].value(),
      "esquinas USD vs grilla", max(np.linalg.norm(a - b) for a, b in zip(usd, pin)).round(3))
assert np.linalg.norm(center - g["sharp_pick"].value()) < 1, "el centro de la card tiene que caer en el punto"
assert max(np.linalg.norm(a - b) for a, b in zip(usd, pin)) < 0.5, "la grilla tiene que calzar con la card"
# lo que dibuja la grilla cae dentro de las esquinas
xs, ys = [p[0] for p in pin], [p[1] for p in pin]
hits = [(x, y) for x in np.arange(min(xs) - 40, max(xs) + 40, 6) for y in np.arange(min(ys) - 40, max(ys) + 40, 6)
        if grid.sample("rgba.alpha", x, y) > 0.3]
hx, hy = zip(*hits)
print("RESULT grilla dibujada: bbox", (min(hx), min(hy), max(hx), max(hy)), "esquinas", (min(xs), min(ys), max(xs), max(ys)))
assert min(hx) > min(xs) - 10 and max(hx) < max(xs) + 10 and min(hy) > min(ys) - 10 and max(hy) < max(ys) + 10
assert max(hx) - min(hx) > 0.8 * (max(xs) - min(xs)), "la grilla tiene que cubrir la card"
fixed = card
card2 = node.create_card(g)  # la nueva pasa a ser la viva; la anterior queda fija
g["sharp_pick"].setValue([450, 1150])
node.update_card(g)
assert fixed["translate"].value() != card2["translate"].value()

# card en el piso de la calle: horizontal y a la altura del suelo (0.2 por el "mover escena")
g["sharp_pick"].setValue([1700, 170])
node.update_card(g)
n = core.rot_zxy(*card2["rotate"].value())[:, 2]
print("RESULT card piso:", card2["label"].value(), "normal", n.round(3), "y", round(card2["translate"].value(1), 3))
assert n[1] > 0.98 and abs(card2["translate"].value(1) - 0.2) < 0.15, "el piso tendría que quedar horizontal en Y≈0.2"
g["sharp_card_grid"].setValue(False)
for c in (fixed, card2):
    nuke.delete(c)

made = node.export(g, node.EXPORTS[-1])  # escena completa afuera: su SplatRender tiene que dar lo mismo
sr_out = next(n for n in made if n.Class() == "SplatRender")
diff = max(abs(a - b) for a, b in zip(px(sr_out), ref))
print("RESULT escena afuera:", [n.Class() for n in made], "dif max", diff)
assert diff < 1e-3 and any(n.Class() == "ReadGeo2" for n in made), "la escena sacada tiene que dar el mismo render"
for n in made:
    nuke.delete(n)
g["sharp_export_rec709"].setValue(True)
prev = node.export(g, node.EXPORTS[1])
gr = next(n for n in prev if n.Class() == "GeoReference")
P, _ = core.read_ply(gr["file_path"].value())
print("RESULT previs Rec.709:", os.path.basename(gr["file_path"].value()), len(P), "splats")
assert gr["file_path"].value().endswith("_rec709.ply") and len(P) > 1000
for n in prev:
    nuke.delete(n)
cam = node.export(g, node.EXPORTS[0])[0]  # solo la cámara
g.setInput(1, cam)
node._wire_cam(g)
with g:
    assert nuke.toNode("SplatRender").input(1).name() == "cam"
diff = max(abs(a - b) for a, b in zip(px(g), ref))
print("RESULT cámara afuera, dif max", diff)
assert diff < 1e-3, "la cámara sacada tiene que dar el mismo render"

cam["translate"].setValue(cam["translate"].value(0) + 0.3, 0)  # vista nueva
print("RESULT cámara movida 0.3 m:", px(g))

name = g.name()
nuke.scriptSaveAs(os.path.join(tmp, "sharp_test.nk").replace("\\", "/"), overwrite=1)  # en -t, scriptSave() no escribe el grafo
nuke.scriptClear()
try:
    nuke.scriptOpen(os.path.join(tmp, "sharp_test.nk").replace("\\", "/"))
except RuntimeError as exc:  # en -t puede quejarse y cargar igual
    print("RESULT scriptOpen dijo:", exc)
g = nuke.toNode(name)
assert node._job(g)["ply"] == paths["ply"] and "sharp_generate" in g.knobs()
print("RESULT reabierto OK:", g["sharp_status"].value())
print("RESULT TODO OK")
