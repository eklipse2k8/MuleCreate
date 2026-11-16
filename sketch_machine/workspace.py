"""State shared by all viewports: scene, selection, tool settings, clipboard.

Each viewport has only its own camera and its own mouse/keyboard state; everything else
lives here, so a change in one viewport applies immediately in all the others.
"""
from PySide6.QtCore import QObject, Signal

from .clipboard import Clipboard
from .scene import Scene

PEN_PX_DEFAULT = 4.0  # pen width in pixels when drawing (default mode)
PEN_WORLD_DEFAULT = 0.03  # pen width in world units (alternative mode)
PEN_MAX_WORLD = 50.0  # largest stroke width in world units (right-click -> Maximum stroke width ..., saved)
PEN_MAX_WORLD_LIMIT = 5000.0  # upper limit of this setting: 5 km
SMOOTH_MAX_FACTOR = 8.0  # default: smooth slider at 100% = this many pen radii (adjustable live)
ERASER_PX_DEFAULT = 24.0  # diameter of the eraser in pixels
SNAP_ANGLE_DEFAULT = 10.0  # snapping with Ctrl: degrees (rotate, straight lines)
SNAP_SCALE_DEFAULT = 10.0  # percent
SNAP_MOVE_DEFAULT = 1.0  # world units
CLEANUP_DIST_DEFAULT = 0.02  # cleanup snap distance (world units = meters): 2 cm
CLEANUP_DIST_RANGE = (0.001, 1.0)  # slider in the cleanup menu, logarithmic

# Attributes a viewport does not hold itself but looks up here
SHARED = ("scene", "selection", "edge_selection", "detached", "select_mode", "planes_visible", "xray",
          "multi_mode", "surface_opacity", "xray_opacity", "pen_px", "pen_world", "pen_world_mode", "smooth",
          "smooth_max_factor", "pen_max_world", "eraser_px",
          "component", "point_selection", "seg_selection", "free_draw", "notes_mode", "notes_visible", "timing_mode")


