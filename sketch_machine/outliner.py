"""Outliner: lists planes, imported items (meshes) and stroke objects, selection synchronized in both directions.

Hierarchy as in Cinema 4D: nulls (also symmetry and array) stand under "Groups" and show the objects below them;
what lies in a null no longer stands in its category. Dragging onto a null hangs it underneath, dragging onto a category
(or into the empty) brings it to the top level."""
import math
import re

from PySide6.QtCore import QItemSelectionModel, QSettings, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QGridLayout, QHeaderView, QLabel,
                               QStyledItemDelegate,
                               QLineEdit, QMenu, QSlider, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                               QVBoxLayout, QWidget)

from . import brief, theme, ui
from .scene import MeshObject, NullObject, StrokeObject, SurfaceObject
from .i18n import tr

ID_ROLE = Qt.UserRole
NAME, MATERIAL, BRIEF, INFO, EYE = range(5)  # columns
COLUMN_WIDTHS = {NAME: 170, MATERIAL: 84, BRIEF: 76, INFO: 76}  # default widths (draggable, stored per machine)
BRIEF_ROLE = Qt.UserRole + 2  # row has a brief field: (text, own level?) – drawn like a dropdown
COLOR_ROLE = Qt.UserRole + 1  # color of the null under which the row lies (QColor) – stripe and tint
KIND_INFO = {"null": "Null", "symmetry": tr("Symmetrie"), "array": "Array"}
# colors for nulls (muted, readable on light and dark background)
NULL_COLORS = ((tr("Rot"), (200, 90, 80)), ("Orange", (215, 140, 65)), (tr("Gelb"), (200, 180, 70)), (tr("Grün"), (105, 170, 95)),
               (tr("Türkis"), (75, 165, 165)), (tr("Blau"), (90, 130, 205)), (tr("Violett"), (150, 110, 195)),
               (tr("Rosa"), (205, 110, 160)))
STRIPE_PX = 4  # color stripe at the left edge
TINT_ALPHA = 30  # tint of the color in the row background (0..255)


