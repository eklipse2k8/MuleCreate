"""Image on a helper plane or helper surface: projected from exactly one direction (no triplanar projection), for
tracing contours and as a reference in the 3D view.

obj.picture: {"asset": file name in scene.assets, "image_aspect": width/height, "matrix": world -> image space (-1..1),
"aspect": width/height of this space, "frame": pose of the object at projection time, "on": visible, "locked": Project locked}.
The image is fitted without distortion and moves with the object (frame).
"""
import numpy as np

from .scene import Plane

FILE_FILTER = "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"
MAX_TEXTURE = 4096  # the longer image edge is scaled down for display (the file stays as it is)


def supports(obj):
    return isinstance(obj, Plane) or bool(getattr(obj, "aid", False) and getattr(obj, "frozen", None))


def _mesh(obj):
    """(triangle corner points Nx3) of the object."""
    if isinstance(obj, Plane):
        c = obj.corners()
        return c[[0, 1, 2, 0, 2, 3]]
    verts, tris = obj.frozen[0][0], obj.frozen[0][1]
    return np.asarray(verts, float)[np.asarray(tris, int).ravel()]


def _frame(obj):
    """4x4: pose of the object (follows move and rotate)."""
    if isinstance(obj, Plane):
        u, v, n, o = obj.axis_u, obj.axis_v, obj.normal, obj.origin
    else:
        p = np.asarray(obj.frozen[0][0], float)
        o = p[0]
        far = p[np.argmax(np.linalg.norm(p - o, axis=1))]
        u = far - o
        u = u / max(np.linalg.norm(u), 1e-9)
        side = np.linalg.norm(np.cross(p - o, u), axis=1)
        w = p[np.argmax(side)] - o
        n = np.cross(u, w)
        n = n / max(np.linalg.norm(n), 1e-9)
        v = np.cross(n, u)
    frame = np.eye(4)
    frame[:3, 0], frame[:3, 1], frame[:3, 2], frame[:3, 3] = u, v, n, o
    return frame


def _along_normal(obj):
    """(matrix, aspect ratio): default - from the surface direction; for curved surfaces from the mean normal."""
    if isinstance(obj, Plane):
        u, v, n = obj.axis_u, obj.axis_v, obj.normal
        u, v = u / np.linalg.norm(u), v / np.linalg.norm(v)
    else:
        tri = _mesh(obj).reshape(-1, 3, 3)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).sum(axis=0)  # weighted by area
        n = n / max(np.linalg.norm(n), 1e-9)
        up = np.array([0.0, 1.0, 0.0]) if abs(n[1]) < 0.9 else np.array([0.0, 0.0, -1.0])
        u = np.cross(up, n)
        u = u / np.linalg.norm(u)
        v = np.cross(n, u)
    p = _mesh(obj)
    a, b = p @ u, p @ v
    half_u, half_v = max(np.ptp(a) / 2, 1e-6), max(np.ptp(b) / 2, 1e-6)
    m = np.eye(4)
    m[0, :3], m[0, 3] = u / half_u, -(a.min() + half_u) / half_u
    m[1, :3], m[1, 3] = v / half_v, -(b.min() + half_v) / half_v
    m[2] = (0.0, 0.0, 0.0, 0.0)
    return m, float(half_u / half_v)


def from_camera(cam, proj, aspect):
    """(matrix, aspect ratio): from the current camera."""
    view = np.eye(4)
    view[:3, :3] = cam.rot.T
    view[:3, 3] = -cam.rot.T @ cam.eye
    return np.asarray(proj, float) @ view, float(aspect)


def create(obj, asset, image_aspect):
    """New image on the object: projected from the surface direction."""
    obj.picture = {"asset": asset, "image_aspect": float(image_aspect), "on": True, "locked": False}
    set_projection(obj, *_along_normal(obj))


def set_projection(obj, matrix, aspect):
    pic = obj.picture
    pic["matrix"], pic["aspect"] = np.asarray(matrix, float).tolist(), float(aspect)
    pic["frame"] = _frame(obj).tolist()
    if isinstance(obj, Plane):
        pic["size"] = [float(obj.size_u), float(obj.size_v)]  # size at projection time: the image scales with the plane


def _size_scale(obj, pic):
    """Plane scaled since projection: back to the size at that time in plane coordinates (4x4). Older images without
    a stored size: the current one counts as the starting point (they stay as they are and scale along from now on)."""
    d = np.eye(4)
    if not isinstance(obj, Plane):
        return d
    if "size" not in pic:
        pic["size"] = [float(obj.size_u), float(obj.size_v)]
    su, sv = pic["size"]
    d[0, 0] = su / max(float(obj.size_u), 1e-9)
    d[1, 1] = sv / max(float(obj.size_v), 1e-9)
    return d


def draw_matrix(obj):
    """World -> image space (-1..1) in the current pose of the object, with the aspect ratio fitted."""
    pic = obj.picture
    fit = np.eye(4)
    if pic["image_aspect"] > pic["aspect"]:
        fit[1, 1] = pic["image_aspect"] / pic["aspect"]
    else:
        fit[0, 0] = pic["aspect"] / pic["image_aspect"]
    return fit @ np.array(pic["matrix"]) @ np.array(pic["frame"]) @ _size_scale(obj, pic) @ np.linalg.inv(_frame(obj))


def draw_list(scene, planes_visible):
    """For the renderer: [(asset, bytes, matrix, corner points, object id)]."""
    if not planes_visible:
        return []
    out = []
    for obj in list(scene.planes) + [s for s in scene.surfaces if s.aid and s.frozen]:
        pic = obj.picture
        if pic and pic.get("on") and not scene.is_hidden(obj):
            data = scene.asset_bytes(pic["asset"])
            if data is not None:
                out.append((pic["asset"], data, draw_matrix(obj), _mesh(obj), obj.id))
    return out
