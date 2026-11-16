"""Light mode: an invisible sun with direction (azimuth, elevation). Display only – colors and attributes of the
scene do not change.

The color roughly follows a physical sky: white from SUN_WHITE_DEG elevation up, increasingly golden, orange below
and reddish at the horizon. Shadows and averted sides get a touch of sky blue.
"""
import math

import numpy as np

SUN_DEFAULT = (35.0, 40.0)  # azimuth (degrees, 0 = from the front/+Z, 90 = from the right/+X), elevation above the horizon
SUN_WHITE_DEG = 17.0  # from this elevation on white light
SKY_TINT = (0.84, 0.89, 1.0)  # shadow side: touch of sky blue
AWAY_DARK = 0.5  # surfaces facing away from the sun: this much darker
SHADOW_DARK = 0.45  # in shadow: this much darker
DOME = 0.25  # sky light (dome light) mixed in: shapes stay readable in shadow
# sun color by elevation (degrees): control points from reddish at the horizon to white
_SUN_COLORS = ((-5.0, (0.95, 0.42, 0.28)), (0.0, (1.0, 0.5, 0.3)), (5.0, (1.0, 0.68, 0.42)),
               (10.0, (1.0, 0.84, 0.64)), (SUN_WHITE_DEG, (1.0, 1.0, 1.0)))


def direction(sun):
    """Direction to the sun (unit vector, Y up)."""
    az, el = (math.radians(float(x)) for x in sun)
    return np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])


def color(sun):
    """Color of the sunlight by elevation."""
    el = float(sun[1])
    pts = _SUN_COLORS
    if el <= pts[0][0]:
        return pts[0][1]
    for (e0, c0), (e1, c1) in zip(pts[:-1], pts[1:]):
        if el <= e1:
            t = (el - e0) / (e1 - e0)
            return tuple(a + (b - a) * t for a, b in zip(c0, c1))
    return pts[-1][1]


def bands_from_slider(value):
    """Slider 0..100 -> light steps: left 3, middle 10, far right continuous (0)."""
    if value >= 100:
        return 0
    return int(round(3.0 * (10.0 / 3.0) ** (value / 50.0)))


def slider_from_bands(bands):
    if not bands:
        return 100
    return int(round(min(max(50.0 * math.log(bands / 3.0) / math.log(10.0 / 3.0), 0.0), 99.0)))


def from_disc(dx, dy):
    """Sky disc (center = zenith, edge = horizon, top = back/-Z, right = +X) -> (azimuth, elevation).
    dx, dy: position in the circle, -1..1 (dy positive downwards)."""
    r = min(math.hypot(dx, dy), 1.0)
    el = 90.0 * (1.0 - r)
    az = math.degrees(math.atan2(dx, dy)) if r > 1e-6 else 0.0
    return az % 360.0, el


def to_disc(sun):
    """(Azimuth, elevation) -> position on the sky disc (dx, dy)."""
    az, el = math.radians(float(sun[0])), float(sun[1])
    r = max(0.0, min(1.0, 1.0 - el / 90.0))
    return r * math.sin(az), r * math.cos(az)