def natural_key(name):
    """Sort key by name, numbers as numbers: "Part 2" before "Part 10", "001_x" before "002_y"."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", (name or "").lower()) if t]


class BriefDelegate(QStyledItemDelegate):
    """Column "Brief": like a small dropdown (frame, arrow) – shows that you can choose here, without a
    real selection field per row (with many meshes that slowed the rebuild)."""

    def paint(self, p, option, index):
        cell = index.data(BRIEF_ROLE)
        if cell is None:
            return super().paint(p, option, index)
        text, own = cell
        r = option.rect.adjusted(3, 3, -4, -3)
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        hover = bool(option.state & option.state.State_MouseOver)
        p.setPen(QColor(ui.ACCENT if hover else ui.LINE))
        p.setBrush(QColor(ui.PANEL).lighter(115 if hover else 105))
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor(ui.TEXT if own else ui.TEXT_DIM))
        p.drawText(r.adjusted(6, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   option.fontMetrics.elidedText(text, Qt.ElideRight, max(r.width() - 20, 8)))
        p.setPen(QColor(ui.TEXT_DIM))
        p.drawText(r.adjusted(0, 0, -5, 0), Qt.AlignVCenter | Qt.AlignRight, "▾")
        p.restore()


class Outliner(QTreeWidget):
    def __init__(self, workspace):
        super().__init__()
        self.ws = workspace
        self.setHeaderLabels(["Name", "Material", "Brief", "Info", ""])
        self.setItemDelegateForColumn(BRIEF, BriefDelegate(self))
        self.setItemDelegateForColumn(MATERIAL, BriefDelegate(self))  # material: painted like a dropdown, menu on click
        # option rows (surface, null, plane): the embedded panel is only created on expanding – one
        # widget per row cost ~0.7 s at ~150 surfaces on EVERY change (harbor test 09.11.)
        self._lazy = {}  # id(option item) -> factory of the panel
        self.itemExpanded.connect(self._ensure_panel)
        self.setMouseTracking(True)  # brief field is highlighted under the cursor
        self.headerItem().setToolTip(BRIEF, tr("Verbindlichkeit fürs Brief: wie genau sich die KI an dieses Objekt hält (Nulls: alles darunter) – leer: wie im Brief-Auftrag"))
        # header row: the separator lines resize name, material and info (widths stored per machine); what does not
        # fit in the outliner scrolls horizontally
        head = self.header()
        head.setStretchLastSection(False)
        head.setMinimumSectionSize(24)
        self._picture_open = set()  # load image ticked, still without a file
        settings = QSettings("SketchMachine", "SketchMachine")
        for col, width in COLUMN_WIDTHS.items():
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            self.setColumnWidth(col, int(settings.value(f"outliner_width_{col}", width)))
        head.setSectionResizeMode(EYE, QHeaderView.Fixed)
        self.setColumnWidth(EYE, 26)  # eye: show/hide
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        head.sectionResized.connect(self._on_section_resized)
        self.setIndentation(14)  # nest groups: names stay readable
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setMinimumWidth(230)
        self._syncing = False
        self._expanded = set()  # surfaces whose options are expanded (arrow on the left)
        self._collapsed = set()  # collapsed nulls (new ones are open)
        self._from_outliner = False  # selection came from the outliner itself: do not scroll there
        self._shown_selection = set()  # selection at the last rebuild (changed in the viewport: scroll there)
        self._filter = ""  # search field: only matching names (and their parents)
        self.search = None
        self.setDragDropMode(QAbstractItemView.DragDrop)  # re-parenting itself in dropEvent (Qt moves nothing)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

        self.groups_root = QTreeWidgetItem([tr("Gruppen")])
        self.planes_root = QTreeWidgetItem([tr("Ebenen")])
        self.meshes_root = QTreeWidgetItem(["Import"])  # imported meshes, also as USD hierarchy
        self.strokes_root = QTreeWidgetItem([tr("Strokes")])
        self.surfaces_root = QTreeWidgetItem([tr("Flächen")])
        self.roots = (self.groups_root, self.planes_root, self.meshes_root, self.surfaces_root, self.strokes_root)
        for root in self.roots:
            root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
            font = root.font(0)
            font.setBold(True)
            root.setFont(0, font)
        self.addTopLevelItems(list(self.roots))
        self.expandAll()

        self.itemSelectionChanged.connect(self._on_selection)
        self.itemChanged.connect(self._on_renamed)
        self.itemClicked.connect(self._on_clicked)
        self.itemExpanded.connect(lambda item: self._remember_expanded(item, True))
        self.itemCollapsed.connect(lambda item: self._remember_expanded(item, False))
        self._recursing = False  # Shift+click on the arrow: everything below as well
        self.itemExpanded.connect(lambda item: self._shift_expand(item, True))
        self.itemCollapsed.connect(lambda item: self._shift_expand(item, False))
        # rebuild delayed: never delete items in the middle of a signal of the tree itself
        self._rebuild_timer = QTimer(self, singleShot=True, interval=0)
        self._rebuild_timer.timeout.connect(self.rebuild)
        workspace.scene_changed.connect(self._scene_changed)
        workspace.toggles_changed.connect(self._rebuild_timer.start)
        self.rebuild()

    def _scene_changed(self):
        if self.ws.paint_only:  # new paint stroke: only the line count of its object is no longer right
            return self._update_line_count(self.vp.scene.active_stroke)
        self._rebuild_timer.start()

    def _update_line_count(self, stroke):
        it = QTreeWidgetItemIterator(self)
        while it.value():
            if it.value().data(0, ID_ROLE) == stroke.id:
                return it.value().setText(INFO, self._line_count(stroke))
            it += 1

    @staticmethod
    def _line_count(stroke):
        n = len(stroke.curves)
        return tr("{0} Linie{1}").format(n, 'n' if n != 1 else '')

    @property
    def vp(self):
        """The most recently used viewport (selection and renaming go through it)."""
        return self.ws.current

    def _on_section_resized(self, index, old, new):
        if index in COLUMN_WIDTHS:
            QSettings("SketchMachine", "SketchMachine").setValue(f"outliner_width_{index}", int(new))

    def panel(self):
        """Outliner with a search field above it (for the dock)."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Suchen …"))
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip(tr("Nur Objekte mit diesem Text im Namen (und die Gruppen, in denen sie liegen)"))
        self.search.textChanged.connect(self.set_filter)
        lay.addWidget(self.search)
        lay.addWidget(self)
        return box

    def drawRow(self, painter, option, index):
        """Rows under a null with color: tint in the background and stripe at the left edge."""
        color = index.siblingAtColumn(0).data(COLOR_ROLE)
        if color is not None:
            tint = QColor(color)
            tint.setAlpha(TINT_ALPHA)
            painter.fillRect(option.rect, tint)
        super().drawRow(painter, option, index)
        if color is not None:
            painter.fillRect(0, option.rect.top(), STRIPE_PX, option.rect.height(), QColor(color))

    def _item(self, obj, info, editable, active, dimmed=False, color=None):
        item = QTreeWidgetItem([obj.name, "", "", info])
        item.setData(0, ID_ROLE, obj.id)
        if color is not None:
            item.setData(0, COLOR_ROLE, QColor(*color))
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if editable:
            flags |= Qt.ItemIsEditable
        if hasattr(obj, "parent"):  # draggable into the hierarchy (planes not)
            flags |= Qt.ItemIsDragEnabled
        if self.vp._flip_locked(obj):  # flipbook outside timing: visible, but not selectable/editable
            flags, dimmed = Qt.ItemIsEnabled, True
        if isinstance(obj, NullObject):
            flags |= Qt.ItemIsDropEnabled
        item.setFlags(flags)
        if not isinstance(obj, NullObject) and self.vp.scene.is_hidden(obj) and not getattr(obj, "hidden", False):
            dimmed = True  # hidden via its null
        if active:
            font = QFont(item.font(0))
            font.setBold(True)
            item.setFont(0, font)
        if dimmed or getattr(obj, "hidden", False):
            for col in (NAME, INFO):
                item.setForeground(col, QBrush(QColor(140, 140, 140)))
        if self._binds(obj):  # brief: own binding level bright, inherited from the null pale, none: "–"
            level, source = self.vp.scene.binding_of(obj)
            text = ("" if source is obj else "↳ ") + tr(brief.TASK_LEVELS[level][0]).split(" – ")[0] if level else "–"
            item.setData(BRIEF, BRIEF_ROLE, (text, bool(level) and source is obj))
            item.setToolTip(BRIEF, tr("Klick: Verbindlichkeit fürs Brief") + ("" if not level or source is obj
                                                                           else tr(" (von {0})").format(source.name)))
        item.setIcon(EYE, ui.icon("eye_off" if getattr(obj, "hidden", False) else "eye"))
        item.setToolTip(EYE, tr("Einblenden") if getattr(obj, "hidden", False) else tr("Ausblenden (H) – Alt+H zeigt alles"))
        return item

    def _on_clicked(self, item, column):
        """Click on the eye: show/hide object; otherwise only return focus to the viewport (keyboard shortcuts)."""
        oid = item.data(0, ID_ROLE)
        if column == BRIEF and oid is not None and self._binds(self.vp.scene.object_by_id(oid)):
            return self._binding_menu(oid)
        if column == MATERIAL and oid is not None and item.data(MATERIAL, BRIEF_ROLE) is not None:
            return self._material_menu(oid)
        if column == EYE and oid is not None:
            obj = self.vp.scene.object_by_id(oid)
            if obj is not None:
                self.vp.set_hidden(oid, not obj.hidden)
        self.vp.setFocus()

    def _shift_expand(self, item, on):
        if self._syncing or self._recursing or not QApplication.keyboardModifiers() & Qt.ShiftModifier:
            return
        self._recursing = True
        try:
            self.set_expanded_below(item, on)
        finally:
            self._recursing = False

    def _remember_expanded(self, item, on):
        oid = item.data(0, ID_ROLE)
        if self._syncing or oid is None:
            return
        if isinstance(self.vp.scene.object_by_id(oid), NullObject):
            (self._collapsed.discard if on else self._collapsed.add)(oid)
            return
        (self._expanded.add if on else self._expanded.discard)(oid)

    @staticmethod
    def _sorted(objs):
        return sorted(objs, key=lambda o: natural_key(o.name))

    def _options_row(self, item, factory, color=None):
        """Expandable option row under item; its panel is built by factory() only on expanding (_ensure_panel)."""
        props = QTreeWidgetItem()
        props.setFlags(Qt.ItemIsEnabled)
        item.addChild(props)  # across the whole width: only possible in the tree (_ensure_panel)
        if color is not None:
            props.setData(0, COLOR_ROLE, QColor(*color))
        self._lazy[id(props)] = (props, factory)
        return props

    def _ensure_panel(self, item):
        """Expanded: build the panels of the option rows directly below now (once per rebuild)."""
        for k in range(item.childCount()):
            entry = self._lazy.pop(id(item.child(k)), None)
            if entry is not None:
                entry[0].setFirstColumnSpanned(True)
                self.setItemWidget(entry[0], 0, entry[1]())

    def _add_object(self, parent_item, obj, color=None, expand=None):
        """Attach the entry of an object (with options or – for nulls – the objects below, sorted by name) to
        parent_item. color: color of the null above (a null with its own color overrides it).
        The entry is attached only AFTER its children (attaching children to a still free item costs almost nothing,
        to one in the tree ~1 ms per child); what should be expanded is collected by expand (set afterwards)."""
        scene = self.vp.scene
        expand = [] if expand is None else expand
        if isinstance(obj, NullObject):
            color = obj.color or color
            children = self._sorted(scene.children(obj))
            item = self._item(obj, f"{KIND_INFO.get(obj.kind, 'Null')} · {len(children)}", True, False, color=color)
            item.setIcon(0, ui.icon({"symmetry": "mirror", "array": "array"}.get(obj.kind, "null")))
            if obj.kind != "null":  # settings of the generator: first row below
                props = self._options_row(item, None, color)
                self._lazy[id(props)] = (props, lambda o=obj, r=props: self._null_options(o, r))
            for child in children:
                if child.id in getattr(self, "_hosts", {}):
                    continue  # surface stands under its line object
                self._add_object(item, child, color, expand)
            if obj.id not in self._collapsed:
                expand.append(item)
            parent_item.addChild(item)
            return item
        if isinstance(obj, MeshObject):
            active = obj is scene.active_surface
            count = f"{obj.geo.triangle_count:,}" if tr("Dr.") != "Dr." else f"{obj.geo.triangle_count:,}".replace(",", ".")
            info = tr("fehlt") if obj.missing else f"{count} {tr('Dr.')}"
            if active:
                info += tr(" · aktiv")
            item = self._item(obj, info, True, active, obj.missing, color=color)
            parent_item.addChild(item)
            return item
        if isinstance(obj, SurfaceObject):
            active = obj is scene.active_mesh
            # helper surfaces are pure projection surfaces like helper planes: they stand with the planes (grayed out when
            # the drawing aids are off); switch back via the arrow
            item = self._item(obj, tr("Hilfsfläche") if obj.aid else "", True, active, obj.aid and not self.vp.planes_visible,
                              color=color)
            others = getattr(self, "_foreign", {}).get(obj.id)
            if others:  # border also from foreign line objects: warning sign, hint on hover
                item.setText(INFO, "⚠")
                item.setToolTip(INFO, tr("Benutzt Rand von fremden Stroke-Objekten: {0}").format(", ".join(others)))
                item.setToolTip(NAME, item.toolTip(INFO))
            if not obj.aid:  # helper surfaces have no material
                item.setData(MATERIAL, BRIEF_ROLE, (tr(dict(theme.MATERIALS).get(obj.material, obj.material)), True))
                item.setToolTip(MATERIAL, tr("Material der Fläche (nur Darstellung) – gilt für alle gewählten Flächen, wenn diese dabei ist; Farbe: im Zeichenmodus F"))
            # expandable (arrow): helper surface, transparency, resolution
            self._options_row(item, lambda o=obj: self._surface_options(o), color)
            if obj.id in self._expanded:
                expand.append(item)
            parent_item.addChild(item)
            return item
        item = self._item(obj, self._line_count(obj), True, obj is scene.active_stroke, color=color)
        hosted = [scene.object_by_id(i) for i in getattr(self, "_hosted_by", {}).get(obj.id, [])]
        for surf in self._sorted([x for x in hosted if x is not None]):
            self._add_object(item, surf, color, expand)
        if hosted and obj.id in self._expanded:
            expand.append(item)
        parent_item.addChild(item)
        return item

    def _surface_hosts(self):
        """Show surfaces under their line object (phase 4: SurfaceObject.owner, Scene.assign_owners):
        {surface id: stroke object} and {surface id: [names of foreign line objects]} for surfaces whose border also
        comes from other line objects (⚠ with hint)."""
        sc = self.vp.scene
        owner_of = {c.id: st for st in sc.strokes for c in st.curves}
        strokes = {st.id: st for st in sc.strokes}
        hosts, foreign = {}, {}
        for f in sc.surfaces:
            if f.aid:
                continue
            st = strokes.get(getattr(f, "owner", None))
            if st is None:
                continue
            if st.parent == f.parent:  # deliberately put into another null: stays there
                hosts[f.id] = st
            others = [strokes[i].name for i in sc.line_owner_counts(f, owner_of) if i != st.id and i in strokes]
            if others:
                foreign[f.id] = others
        return hosts, foreign

    def _import_group(self, obj):
        """Null under which only imported meshes lie (e.g. the hierarchy of a USD file): stands under "Import"."""
        if not isinstance(obj, NullObject) or obj.kind != "null":
            return False
        below = self.vp.scene.descendants(obj)
        return any(isinstance(o, MeshObject) for o in below) and             all(isinstance(o, MeshObject) or isinstance(o, NullObject) and o.kind == "null" for o in below)

    def rebuild(self):
        try:
            self._rebuild()
        finally:  # never be left behind with the display switched off or a stuck _syncing
            self.setUpdatesEnabled(True)
            self._syncing = False

    def _rebuild(self):
        with self.vp.scene.hierarchy_batch():  # children per null from a table (USD: thousands of nulls)
            self._rebuild_rows()

    def _rebuild_rows(self):
        self._syncing = True
        scroll = (self.verticalScrollBar().value(), self.horizontalScrollBar().value())  # rebuild: position stays
        scene = self.vp.scene
        self.setUpdatesEnabled(False)
        cur = self.currentItem()  # anchor for Shift+click: after the rebuild the same row again (otherwise the topmost)
        cur_id = cur.data(0, ID_ROLE) if cur is not None else None
        for root in self.roots:
            root.takeChildren()
        self._lazy = {}
        self._hosts, self._foreign = self._surface_hosts()
        hosted_by = {}
        for fid, st in self._hosts.items():
            hosted_by.setdefault(st.id, []).append(fid)
        self._hosted_by = hosted_by
        expand = []
        surface = scene.active_surface
        for plane in scene.planes:
            active = plane is surface
            info = " · ".join(t for t, on in ((tr("fest"), plane.preset), (tr("aktiv"), active)) if on)
            hidden = not plane.preset and not self.vp.planes_visible
            plane_item = self._item(plane, info, not plane.preset, active, hidden)
            self._options_row(plane_item, lambda o=plane: self._picture_options(o))  # expandable: image on the plane
            self.planes_root.addChild(plane_item)
            if plane.id in self._expanded:
                expand.append(plane_item)
        for obj in self._sorted(scene.children(None)):  # top level; what lies in a null stands there
            if obj.id in self._hosts:
                continue  # stands under its line object
            root = (self.meshes_root if self._import_group(obj) else self.groups_root if isinstance(obj, NullObject)
                    else self.meshes_root if isinstance(obj, MeshObject)
                    else (self.planes_root if obj.aid else self.surfaces_root) if isinstance(obj, SurfaceObject)
                    else self.strokes_root)
            self._add_object(root, obj, expand=expand)
        for item in expand:  # only now (in the tree) expand; this also builds the panels below (_ensure_panel)
            item.setExpanded(True)
            self._ensure_panel(item)
        for root in self.roots:  # do not show empty groups (e.g. no meshes)
            root.setHidden(root.childCount() == 0)
        selected = set(self.vp.selection)
        # edit mode: also the objects to which selected lines, edges and points belong (e.g. after a double click
        # on a surface in point/edge mode the stroke objects of its lines)
        selected |= {r[1] for r in (*self.vp.edge_selection, *self.vp.seg_selection, *self.vp.point_selection)}
        it, first = QTreeWidgetItemIterator(self), None
        while it.value() is not None:
            child = it.value()
            oid = child.data(0, ID_ROLE)
            if oid is not None:
                child.setSelected(oid in selected)
                if oid in selected and first is None:
                    first = child
            it += 1
        self._apply_filter()
        if cur_id is not None:
            it = QTreeWidgetItemIterator(self)
            while it.value() is not None:
                if it.value().data(0, ID_ROLE) == cur_id:
                    self.setCurrentItem(it.value(), 0, QItemSelectionModel.NoUpdate)
                    break
                it += 1
        self.updateGeometries()
        self.verticalScrollBar().setValue(scroll[0])
        self.horizontalScrollBar().setValue(scroll[1])
        # selected in the viewport: expand the groups above and scroll there (selected from the outliner: position stays)
        if selected != self._shown_selection and not self._from_outliner and first is not None:
            up = first.parent()
            while up is not None:
                if not up.isExpanded():
                    up.setExpanded(True)
                    self._collapsed.discard(up.data(0, ID_ROLE))
                up = up.parent()
            self.scrollToItem(first, QAbstractItemView.EnsureVisible)
        self._shown_selection, self._from_outliner = selected, False
        self.setUpdatesEnabled(True)
        self._syncing = False

    # --- Search, expand/collapse ---
    def set_filter(self, text):
        self._filter = text.strip().lower()
        self._syncing = True
        self._apply_filter()
        self._syncing = False

    def _apply_filter(self):
        """Search field: hide rows without the text in the name – except groups containing a hit (those
        are expanded). Empty: everything as stored."""
        text = self._filter

        def visit(item):
            oid = item.data(0, ID_ROLE)
            hit = bool(text) and oid is not None and text in item.text(0).lower()
            below = False
            for k in range(item.childCount()):
                below = visit(item.child(k)) or below
            if oid is None and item not in self.roots:  # option row: like its object
                item.setHidden(bool(text))
                return False
            if not text:
                if item in self.roots:
                    item.setHidden(item.childCount() == 0)
                else:
                    item.setHidden(False)
                return False
            item.setHidden(not (hit or below))
            if below:
                item.setExpanded(True)
            return hit or below

        for root in self.roots:
            visit(root)

    def set_expanded_below(self, item, on):
        """Expand/collapse a group together with all groups below (surface options stay as they are)."""
        item.setExpanded(on)
        for k in range(item.childCount()):
            child = item.child(k)
            oid = child.data(0, ID_ROLE)
            if child in self.roots or isinstance(self.vp.scene.object_by_id(oid) if oid is not None else None,
                                                 NullObject):
                self.set_expanded_below(child, on)

    def _expand_all(self, on):
        for root in self.roots:
            self.set_expanded_below(root, on)

    # --- Drag and drop: hierarchy ---
    def _drop_target(self, event):
        """Null id under which it is dropped (None: top level), or ... (not droppable)."""
        item = self.itemAt(event.position().toPoint())
        pos = self.dropIndicatorPosition()
        scene = self.vp.scene
        inside = False
        while item is not None and item.data(0, ID_ROLE) is None and item not in self.roots:
            item, inside = item.parent(), True  # option row: counts as its object (for a null: into it)
        if item is None or item in self.roots:
            return None
        obj = scene.object_by_id(item.data(0, ID_ROLE))
        if isinstance(obj, NullObject) and (pos == QAbstractItemView.OnItem or inside):
            return obj.id
        return getattr(obj, "parent", None)  # next to an object: into the same null as this one

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        if event.source() is self:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.source() is not self:
            return event.ignore()
        target = self._drop_target(event)
        ids = [i.data(0, ID_ROLE) for i in self.selectedItems() if i.data(0, ID_ROLE) is not None]
        event.setDropAction(Qt.IgnoreAction)  # let Qt move nothing: rebuild from the scene
        event.accept()
        self.vp.set_parent(ids, target)
        self._rebuild_timer.start()

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        oid = item.data(0, ID_ROLE) if item is not None else None
        obj = self.vp.scene.object_by_id(oid) if oid is not None else None
        menu = QMenu(self)
        if obj is not None:
            menu.addAction(tr("Duplizieren (mit allem darunter)\tStrg+D"), self._duplicate)
            menu.addAction(tr("Löschen (mit allem darunter)\tEntf"), self._delete)
            menu.addSeparator()
        menu.addAction(tr("Null (Auswahl gruppieren)\tAlt+G"), lambda: self.vp.create_null("null"))
        menu.addAction(tr("Symmetrie (Auswahl spiegeln)"), lambda: self.vp.create_null("symmetry"))
        menu.addAction(tr("Array (Auswahl vervielfachen)"), lambda: self.vp.create_null("array"))
        if isinstance(obj, NullObject):
            menu.addSeparator()
            colors = menu.addMenu(tr("Farbe"))
            ids = [i for i in self._selected_ids() if isinstance(self.vp.scene.object_by_id(i), NullObject)] or [oid]
            for name, rgb in NULL_COLORS:
                pix = QPixmap(14, 14)
                pix.fill(QColor(*rgb))
                colors.addAction(QIcon(pix), name, lambda rgb=rgb: self.vp.set_null_color(ids, rgb))
            colors.addSeparator()
            colors.addAction(tr("Keine (wie darüber)"), lambda: self.vp.set_null_color(ids, None))
            if obj.kind != "null":
                menu.addAction(tr("Konvertieren (echte Geometrie)\tAlt+C"), self.vp.convert_generators)
            menu.addAction(tr("Gruppe auflösen\tShift+G"), self.vp.dissolve_null)
        if obj is not None and getattr(obj, "parent", None) is not None:
            menu.addAction(tr("Auf oberste Ebene"), lambda: self.vp.set_parent([i.data(0, ID_ROLE)
                                                                            for i in self.selectedItems()], None))
        menu.addSeparator()
        if isinstance(obj, NullObject):
            menu.addAction(tr("Aufklappen mit allem darunter\tShift+Klick auf den Pfeil"),
                           lambda: self.set_expanded_below(item, True))
            menu.addAction(tr("Zuklappen mit allem darunter"), lambda: self.set_expanded_below(item, False))
        menu.addAction(tr("Alles aufklappen"), lambda: self._expand_all(True))
        menu.addAction(tr("Alles einklappen"), lambda: self._expand_all(False))
        menu.exec(self.viewport().mapToGlobal(pos))

    def _selected_ids(self):
        return [i.data(0, ID_ROLE) for i in self.selectedItems() if i.data(0, ID_ROLE) is not None]

    def _duplicate(self):
        """Duplicate selected objects as new objects – a null together with everything below (lines and surfaces stay
        connected among themselves, not with the original)."""
        ids = self._selected_ids()
        if ids:
            self.vp.selection = ids
            self.vp.edge_selection, self.vp.point_selection, self.vp.seg_selection = [], [], []
            self.vp.duplicate("objects")

    def _delete(self):
        self.vp.delete_objects(self._selected_ids())

    def keyPressEvent(self, e):
        if self.state() != QAbstractItemView.EditingState:
            if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):  # Ctrl+D duplicate: menu of the main window
                return self._delete()
            # letter shortcuts (Alt+G group, Shift+G ungroup, H/Alt+H, Ctrl+G …) also apply when the focus
            # currently lies in the outliner (harbor test: Alt+G after a click in the outliner did nothing)
            if Qt.Key_A <= e.key() <= Qt.Key_Z and not (e.modifiers() & Qt.ControlModifier and e.key() == Qt.Key_A):
                vp = self.vp
                vp.setFocus()
                return vp.keyPressEvent(e)
        super().keyPressEvent(e)

    @staticmethod
    def _binds(obj):
        """Objects with a binding level for the brief: meshes, surfaces (without helper surfaces) and nulls."""
        return isinstance(obj, (MeshObject, NullObject)) or isinstance(obj, SurfaceObject) and not obj.aid

    def _binding_menu(self, oid):
        """Binding-level menu; if the object is selected, the choice applies to all selected (one undo step)."""
        obj = self.vp.scene.object_by_id(oid)
        menu = QMenu(self)
        choices = [(None, tr("Wie im Auftrag / Null darüber"))] + [(k, tr(label)) for k, (label, _t) in brief.TASK_LEVELS.items()]
        for k, (key, label) in enumerate(choices):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(obj.binding == key)
            act.setData(key)
            if k == 0:
                menu.addSeparator()
        chosen = menu.exec(QCursor.pos())
        if chosen is not None:
            ids = self._selected_ids()
            self.vp.set_binding(ids if oid in ids else [oid], chosen.data())
        self.vp.setFocus()

    def _material_menu(self, sid):
        """Click in the material column: menu of the materials (if the surface is selected, for all selected)."""
        surface = self.vp.scene.object_by_id(sid)
        if surface is None:
            return
        menu = QMenu(self)
        for key, name in theme.MATERIALS:
            act = menu.addAction(tr(name))
            act.setCheckable(True)
            act.setChecked(surface.material == key)
            act.setData(key)
        chosen = menu.exec(QCursor.pos())
        if chosen is not None:
            self._set_material(sid, chosen.data())
        self.vp.setFocus()

    def _material_box(self, surface):
        """Small dropdown: display material of the surface."""
        box = QComboBox()
        box.setFocusPolicy(Qt.NoFocus)
        for key, name in theme.MATERIALS:
            box.addItem(tr(name), key)
        box.setCurrentIndex(theme.MATERIAL_INDEX.get(surface.material, 0))
        box.setToolTip(tr("Material der Fläche (nur Darstellung) – gilt für alle gewählten Flächen, wenn diese dabei ist; Farbe: im Zeichenmodus F"))
        sid = surface.id
        box.currentIndexChanged.connect(lambda i, b=box: self._set_material(sid, b.itemData(i)))
        return box

    def _set_material(self, sid, key):
        """Material dropdown: if the surface is selected, all selected surfaces get the material (one undo step)."""
        ids = self._selected_ids()
        self.vp.set_surface_material(ids if sid in ids else [sid], key)

    def _surface_options(self, surface):
        """Options of a surface (expanded): helper surface, transparency (0 = opaque) and resolution of the net
        (×0.25 … ×4, middle ×1)."""
        box = QWidget()
        lay = QGridLayout(box)  # stacked: fits the narrow outliner
        lay.setContentsMargins(4, 0, 8, 2)
        lay.setHorizontalSpacing(6)
        lay.setVerticalSpacing(0)
        sid = surface.id

        def slider(tip, value, on_change):
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(value)
            sl.setFocusPolicy(Qt.NoFocus)
            sl.setToolTip(tip)
            sl.valueChanged.connect(on_change)
            return sl

        transp = slider(tr("Transparenz der Fläche (0 = deckend)"), round((1.0 - surface.opacity) * 100),
                        lambda v: self.vp.set_surface_opacity(sid, 1.0 - v / 100))
        res = slider(tr("Auflösung des Netzes: links ×0.25, Mitte ×1, rechts ×4 (die Form bleibt)"),
                     round((math.log(max(surface.resolution, 0.25)) / math.log(16) + 0.5) * 100),
                     lambda v: self.vp.set_surface_resolution(sid, 0.25 * 16 ** (v / 100)))
        aid = QCheckBox(tr("Hilfsfläche"))
        aid.setChecked(surface.aid)
        aid.setFocusPolicy(Qt.NoFocus)
        aid.setToolTip(tr("Nur noch Projektionsfläche zum Draufzeichnen (wie eine Hilfsebene): ohne Material, verdeckt nichts, mit den Zeichenhilfen ausgeblendet – eingefroren: folgt keiner Linie, nur das Gizmo bewegt sie (Doppelklick wählt sie)"))
        aid.toggled.connect(lambda on: self.vp.set_surface_aid(sid, on))
        lay.addWidget(aid, 0, 0, 1, 2)
        for row, (label, sl) in enumerate(((tr("Transparenz"), transp), (tr("Auflösung"), res)), start=1):
            text = QLabel(label)
            text.setToolTip(sl.toolTip())
            sl.setEnabled(not surface.aid or sl is res)
            lay.addWidget(text, row, 0)
            lay.addWidget(sl, row, 1)
        if surface.aid and surface.frozen:
            lay.addWidget(self._picture_options(surface), 3, 0, 1, 2)
        lay.setColumnStretch(1, 1)
        box.setMaximumWidth(max(self.viewport().width() - 2 * self.indentation(), 120))
        return box

    def _picture_options(self, obj):
        """Image on the helper plane/surface: checkbox Load image, below file, Project and Lock."""
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 0, 8, 2)
        lay.setSpacing(2)
        oid, pic = obj.id, obj.picture
        shown = bool(oid in self._picture_open or (pic and pic.get("on")))
        load = QCheckBox(tr("Bild laden"))
        load.setChecked(shown)
        load.setFocusPolicy(Qt.NoFocus)
        load.setToolTip(tr("Bild aus einer Richtung auf diese Fläche projizieren: zum Nachzeichnen und als Referenz"))
        lay.addWidget(load)
        row = QWidget()  # stacked: fits the narrow outliner
        column = QVBoxLayout(row)
        column.setContentsMargins(18, 0, 0, 0)
        column.setSpacing(2)
        rows = QHBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        file_btn = QPushButton(tr("Datei …") if not pic else tr("Andere Datei …"))
        file_btn.setFocusPolicy(Qt.NoFocus)
        file_btn.clicked.connect(lambda: self.vp.load_picture_dialog(oid))
        column.addWidget(file_btn)
        column.addLayout(rows)
        project = QPushButton("Project")
        project.setFocusPolicy(Qt.NoFocus)
        project.setToolTip(tr("Bild aus der jetzigen Kameraperspektive projizieren"))
        project.setEnabled(bool(pic) and not pic.get("locked"))
        project.clicked.connect(lambda: self.vp.project_picture(oid))
        rows.addWidget(project)
        lock = QCheckBox("Lock")
        lock.setFocusPolicy(Qt.NoFocus)
        lock.setToolTip(tr("Sperrt Project, damit das Bild nicht versehentlich verspringt"))
        lock.setChecked(bool(pic and pic.get("locked")))
        lock.setEnabled(bool(pic))
        lock.toggled.connect(lambda on: self.vp.set_picture_locked(oid, on))
        rows.addWidget(lock)
        lay.addWidget(row)
        row.setVisible(shown)  # attach first: visible without a parent it would briefly be its own window

        def toggled(on):
            (self._picture_open.add if on else self._picture_open.discard)(oid)
            row.setVisible(on)
            self.vp.set_picture_on(oid, on)
            self.scheduleDelayedItemsLayout()
        load.toggled.connect(toggled)
        box.setMaximumWidth(max(self.viewport().width() - 2 * self.indentation(), 120))
        return box

    def _null_options(self, null, row_item):
        """Settings of a generator. Selection fields and buttons act immediately (one undo step), numbers on
        confirm or arrow, sliders while dragging (combined)."""
        from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QPushButton, QSpinBox, QToolButton
        box = QWidget()
        lay = QGridLayout(box)
        lay.setContentsMargins(4, 0, 8, 2)
        lay.setHorizontalSpacing(6)
        lay.setVerticalSpacing(1)
        nid, prm, vp = null.id, null.params, self.vp
        rows = []

        def combo(items, current, key):
            c = QComboBox()
            c.setFocusPolicy(Qt.NoFocus)
            for value, text in items:
                c.addItem(text, value)
            c.setCurrentIndex(max(0, [v for v, _ in items].index(current)) if current in [v for v, _ in items] else 0)
            c.currentIndexChanged.connect(lambda i: vp.set_null_param(nid, key, c.itemData(i)))
            return c

        def number(value, key, lo, hi, step=1.0, decimals=2, integer=False, cast=None):
            s = QSpinBox() if integer else QDoubleSpinBox()
            if not integer:
                s.setDecimals(decimals)
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setValue(value)
            s.setKeyboardTracking(False)  # only on confirm, not on every digit
            s.valueChanged.connect(lambda v: vp.set_null_param(nid, key, cast(v) if cast else v, rebuild=False))
            return s

        def axes_toggles(key):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(2)
            for i, name in enumerate("XYZ"):
                cb = QToolButton()
                cb.setText(name)
                cb.setCheckable(True)
                cb.setFixedWidth(24)
                cb.setFocusPolicy(Qt.NoFocus)
                cb.setToolTip(tr("Achse {0} an/aus").format(name))
                cb.setChecked(bool(prm.get(key, [True] * 3)[i]))
                cb.toggled.connect(lambda on, i=i: vp.set_null_param(
                    nid, key, [on if k == i else bool(x) for k, x in enumerate(vp.scene.null_by_id(nid).params[key])]))
                h.addWidget(cb)
            h.addStretch(1)
            return w

        def amount(key, tip):
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(round(float(prm.get(key, 0.0)) * 100))
            sl.setFocusPolicy(Qt.NoFocus)
            sl.setToolTip(tip)
            sl.valueChanged.connect(lambda v: vp.set_null_param(nid, key, v / 100, rebuild=False))
            return sl

        if null.kind != "null":
            on = QPushButton("An" if prm.get("on", True) else tr("Aus"))
            on.setCheckable(True)
            on.setChecked(bool(prm.get("on", True)))
            on.setFocusPolicy(Qt.NoFocus)
            on.setToolTip(tr("Generator an/aus – aus: nichts geschnitten oder vervielfacht, der Inhalt bleibt, wie er ist"))
            on.clicked.connect(lambda checked: vp.set_null_param(nid, "on", bool(checked)))
            rows.append(("Generator", on))
        if null.kind == "symmetry":
            rows.append((tr("Ebene"), combo([("zy", "ZY (X)"), ("xz", "XZ (Y)"), ("xy", "XY (Z)")],
                                        prm.get("plane", "zy"), "plane")))
            side = QPushButton(tr("+ Seite") if prm.get("side", 1) >= 0 else tr("− Seite"))
            side.setFocusPolicy(Qt.NoFocus)
            side.setToolTip(tr("Welche Seite der Spiegelebene das Original zeigt (die andere ist die Spiegelung)"))
            side.clicked.connect(lambda: vp.set_null_param(
                nid, "side", -1 if vp.scene.null_by_id(nid).params.get("side", 1) >= 0 else 1))
            rows.append((tr("Behalten"), side))
        elif null.kind == "array":
            mode = prm.get("mode", "radial")
            rows.append((tr("Modus"), combo([("radial", tr("Kreis (um Y)")), ("linear", "Linear"),
                                         ("line", tr("Entlang Linie"))], mode, "mode")))
            rows.append((tr("Anzahl"), number(int(prm.get("count", 6)), "count", 1, 1000, 1, integer=True, cast=int)))
            if mode == "radial":
                rows.append((tr("Winkel °"), number(float(prm.get("angle", 360.0)), "angle", -3600, 3600, 15, 1)))
            elif mode == "linear":
                off = list(prm.get("offset", [1.0, 0.0, 0.0]))
                for i in range(3):
                    s = QDoubleSpinBox()
                    s.setDecimals(2)
                    s.setRange(-1000, 1000)
                    s.setSingleStep(0.1)
                    s.setValue(float(off[i]))
                    s.setKeyboardTracking(False)
                    s.setToolTip(tr("Versatz je Kopie entlang ") + "XYZ"[i] + tr(" des Nulls"))
                    s.valueChanged.connect(lambda v, i=i: vp.set_null_param(
                        nid, "offset", [v if k == i else float(x) for k, x in
                                        enumerate(vp.scene.null_by_id(nid).params["offset"])], rebuild=False))
                    rows.append((tr("Versatz ") + "XYZ"[i], s))
            else:
                for key, label in (("path", tr("Linie")), ("up", tr("Up-Linie"))):
                    curve = vp.scene.curve_by_id(prm.get(key)) if prm.get(key) is not None else None
                    b = QPushButton(("✓ " if curve is not None else "") + tr("aus Auswahl"))
                    b.setFocusPolicy(Qt.NoFocus)
                    b.setToolTip(tr("Gewählte Linie (Edit, Kantenmodus) übernehmen") +
                                 (tr(" – ohne Up-Linie wird die Y-Achse des Nulls mitgeführt") if key == "up" else ""))
                    b.clicked.connect(lambda _=False, key=key: vp.assign_array_line(nid, key))
                    rows.append((label, b))
            rows.append((tr("Drehung °"), number(float(prm.get("spin", 0.0)), "spin", -3600, 3600, 5, 1)))
            rows.append((tr("Zufall Dreh."), amount("rand_rot", tr("0 = keine, 1 = bis ±180° (Achsen darunter)"))))
            rows.append(("", axes_toggles("rot_axes")))
            rows.append((tr("Zufall Vers."), amount("rand_off", tr("0 = keiner, 1 = bis ± Größe des Inhalts (Achsen darunter)"))))
            rows.append(("", axes_toggles("off_axes")))
            rows.append(("Seed", number(int(prm.get("seed", 1)), "seed", 0, 99999, 1, integer=True, cast=int)))
        for row, (label, widget) in enumerate(rows):
            text = QLabel(label)
            text.setToolTip(widget.toolTip())
            lay.addWidget(text, row, 0)
            lay.addWidget(widget, row, 1)
        lay.setColumnStretch(1, 1)
        depth, it = 0, row_item
        while it.parent() is not None:  # indented as deep as the row stands in the tree
            depth, it = depth + 1, it.parent()
        box.setMaximumWidth(max(self.viewport().width() - (depth + 1) * self.indentation() - 4, 120))
        return box

    def _on_selection(self):
        if self._syncing:
            return
        self._from_outliner = True
        ids = [item.data(0, ID_ROLE) for item in self.selectedItems()]
        current = self.currentItem()
        if current is not None and current.isSelected() and current.data(0, ID_ROLE) in ids:
            cid = current.data(0, ID_ROLE)
            ids = [i for i in ids if i != cid] + [cid]  # last clicked becomes active
        self.vp.set_selection(ids)

    def _on_renamed(self, item, column):
        if self._syncing or column != 0 or item.data(0, ID_ROLE) is None:
            return
        self.vp.rename(item.data(0, ID_ROLE), item.text(0))
