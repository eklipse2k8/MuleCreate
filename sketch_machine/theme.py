"""Color scheme "Drawing office": warm drawing paper, graphite, tracing-paper planes, muted
accent colors (Prussian blue = active, terracotta = selected, sage green = both).

All viewport colors are here so that a second (dark) scheme can later be placed next to
it. Qt colors for the overlay (QPainter), float tuples for the shaders.
"""
from PySide6.QtGui import QColor


def rgb(color):
    """QColor -> (r, g, b) in 0..1 for the shaders."""
    return color.redF(), color.greenF(), color.blueF()


# --- Paper and graphite ---
PAPER = QColor(227, 226, 221)  # background: drawing paper (a bit lighter, 40 % desaturated)
PAPER_STAIN = 0.0025  # strength of the large, soft blotches in the paper (only subconsciously noticeable)
PAPER_GRAIN = 0.05  # strength of the fine paper grain and fibers
PAPER_VIGNETTE = 0.07  # darkening toward the corners
GRAPHITE = QColor(58, 56, 54)  # pen color (pencil)
GRAPHITE_SOFT = QColor(58, 56, 54, 150)  # guide lines in the overlay (rectangle, string, circles)

# --- Accents: active / selected / both ---
SEA = QColor(62, 146, 126)  # active drawing surface/plane: sea green/aqua
PRUSSIAN = QColor(52, 92, 128)  # active: drawing happens here
TERRACOTTA = QColor(228, 128, 26)  # selected: is being transformed (strong orange-yellow)
SAGE = QColor(96, 138, 112)  # both
OCHRE = QColor(196, 150, 60)  # hover at the gizmo, pivot
OCTOPUS = QColor(206, 38, 150)  # arms of the note octopus (magenta, only on the selected note)

# planes as tracing paper: (fill, line) by (active, selected). The fill is a
# light, milky haze over the paper; the state shows mainly in border and grid
TRACING = QColor(250, 248, 242)
PLANE_COLORS = {
    (False, False): (QColor(234, 235, 221, 130), QColor(112, 126, 110)),  # sand with a hint of sea green
    (True, False): (QColor(186, 238, 214, 180), SEA),  # active (drawing happens here): light, cool aqua
    (False, True): (QColor(255, 200, 112, 160), TERRACOTTA),  # selected: strong orange-yellow
    (True, True): (QColor(232, 243, 238, 160), SAGE),
}
# drawing surfaces, neither active nor selected: like the active one but desaturated - "I can click on them
# and draw"; active/selected like the planes
SURFACE_IDLE_COLORS = (QColor(214, 226, 204, 152), QColor(96, 124, 104))  # same tone as active, desaturated
# gray tones of the color swatches (brush, surface tinting): graphite ... light gray
GRAY_DARK = (0.24, 0.23, 0.22)
GRAY_LIGHT = (0.86, 0.85, 0.83)  # lightest gray tone of the palette
GRAY_TONES = (0.0, 0.25, 0.5, 0.75, 1.0)  # palette: graphite ... light gray
COLOR_VIEW = True  # color view (switch at top right); off = everything in black and white
RECENT_COLORS = 8  # the color picker remembers this many recently used colors
ACTIVE_GLAZE = 0.2  # active drawing plane lying on a surface: glazed in color with this opacity


def gray_tone(tone):
    """Gray tone of the palette (0 graphite ... 1 light gray) as (r, g, b)."""
    return tuple(a + (b - a) * float(tone) for a, b in zip(GRAY_DARK, GRAY_LIGHT))

