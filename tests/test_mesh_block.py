"""Mesh block: from BLOCK_MIN imported meshes on, the renderer draws them in one pass (placement included, per
point the number of its part). The image, highlighting, hiding, moving and picking must stay exactly as per
mesh – notes and paint stay attached to the individual part."""
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
    """n×n crates on the ground (more than BLOCK_MIN), each its own mesh with its own placement."""
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
    """(image with block, image per mesh)."""
    with_block = _arr(h.grab())
    assert h.v.renderer._block is not None, "from BLOCK_MIN meshes on there is a block"
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
    n = int((d > 2).sum())  # single edge pixels may differ (placement in the block already rounded in world coordinates)
    assert n <= d.size * 2e-4, f"{label}: block differs from drawing per mesh ({n} pixels)"


def test_block_image_as_per_mesh_also_hidden_moved_selected(h: H):
    meshes = _grid_scene(h)
    _same(*_both(h), "base image")
    meshes[3].hidden = True  # hidden: only the table, no rebuild
    h.v._changed()
    _same(*_both(h), "hidden")
    h.grab()
    block = h.v.renderer._block
    xf = meshes[17].xform.copy()
    xf[:3, 3] += [0.0, 0.8, 0.0]
    meshes[17].xform = xf  # moved: this part individually until a rebuild pays off
    h.v._changed()
    with_block = _arr(h.grab())
    assert h.v.renderer._block is block, "a moved part does not rebuild the block"
    assert block.current(meshes[17]) is None
    h.v.selection = [meshes[40].id]  # selected: different tint from the table
    h.v.ws.select_mode = True
    h.v._changed()
    _same(*_both(h), "moved and selected")
    assert not np.array_equal(with_block, _arr(h.grab())), "selection is visible"


def test_block_picking_hits_the_individual_part(h: H):
    meshes = _grid_scene(h)
    h.grab()
    assert h.v.renderer._block is not None
    for m in (meshes[0], meshes[55], meshes[99]):
        top = m.xform[:3, 3] + [0.0, 0.4, 0.0]  # middle of the lid
        hit, point, _ = h.v._mesh_under(h.scrf(top))
        assert hit is m, (m.name, getattr(hit, "name", None))
        assert np.allclose(point, top, atol=0.03), point


def test_block_with_light_and_color_id(h: H):
    """Light mode (shadow map from the block) as per mesh; the brief's color ID names the individual mesh per pixel,
    even if it is drawn in the block."""
    meshes = _grid_scene(h)
    h.v.ws.light_on = True
    try:
        h.v._changed()
        _same(*_both(h), "light")
    finally:
        h.v.ws.light_on = False
    h.grab()
    assert h.v.renderer._block is not None
    img, ids = h.v.clean_image(ids=True)
    m = meshes[55]
    top = h.scrf(m.xform[:3, 3] + [0.0, 0.4, 0.0])
    hh, ww = ids.shape
    x, y = int(top.x() * ww / h.v.width()), int(top.y() * hh / h.v.height())  # row 0 on top
    assert int(round(float(ids[y, x]))) == m.id, (ids[y, x], m.id)