class Workspace(QObject):
    status_changed = Signal(str)
    scene_changed = Signal()  # structure, names, selection or activation have changed
    toggles_changed = Signal()  # modes and toggles (selection, planes, X-ray, multi)
    timing_changed = Signal()  # timing data (notes, cameras, poses, drawings) - panel and timeline
    frame_changed = Signal(int)  # current frame

    def __init__(self):
        super().__init__()
        self.paint_only = False  # during scene_changed: only new paint strokes were added (outliner stays put)
        self.scene = Scene()
        self.selection = []  # ids of planes, stroke objects, surfaces and meshes
        self.edge_selection = []  # selected edges/lines (references from edges.py)
        self.component = "edge"  # Auswahlmodus: "point" (1), "edge" (2), "face" (3) – wie in Houdini
        self.point_selection = []  # selected points ("pt", stroke_id, line_id, node) - components.py
        self.seg_selection = []  # selected sub-edges ("seg", stroke_id, line_id, a, b)
        self.detached = frozenset()  # pasted lines: move without coupling/welding
        self.pending_paste = None  # pasted copy still lying on the original (only takes effect once moved)
        self.select_mode = False  # S: pure selecting (edges, objects, rectangle)
        self.planes_visible = True
        self.draw_tool = "pen"  # draw mode: "pen", "brush" (A) or "eraser" (D)
        self.last_draw_tool = "pen"  # tool before the eraser (A returns to it)
        self.paint_color = (0.24, 0.23, 0.22)  # color of brush and surface tinting (RGB 0..1)
        self.recent_colors = []  # recently used colors (newest first), remembered globally
        self.board_color = None  # pen color in the note board (RGB 0..1; None = ink, follows the interface)
        self.swatch_mode = "gray"  # swatches in the bar: "gray" (grays) or "color" (recent colors)
        self.notice = None  # (text, time): short notice for the status line  # drawing aids off: still fade lines behind drawing surfaces
        self.xray = False
        self.free_upright = False  # free mode (Q): upright plane instead of plane facing the camera (right-click toggle)
        self.extrude_surface = True  # X also creates surfaces (like a loft); off (right-click menu): lines only
        self.multi_mode = False  # default: only the active surface; B / icon = multi (click collects surfaces)
        self.light_on = False  # light mode (sun): display only
        self.sun_edit = False  # edit sun: sky disc at the bottom right of the viewport

        self.cleanup_dist = CLEANUP_DIST_DEFAULT  # cleanup menu: snap distance (world units) for close gaps, weld, fuse
        self.cleanup_global = False  # cleanup menu: off = selection only, on = everything
        self.magnet = True  # magnet (toolbar): stroke start/end snap to lines; off = draw freely
        # Pressure sensitivity (graphics tablet) per tool, 0..1: 0 = pressure ignored; 1 = lightest touch 10 %,
        # firmest 200 % - pen/brush: stroke width, eraser: eraser strength
        self.pressure = {"pen": 0.0, "brush": 0.0, "eraser": 0.0}
        self.last_line_tool = "pen"  # A: pen or brush (whichever was used last)
        self.notes_mode = False  # N: third base state - create, connect, edit notes
        self.notes_visible = True  # show notes (icon at the top right)
        # Timing (fourth base state, timing.py): paint flipbook planes, set up timing cameras, timeline
        self.timing_mode = False
        self.playing = False  # timeline is playing (expensive extras like note occlusion rest then)
        self.play_requested = False  # Alt+A in the viewport: the timeline starts/stops playback
        self.timing_cam = None  # id of the selected timing camera (panel, camera row of the timeline)
        self.flip_cache = None  # (scene, frame, {plane id: frames}, {plane id: current drawing}) - frame filter
        self.active_note = None  # id of the most recently clicked note
        self.active_anchor = None  # (note id, index): clicked anchor point - only its parts light up
        self.free_draw = False  # Q: free mode - pen attaches to lines/surfaces, draws in the view plane
        self.surface_opacity = 1.0  # opacity of imported meshes (slider)
        # Show/hide (display only, top right): pencil lines, color lines (brush), painting
        self.layers_visible = {"lines": True, "brush": True, "paint": True, "surfaces": True}
        self.knot_mode = "auto"  # drag points: auto (as the line kinks at the point) | soft (always soft) | hard
        self.value_tool = None  # edit tool on: "hardness" (K) or "smooth" (J) - dragging sets the value
        self.paint_mode = False  # paint mode (S): pen/brush paint dead strokes lying flat
        self.xray_opacity = 0.6  # X-ray: opacity of the front layer (occluded parts 40 % of it), right-click on the icon
        self.wireframe = False  # wireframe: in X-ray additionally show edges of imported meshes (overlay as in Blender)
        self.wire_opacity = 0.25  # ... opacity of the edges, right-click on the icon
        self.material_scale = 1.0  # global material scale of the surfaces (right-click on the X-ray icon)
        self.point_scale = 1.0  # point size in edit (point/edge mode), slider in the View menu
        self.pen_px = PEN_PX_DEFAULT
        self.pen_world = PEN_WORLD_DEFAULT
        self.pen_world_mode = True  # True: fixed world unit (default), False: size in pixels when drawing
        self.smooth = 0.0  # smooth slider 0..1
        self.smooth_max_factor = SMOOTH_MAX_FACTOR
        self.pen_max_world = PEN_MAX_WORLD
        self.eraser_px = ERASER_PX_DEFAULT
        # Snapping with Ctrl (right-click -> Snap steps ..., saved in the settings)
        self.snap_angle = SNAP_ANGLE_DEFAULT  # degrees: rotate and straight lines
        self.snap_scale = SNAP_SCALE_DEFAULT  # percent
        self.snap_move = SNAP_MOVE_DEFAULT  # world units
        self.gizmo_tool = None  # translate | rotate | scale | None
        self.gizmo_space = "world"  # world | local
        self.clipboard = Clipboard()
        self.axis_mode = False  # Alt + A: gizmo moves only the pivot
        # Pivot of the current selection: (selection key, point, axes or None, own axis?).
        # On first use the middle of the bounding box, then moves along; new selection or undo: anew
        self.selection_pivot = None
        self.target_cache = (None, None)
        self.seg_cache = None  # (scene, {kind: segment arrays}) for picking lines; anew on every change
        self.points_cache = None  # (scene, points) - line ends, corners, inserted points (snapping while drawing)
        self.viewports = []
        self.current = None  # most recently used viewport (toolbar, outliner, menu act there)