# loft drawing surfaces (curved, through cross-sections): inactive ocher yellow, active like any drawing surface
LOFT_IDLE_COLORS = (QColor(250, 236, 206, 128), QColor(178, 138, 72))
# highlighting by level (0 normal, 1 selected, 2 active for drawing): (grid, border opacity, border width)
# 3: drawing surface, clickable (neither active nor selected)
PLANE_EMPHASIS = {0: (0.035, 0.45, 1.0), 1: (0.12, 1.0, 2.5), 2: (0.18, 1.0, 2.5), 3: (0.1, 0.7, 1.5)}
SURFACE_GRID_ALPHA = {0: 0.10, 1: 0.24, 2: 0.36, 3: 0.22}  # projected grid on drawing surfaces
MESH_TINT_ALPHA = {(False, False): 0.0, (True, False): 0.28, (False, True): 0.34, (True, True): 0.3}
PAPER_VIEW_SHADE = 0.2  # paper surfaces get darker by up to this much the flatter one looks at them
TRACING_VIEW_MILK = 0.85  # tracing paper: under a flat view up to this much milkier (fraction of the opacity)

# --- Strokes ---
STROKE_COLOR = QColor(GRAPHITE)  # color of the pencil lines (own object: adjustable under View, like the chalk)
SELECTED_STROKE_COLOR = TERRACOTTA
DRAWING_COLOR = QColor(40, 38, 36)  # stroke currently being created
STRAIGHT_COLOR = PRUSSIAN  # straight line or recognized shape before release
CONNECT_COLOR = SAGE  # Connect tool
EDGE_LINE_COLOR = QColor(53, 123, 119)  # edit mode: outer lines of surfaces - dark petrol (surface green, stronger)
EDGE_LINE_MIX = 0.8  # this much of it instead of graphite
ERASER_COLOR = TERRACOTTA
PIVOT_COLOR = OCHRE

# --- Drawing surfaces (like planes: tracing paper, colors from PLANE_COLORS) ---
SURFACE_PAPER_GRAIN = 0.06  # paper texture in the base tone of the surfaces

# --- Gizmos, axes, labels ---
AXIS_COLORS = (QColor(178, 74, 62), QColor(92, 138, 72), QColor(62, 102, 168))  # X, Y, Z muted
HOVER_COLOR = OCHRE
VIEW_RING_COLOR = QColor(128, 92, 168)  # rotating around the view direction
GIZMO_CENTER = QColor(70, 66, 62)
LABEL_COLOR = QColor(90, 84, 76, 190)  # view name
CURRENT_FRAME = QColor(52, 92, 128, 120)  # frame around the active viewport
CLOSE_BG, CLOSE_FG = QColor(58, 56, 54, 22), QColor(58, 56, 54, 170)
CLOSE_BG_HOVER, CLOSE_FG_HOVER = QColor(188, 104, 62, 210), QColor(250, 246, 238)
BAND_PEN, BAND_FILL = QColor(58, 56, 54, 170), QColor(58, 56, 54, 14)  # selection rectangle
FEEDBACK_PEN, FEEDBACK_FILL = QColor(58, 56, 54, 200), QColor(58, 56, 54, 30)  # pen size
GIZMO_HALO = QColor(58, 56, 54, 16)  # circle behind the axis gizmo on hover
ERROR_BG, ERROR_FG = QColor(236, 230, 216), QColor(170, 60, 50)

# hidden lines: strokes behind hidden drawing surfaces (opacity fraction)
HIDDEN_LINE_FADE = 0.16

# pencil grain of the strokes (renderer): 0 = smooth
STROKE_GRAIN = 1.0

