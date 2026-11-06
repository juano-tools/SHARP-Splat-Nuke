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


def test_inside_quad():
    q = [(0, 0), (10, 0), (10, 5), (0, 5)]
    x, y = np.array([5, 11, 5, -1, 9.9]), np.array([2, 2, 6, 1, 4.9])
    assert core.inside_quad(x, y, q).tolist() == [True, False, False, False, True]


def test_card_from_quad():
    """Pared inclinada vista por una cámara girada: la card tiene que caer en la pared, del tamaño de la región."""
    rng = np.random.default_rng(3)
    W, H, f = 3840, 2160, 3000.0
    cam_R, cam_pos = core.rot_zxy(5, 20, -2), np.array([1.0, 1.6, 4.0])
    n_true = core.rot_zxy(0, 35, 0) @ np.array([0, 0, 1.0])  # pared girada 35° en Y
    p0 = cam_pos + cam_R @ np.array([0, 0, -6.0])            # a 6 m delante de la cámara
    quad = [(1500, 800), (2400, 850), (2350, 1500), (1450, 1400)]

    def hit(u, v):
        d = cam_R @ np.array([(u - W / 2) / f, (v - H / 2) / f, -1])
        return cam_pos + ((p0 - cam_pos) @ n_true) / (d @ n_true) * d

    u, v = rng.uniform(1400, 2450, 3000), rng.uniform(750, 1550, 3000)
    m = core.inside_quad(u, v, quad)
    P = np.array([hit(a, b) for a, b in zip(u[m], v[m])]) + rng.normal(0, 0.005, (m.sum(), 3))
    P[:40] += cam_R @ np.array([0, 0, -3.0])  # algo de fondo detrás de la pared
    card = core.card_from_quad(P, cam_pos, cam_R, f, (W, H), quad)
    C = np.array([hit(a, b) for a, b in quad])
    assert np.allclose(card["corners"], C, atol=0.03), (card["corners"], C)
    n = core.rot_zxy(*card["rotate"])[:, 2]
    assert n @ n_true > 0.999 and n @ (cam_pos - p0) > 0, n  # normal de la pared, hacia la cámara
    w = np.linalg.norm((C[1] + C[2]) / 2 - (C[0] + C[3]) / 2)
    assert abs(card["size"][0] - w) < 0.05 and card["fit"] > 0.9, card


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
