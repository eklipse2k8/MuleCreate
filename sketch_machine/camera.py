"""Orbit camera with free orientation, but world Y up while orbiting (like Houdini).
Perspective or orthographic; orthographic shows exactly as much at the depth of target as
perspective does, so switching does not jump.

The orientation is a 3x3 matrix with the columns right, up, back (back points from
target to the camera). Camera moves interpolate target and distance linearly, the
orientation by quaternion slerp.
"""
import math

import numpy as np

WORLD_UP = np.array([0.0, 1.0, 0.0])
ORBIT_SPEED = 0.008


def rot_axis(axis, angle):
    """Rotation matrix about an axis (Rodrigues)."""
    x, y, z = axis / np.linalg.norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    C = 1 - c
    return np.array([
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ])


def view_for_back(back):
    """Orientation looking along -back, with world Y as far up as possible."""
    back = back / np.linalg.norm(back)
    if abs(back @ WORLD_UP) > 0.999:
        right = np.array([1.0, 0.0, 0.0])  # top view: X to the right
    else:
        right = np.cross(WORLD_UP, back)
        right /= np.linalg.norm(right)
    up = np.cross(back, right)
    return np.column_stack([right, up, back])


def _mat_to_quat(m):
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def _quat_to_mat(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _slerp(q0, q1, t):
    d = q0 @ q1
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + t * (q1 - q0)
        return q / np.linalg.norm(q)
    theta = math.acos(d)
    return (math.sin((1 - t) * theta) * q0 + math.sin(t * theta) * q1) / math.sin(theta)


class Camera:
    HOME_YAW = math.radians(35)
    HOME_PITCH = math.radians(28)
    HOME_DIST = 12.0

    def __init__(self):
        self.target = np.zeros(3)
        self.dist = self.HOME_DIST
        self.rot = self.home_rot()
        self.ortho = False  # orthographic (axis views); image height is then 2 * dist * tan(fov/2)

    @classmethod
    def home_rot(cls):
        cp = math.cos(cls.HOME_PITCH)
        back = np.array([cp * math.sin(cls.HOME_YAW), math.sin(cls.HOME_PITCH), cp * math.cos(cls.HOME_YAW)])
        return view_for_back(back)

    # --- Basis ---
    @property
    def right(self):
        return self.rot[:, 0]

    @property
    def up(self):
        return self.rot[:, 1]

    @property
    def back(self):
        return self.rot[:, 2]

    @property
    def eye(self):
        return self.target + self.dist * self.back

    # --- Navigation ---
    def orbit(self, dx, dy, pivot=None):
        """Rotate about target, or about an arbitrary point (pivot) without an image jump."""
        old_rot, old_eye = self.rot, self.eye
        self._orbit_rot(dx, dy)
        if pivot is not None:
            delta = self.rot @ old_rot.T
            eye = pivot + delta @ (old_eye - pivot)
            self.target = eye - self.dist * self.back

    def _orbit_rot(self, dx, dy):
        rot = rot_axis(WORLD_UP, -dx * ORBIT_SPEED) @ self.rot
        pitched = rot_axis(rot[:, 0], -dy * ORBIT_SPEED) @ rot
        if pitched[1, 1] >= -1e-6:  # do not tip over the pole
            rot = pitched
        # remove roll angle: keep right horizontal
        back = rot[:, 2]
        right = np.cross(WORLD_UP, back)
        n = np.linalg.norm(right)
        right = right / n if n > 1e-6 else rot[:, 0]
        self.rot = np.column_stack([right, np.cross(back, right), back])

    def pan(self, dx, dy, fov, viewport_height):
        scale = self.dist * math.tan(fov / 2) * 2 / max(viewport_height, 1)
        self.target = self.target + (-dx * self.right + dy * self.up) * scale

    MIN_DIST, MAX_DIST = 0.2, 100000.0  # 100 km: clip planes grow along (vp._near/_far), the limit only protects the numbers

    def dolly(self, amount):
        """Zoom continuously (same factor per mouse distance) - never a jump: if the camera is already outside the
        limits (e.g. after framing), it continues from there."""
        dist = self.dist * math.exp(-amount)
        lo, hi = min(self.MIN_DIST, self.dist), max(self.MAX_DIST, self.dist)
        self.dist = max(lo, min(hi, dist))

    # --- Fahrten ---
    def state(self):
        return self.target.copy(), self.dist, self.rot.copy()

    def set_state(self, target, dist, rot):
        self.target, self.dist, self.rot = target, dist, rot

    @staticmethod
    def interpolate(a, b, t):
        """Intermediate state of two state() tuples, t in [0, 1]."""
        t = t * t * (3 - 2 * t)  # ease in/out
        target = a[0] + (b[0] - a[0]) * t
        dist = a[1] * (b[1] / a[1]) ** t
        rot = _quat_to_mat(_slerp(_mat_to_quat(a[2]), _mat_to_quat(b[2]), t))
        return target, dist, rot