# --- Viewport light (drawing paper) / dark (chalkboard) ---
# switching recolors the existing QColor objects (all that use them follow) and sets the
# numeric values anew. The surfaces stay the same in both modes.
_CHALK = (232, 230, 222)
DARK = {
    "PAPER": (36, 41, 39), "GRAPHITE": _CHALK, "GRAPHITE_SOFT": (*_CHALK, 150), "DRAWING_COLOR": (250, 248, 240),
    "PRUSSIAN": (150, 190, 225), "SEA": (110, 200, 170), "SAGE": (140, 190, 160), "OCHRE": (220, 180, 90),
    "TRACING": (60, 66, 63),
    "GIZMO_CENTER": (220, 215, 205), "LABEL_COLOR": (200, 196, 186, 190), "CURRENT_FRAME": (150, 190, 225, 120),
    "CLOSE_BG": (*_CHALK, 22), "CLOSE_FG": (*_CHALK, 170), "BAND_PEN": (*_CHALK, 170), "BAND_FILL": (*_CHALK, 14),
    "FEEDBACK_PEN": (*_CHALK, 200), "FEEDBACK_FILL": (*_CHALK, 30), "GIZMO_HALO": (*_CHALK, 16),
    "ERROR_BG": (36, 41, 39), "ERROR_FG": (230, 120, 100), "VIEW_RING_COLOR": (170, 140, 210),
    "EDGE_LINE_COLOR": (124, 218, 206), "STROKE_COLOR": _CHALK,
}
DARK_TUPLES = {  # (name, index) -> rgba for colors in tuples/dicts
    ("AXIS_COLORS", 0): (222, 104, 92), ("AXIS_COLORS", 1): (132, 192, 104), ("AXIS_COLORS", 2): (104, 152, 222),
    ("PLANE_COLORS", (False, False), 0): (200, 210, 200, 34), ("PLANE_COLORS", (False, False), 1): (150, 165, 150),
    ("PLANE_COLORS", (True, False), 0): (110, 210, 175, 58),
    ("PLANE_COLORS", (False, True), 0): (240, 160, 70, 66),
    ("PLANE_COLORS", (True, True), 0): (150, 200, 170, 50),
    ("SURFACE_IDLE_COLORS", 0): (160, 190, 170, 44), ("SURFACE_IDLE_COLORS", 1): (122, 162, 136),
    ("LOFT_IDLE_COLORS", 0): (220, 180, 110, 40), ("LOFT_IDLE_COLORS", 1): (204, 164, 92),
}
DARK_VALUES = {"PAPER_STAIN": 0.03, "PAPER_GRAIN": 0.075, "PAPER_VIGNETTE": 0.2, "STROKE_GRAIN": 1.55,
               "SURFACE_PAPER_GRAIN": 0.04, "TRACING_VIEW_MILK": 0.5, "PAPER_VIEW_SHADE": 0.1}
dark = False


def _lookup(key):
    obj = globals()[key[0]]
    for k in key[1:]:
        obj = obj[k]
    return obj


_LIGHT = {name: QColor(globals()[name]) for name in DARK}
_LIGHT_TUPLES = {key: QColor(_lookup(key)) for key in DARK_TUPLES}
_LIGHT_VALUES = {name: globals()[name] for name in DARK_VALUES}


def set_dark(on):
    """Switch the viewport color scheme: chalkboard (True) or drawing paper (False)."""
    global dark
    dark = bool(on)
    for name, rgba in DARK.items():
        globals()[name].setRgb(*rgba) if dark else globals()[name].setRgba(_LIGHT[name].rgba())
    for key, rgba in DARK_TUPLES.items():
        _lookup(key).setRgb(*rgba) if dark else _lookup(key).setRgba(_LIGHT_TUPLES[key].rgba())
    for name, value in DARK_VALUES.items():
        globals()[name] = value if dark else _LIGHT_VALUES[name]


PENCIL_DEFAULT, CHALK_DEFAULT = (58, 56, 54), _CHALK


def stroke_colors():
    """(pencil, chalk) as RGB 0..255 - the color of the lines on paper or on the chalkboard."""
    return _LIGHT["STROKE_COLOR"].getRgb()[:3], tuple(DARK["STROKE_COLOR"][:3])


def set_stroke_colors(pencil=None, chalk=None):
    """Set pencil and/or chalk color (RGB 0..255); the displayed color follows the current mode."""
    if pencil is not None:
        _LIGHT["STROKE_COLOR"].setRgb(*pencil)
    if chalk is not None:
        DARK["STROKE_COLOR"] = tuple(chalk)
    STROKE_COLOR.setRgb(*(DARK["STROKE_COLOR"] if dark else _LIGHT["STROKE_COLOR"].getRgb()[:3]))


