"""Mesh-Block: ab BLOCK_MIN importierten Meshes zeichnet der Renderer sie in einem Durchgang (Lage eingerechnet, je
Punkt die Nummer seines Teils). Das Bild, die Hervorhebung, Ausblenden, Verschieben und Picking müssen genau wie je
Mesh bleiben – Notizen und Malerei hängen weiter am einzelnen Teil."""
import numpy as np

from tests.harness import H
from sketch_machine import renderer as rmod
from sketch_machine.geometry import Geometry
from sketch_machine.scene import MeshObject


def _box(size=0.4):
    s = size / 2
    v = np.array([[x, y, z] for x in (-s, s) for y in (0, 2 * s) for z in (-s, s)], float)
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return Geometry(v, f)


def _grid_scene(h: H, n=10):
    """n×n Kisten auf dem Boden (mehr als BLOCK_MIN), jede ein eigenes Mesh mit eigener Lage."""
    h.new_scene()
    geo = _box()
    for i in range(n):
        for j in range(n):
            xf = np.eye(4)
            xf[:3, 3] = [i - n / 2, 0.0, j - n / 2]
            h.sc.meshes.append(MeshObject(f"Kiste {i}-{j}", "", geo, xform=xf))
    h.v._changed()
    h.camera([0.0, 0.0, 0.0], 14, [0.3, 0.7, 0.6])
    return h.sc.meshes


def _arr(img):
    img = img.convertToFormat(img.Format.Format_RGB32)
    raw = np.frombuffer(bytes(img.constBits()), np.uint8)
    return raw.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4].astype(int)


def _both(h: H):
    """(Bild mit Block, Bild je Mesh)."""
    with_block = _arr(h.grab())
    assert h.v.renderer._block is not None, "ab BLOCK_MIN Meshes gibt es einen Block"
    old = rmod.BLOCK_MIN
    rmod.BLOCK_MIN = 10 ** 9
    try:
        h.v.renderer._block_memo = None
        per_mesh = _arr(h.grab())
        assert h.v.renderer._block is None
    finally:
        rmod.BLOCK_MIN = old
        h.v.renderer._block_memo = None
    return with_block, per_mesh


def _same(a, b, label):
    d = np.abs(a - b).reshape(a.shape[0], -1, 4)[..., :3].max(axis=2)
    n = int((d > 2).sum())  # einzelne Kantenpixel dürfen abweichen (Lage im Block schon in Weltkoordinaten gerundet)
    assert n <= d.size * 2e-4, f"{label}: Block weicht vom Zeichnen je Mesh ab ({n} Pixel)"


def test_block_bild_wie_je_mesh_auch_ausgeblendet_verschoben_gewaehlt(h: H):
    meshes = _grid_scene(h)
    _same(*_both(h), "Grundbild")
    meshes[3].hidden = True  # ausgeblendet: nur die Tabelle, kein Neubau
    h.v._changed()
    _same(*_both(h), "ausgeblendet")
    h.grab()
    block = h.v.renderer._block
    xf = meshes[17].xform.copy()
    xf[:3, 3] += [0.0, 0.8, 0.0]
    meshes[17].xform = xf  # verschoben: dieses Teil einzeln, bis sich ein Neubau lohnt
    h.v._changed()
    with_block = _arr(h.grab())
    assert h.v.renderer._block is block, "ein verschobenes Teil baut den Block nicht neu"
    assert block.current(meshes[17]) is None
    h.v.selection = [meshes[40].id]  # gewählt: andere Tönung aus der Tabelle
    h.v.ws.select_mode = True
    h.v._changed()
    _same(*_both(h), "verschoben und gewählt")
    assert not np.array_equal(with_block, _arr(h.grab())), "Auswahl ist zu sehen"


def test_block_picking_trifft_das_einzelne_teil(h: H):
    meshes = _grid_scene(h)
    h.grab()
    assert h.v.renderer._block is not None
    for m in (meshes[0], meshes[55], meshes[99]):
        top = m.xform[:3, 3] + [0.0, 0.4, 0.0]  # Mitte des Deckels
        hit, point, _ = h.v._mesh_under(h.scrf(top))
        assert hit is m, (m.name, getattr(hit, "name", None))
        assert np.allclose(point, top, atol=0.03), point


def test_block_mit_licht_und_color_id(h: H):
    """Licht-Modus (Schattenkarte aus dem Block) wie je Mesh; die Color-ID des Briefs nennt je Pixel das einzelne
    Mesh, auch wenn es im Block gezeichnet wird."""
    meshes = _grid_scene(h)
    h.v.ws.light_on = True
    try:
        h.v._changed()
        _same(*_both(h), "Licht")
    finally:
        h.v.ws.light_on = False
    h.grab()
    assert h.v.renderer._block is not None
    img, ids = h.v.clean_image(ids=True)
    m = meshes[55]
    top = h.scrf(m.xform[:3, 3] + [0.0, 0.4, 0.0])
    hh, ww = ids.shape
    x, y = int(top.x() * ww / h.v.width()), int(top.y() * hh / h.v.height())  # Zeile 0 oben
    assert int(round(float(ids[y, x]))) == m.id, (ids[y, x], m.id)
