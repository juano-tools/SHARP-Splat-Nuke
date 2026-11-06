"""Pruebas del nucleo, sin Nuke: python tests/test_core.py (necesita numpy)."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "nuke"))
from sharp_splat import core  # noqa: E402


def test_floor_orient():
    """Piso sintetico inclinado + ruido + una pared: tiene que devolver los angulos y la altura."""
    rng = np.random.default_rng(1)
    rx, rz, h = 13.0, -3.0, 1.6
    a, g = np.radians(rx), np.radians(rz)
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Rz = np.array([[np.cos(g), -np.sin(g), 0], [np.sin(g), np.cos(g), 0], [0, 0, 1]])
    M = Rx @ Rz  # cámara -> mundo
    floor = np.c_[rng.uniform(-5, 5, 20000), np.full(20000, -h), rng.uniform(-30, -2, 20000)]
    wall = np.c_[np.full(8000, 3.0), rng.uniform(-h, 4, 8000), rng.uniform(-30, -2, 8000)]
    W = np.r_[floor, wall] + rng.normal(0, 0.01, (28000, 3))
    got = core.floor_orient(W @ M, np.ones(len(W)))  # W @ M = mundo -> cámara (M ortogonal)
    assert np.allclose(got, (rx, rz, h), atol=0.2), got  # grados y metros, con ruido de 1 cm


def test_floor_missing():
    P = np.c_[np.zeros(500), np.full(500, 2.0), np.full(500, -5.0)]  # todo sobre la cámara
    try:
        core.floor_orient(P, np.ones(500))
    except RuntimeError:
        return
    raise AssertionError("tenía que fallar sin piso")


def test_lens_from_metadata():
    # metadata real de un Venice 2: sensor en micras, lente sin datos
    sony = {"exr/sony/camera/ImageSensorEffectiveWidth": "22589", "exr/sony/camera/ImageSensorEffectiveHeight": "12713",
            "exr/sony/lens/LensAttributes": "Unknown", "exr/sony/camera/ShutterSpeedTime": "1 / 50"}
    f, fb, note = core.lens_from_metadata(sony, 3840, 2160)
    assert f is None and abs(fb - 22.589) < 1e-6 and "OJO" not in note, (f, fb, note)
    f, fb, note = core.lens_from_metadata(dict(sony, **{"exr/lens/FocalLength": "35mm",
                                                        "exr/lens/FocalLength35mmEquiv": "50"}), 3840, 1600)
    assert f == 35 and "OJO" in note, (f, fb, note)  # ignora el equivalente y avisa del recorte
    assert core.lens_from_metadata({}, 1920, 1080) == (None, None, "sin datos de lente ni sensor")


def test_euler_roundtrip():
    for ang in [(10, 20, 30), (-80, 170, -5), (0, 0, 0), (45, -90 + 1e-3, 12)]:
        R = core.rot_zxy(*ang)
        assert np.allclose(core.rot_zxy(*core.euler_zxy(R)), R, atol=1e-9), ang
    # medido en Nuke 17.1: Axis ZXY (30, 40, 50) -> primera columna de la world_matrix
    assert np.allclose(core.rot_zxy(30, 40, 50)[:, 0], [0.7386, 0.6634, -0.1198], atol=1e-4)


def test_card_at_point():
    """Pared girada y un piso, vistos por una cámara girada: centro en la superficie, normal correcta,
    borde de abajo horizontal en la pared, y spin gira en el plano."""
    rng = np.random.default_rng(3)
    W, H, f = 3840, 2160, 3000.0
    cam_R, cam_pos = core.rot_zxy(5, 20, -2), np.array([1.0, 1.6, 4.0])

    def surface(n_true, p0, pick, r=150):
        def hit(u, v):
            d = cam_R @ np.array([(u - W / 2) / f, (v - H / 2) / f, -1])
            return cam_pos + ((p0 - cam_pos) @ n_true) / (d @ n_true) * d
        ang = rng.uniform(0, 2 * np.pi, 2000)
        rad = r * np.sqrt(rng.uniform(0, 1, 2000))
        P = np.array([hit(pick[0] + a * np.cos(b), pick[1] + a * np.sin(b)) for a, b in zip(rad, ang)])
        P += rng.normal(0, 0.005, P.shape)
        P[:30] += cam_R @ np.array([0, 0, -3.0])  # algo de fondo detrás
        return P, hit(*pick)

    n_wall = core.rot_zxy(0, 35, 0) @ np.array([0, 0, 1.0])
    P, center = surface(n_wall, cam_pos + cam_R @ np.array([0, 0, -6.0]), (2000, 1100))
    card = core.card_at_point(P, cam_pos, cam_R, f, (W, H), (2000, 1100))
    R = core.rot_zxy(*card["rotate"])
    assert np.allclose(card["translate"], center, atol=0.02), (card["translate"], center)
    assert R[:, 2] @ n_wall > 0.999 and abs(R[1, 0]) < 1e-6 and card["fit"] > 0.9, (R, card)  # borde horizontal
    spun = core.rot_zxy(*core.card_at_point(P, cam_pos, cam_R, f, (W, H), (2000, 1100), spin=30)["rotate"])
    assert abs(np.degrees(np.arccos(np.clip(spun[:, 0] @ R[:, 0], -1, 1))) - 30) < 1e-6

    # punto en el borde de una pared chica delante de otra grande: gana la de adelante, no la dominante
    P_front, center = surface(n_wall, cam_pos + cam_R @ np.array([0, 0, -6.0]), (2000, 1100), r=40)
    P_back, _ = surface(np.array([0, 0, 1.0]), cam_pos + cam_R @ np.array([0, 0, -15.0]), (2000, 1100), r=150)
    card = core.card_at_point(np.r_[P_front, P_back], cam_pos, cam_R, f, (W, H), (2000, 1100), radius_px=150)
    assert np.allclose(card["translate"], center, atol=0.05) and core.rot_zxy(*card["rotate"])[:, 2] @ n_wall > 0.99, card
    # letrero chico de frente delante de una pared oblicua que llena la región: gana el letrero
    n_sign = cam_R @ np.array([0, 0, 1.0])
    P_sign, center = surface(n_sign, cam_pos + cam_R @ np.array([0, 0, -20.0]), (2000, 1100), r=35)
    n_obl = cam_R @ core.rot_zxy(0, 80, 0) @ np.array([0, 0, 1.0])  # pared casi paralela al rayo
    P_wall, _ = surface(n_obl, cam_pos + cam_R @ np.array([0, 0, -21.0]), (2000, 1100), r=150)
    card = core.card_at_point(np.r_[P_sign, P_wall], cam_pos, cam_R, f, (W, H), (2000, 1100), radius_px=50)  # objeto chico: radio chico
    assert np.allclose(card["translate"], center, atol=0.1) and core.rot_zxy(*card["rotate"])[:, 2] @ n_sign > 0.98, card
    # un plano visto de canto (techo de auto a la altura de la cámara) no sirve de card
    fwd = cam_R @ np.array([0, 0, -1.0])
    fwd = np.array([fwd[0], 0, fwd[2]]) / np.hypot(fwd[0], fwd[2])
    roof = cam_pos + 20 * fwd  # a la altura de la cámara: se ve de canto
    edge = np.c_[rng.uniform(-1, 1, 800), np.zeros(800), rng.uniform(-1, 1, 800)] + roof
    d = cam_R.T @ (roof - cam_pos)
    pick = (W / 2 + f * d[0] / -d[2], H / 2 + f * d[1] / -d[2])
    try:
        core.card_at_point(edge, cam_pos, cam_R, f, (W, H), pick)
        raise AssertionError("tenía que rechazar el plano de canto")
    except RuntimeError:
        pass

    P, center = surface(np.array([0, 1.0, 0]), np.array([0, 0, 0.0]), (1900, 300))  # piso en Y=0
    card = core.card_at_point(P, cam_pos, cam_R, f, (W, H), (1900, 300))
    assert abs(card["translate"][1]) < 0.02 and core.rot_zxy(*card["rotate"])[1, 2] > 0.999, card


def test_preview_ply(tmp):
    """Gris medio ACEScg 0.18 -> Rec.709 de pantalla ~0.49; un rojo HDR se recorta a 1; el resto no cambia."""
    path = os.path.join(tmp, "c.ply")
    C0 = core.SH_C0
    dc = lambda rgb: [(c - 0.5) / C0 for c in rgb]
    pts = np.array([(0, 0, -1, *dc((0.18, 0.18, 0.18)), 1.0), (0, 0, -2, *dc((8.0, 0.0, 0.0)), 1.0)],
                   dtype=[(n, "<f4") for n in ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity")])
    with open(path, "wb") as f:
        f.write(b"ply\nformat binary_little_endian 1.0\nelement vertex 2\n" +
                b"".join(b"property float %s\n" % n.encode() for n in pts.dtype.names) + b"end_header\n")
        pts.tofile(f)
    with open(core.preview_ply(path), "rb") as f:
        b = np.frombuffer(f.read().split(b"end_header\n", 1)[1], dtype=pts.dtype)
    col = 0.5 + C0 * np.stack([b["f_dc_%d" % i] for i in range(3)], 1)
    assert np.allclose(col[0], 0.18 ** (1 / 2.4), atol=0.01) and abs(col[1, 0] - 1) < 1e-4, col
    assert b["z"].tolist() == [-1, -2] and b["opacity"].tolist() == [1, 1]


def test_equiv_focal():
    # 18 mm sobre 22,59 mm de ancho en UHD = el mismo FOV que pide SHARP en equivalente diagonal
    f = core.equiv_focal(18, 22.589, 3840, 2160)
    assert abs(f - 18 / 22.589 * 3840 * 43.2666 / np.hypot(3840, 2160)) < 1e-9


def test_read_ply(tmp):
    path = os.path.join(tmp, "t.ply")
    pts = np.array([(1, 2, -3, 0.5), (4, 5, -6, -1.0)], dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("opacity", "<f4")])
    with open(path, "wb") as f:
        f.write(b"ply\nformat binary_little_endian 1.0\nelement vertex 2\nproperty float x\nproperty float y\n"
                b"property float z\nproperty float opacity\nend_header\n")
        pts.tofile(f)
    P, op = core.read_ply(path)
    assert P.tolist() == [[1, 2, -3], [4, 5, -6]] and op.tolist() == [0.5, -1.0]


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_"):
                fn(tmp) if fn.__code__.co_argcount else fn()
                print("ok", name)