# --- Color Compress (slider at top right, display only) ---
# Compresses the grays (brush) so they stand out from the background: on the chalkboard
# the darkest tone is raised (at 1 clearly lighter than the board), on paper the lightest is lowered.
# The order of the tones stays - light and shadow tell the same thing.
COLOR_COMPRESS = 0.0
COMPRESS_MARGIN = 0.2  # at full slider: this much lighter (board) or darker (paper) than the background


_DISPLAY_RGB = {}  # (color, settings) -> displayed color: asked per frame for every brush stroke


def display_rgb(rgb):
    """Color of a brush stroke as it is displayed: Color Compress compresses only the brightness, in the
    black-and-white view only the brightness."""
    key = (tuple(rgb), COLOR_COMPRESS, COLOR_VIEW, COMPRESS_MARGIN, PAPER.rgba(), tuple(GRAY_DARK), tuple(GRAY_LIGHT),
           dark)
    hit = _DISPLAY_RGB.get(key)
    if hit is None:
        if len(_DISPLAY_RGB) > 4096:
            _DISPLAY_RGB.clear()
        hit = _DISPLAY_RGB[key] = _display_rgb(rgb)
    return hit


def _display_rgb(rgb):
    w = (0.2126, 0.7152, 0.0722)
    lum = lambda c: sum(a * b for a, b in zip(c, w))
    lo, hi = gray_endpoints()
    l0, l1 = lum(GRAY_DARK), lum(GRAY_LIGHT)
    t = (lum(rgb) - l0) / max(l1 - l0, 1e-4)
    target = lum(lo) + (lum(hi) - lum(lo)) * t
    shift = target - lum(rgb)
    out = [min(max(c + shift, 0.0), 1.0) for c in rgb]
    if not COLOR_VIEW:
        g = lum(out)
        out = [g, g, g]
    return tuple(out)


def gray_endpoints():
    """(darkest, lightest) gray tone of the palette after Color Compress, as (r, g, b) in 0..1."""
    lo, hi = tuple(GRAY_DARK), tuple(GRAY_LIGHT)
    k = max(0.0, min(1.0, COLOR_COMPRESS))
    if k <= 0:
        return lo, hi
    bg = rgb(PAPER)
    if dark:
        target = tuple(min(1.0, c + COMPRESS_MARGIN) for c in bg)
        lo = tuple(a + (t - a) * k for a, t in zip(lo, target))
    else:
        target = tuple(max(0.0, c - COMPRESS_MARGIN) for c in bg)
        hi = tuple(a + (t - a) * k for a, t in zip(hi, target))
    return lo, hi


# --- Active base plane "infinite": outside its rectangle a soft neutral grid that fades with
# distance and under a flat view (shows where the plane cuts the space; one keeps drawing there)
INFINITE_FILL_ALPHA = 0.015  # milk outside the core (fraction of opacity) - very subtle
INFINITE_GRID_ALPHA = 0.03  # fine grid outside the core
INFINITE_TILE_ALPHA = 0.07  # tiles in the size of the plane: its rectangle repeats
INFINITE_REACH = 25.0  # fade out up to this many plane spacings or core sizes


# --- Surface display (materials are only forms of display) ---
# (key, name in the menu) - the order is the index in the shader (renderer.MATERIAL_FS)
MATERIALS = [("papier", "Papier"), ("stoff", "Stoff"), ("pappe", "Finnpappe"), ("holz", "Holz"), ("spruehfarbe", "Sprühfarbe")]
MATERIAL_INDEX = {key: i for i, (key, _) in enumerate(MATERIALS)}
MATERIAL_SCALE = 1.0  # global material scale (world units per texture unit), right-click menu
MATERIAL_SIZE_WEIGHT = 0.1  # fraction of the surface size in the grain (9 : 1): large surfaces somewhat coarser
MATERIAL_SIZE_REF = 4.0  # surface size (diagonal) at which only the global scale applies
STAIN_STRENGTH = 1.0  # blotches over all materials (0 = off)
SURFACE_STATE_GLAZE = (0.08, 0.28)  # tint of the material in the state color: (active drawing surface, selected)
