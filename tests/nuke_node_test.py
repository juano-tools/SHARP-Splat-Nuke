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
gf = os.path.expanduser("~/.nuke/plugins/GenFill/nuke/python")
if os.path.isdir(gf):
    sys.path.insert(0, gf)
from sharp_splat import core, node  # noqa: E402

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

made = node.export(g, node.EXPORTS[-1])  # escena completa afuera: su SplatRender tiene que dar lo mismo
sr_out = next(n for n in made if n.Class() == "SplatRender")
diff = max(abs(a - b) for a, b in zip(px(sr_out), ref))
print("RESULT escena afuera:", [n.Class() for n in made], "dif max", diff)
assert diff < 1e-3 and any(n.Class() == "ReadGeo2" for n in made), "la escena sacada tiene que dar el mismo render"
for n in made:
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
