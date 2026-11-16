"""Viewport layout as in Houdini: split viewports left/right or top/bottom, close,
temporarily maximize one (Space + F). All viewports share one workspace,
each has its own camera.

The layout is a tree of QSplitters; the root is always a splitter.
"""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from .viewport import Viewport

SPLIT_HALF = 10000  # Splitters distribute sizes proportionally: two equal values = half-half


def _camera_dict(cam):
    return {"target": cam.target.tolist(), "dist": cam.dist, "rot": cam.rot.tolist(), "ortho": cam.ortho}


def _apply_camera(cam, data):
    cam.set_state(np.array(data["target"], float), float(data["dist"]), np.array(data["rot"], float))
    cam.ortho = bool(data.get("ortho", False))


class ViewArea(QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.ws = workspace
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.root = QSplitter(Qt.Horizontal)
        layout.addWidget(self.root)
        self._hidden = []  # widgets hidden while maximized
        self.root.addWidget(self._new_viewport())

    def _new_viewport(self, like=None):
        vp = Viewport(self.ws)
        vp.area = self
        if like is not None:  # the new view starts with the same camera
            vp.cam.set_state(*like.cam.state())
            vp.cam.ortho = like.cam.ortho
        return vp

    def viewports(self):
        return [v for v in self.ws.viewports if v.area is self]

    def count(self):
        return len(self.viewports())

    # --- Split / close ---
    def split(self, vp, orientation):
        """Split vp: a new viewport next to it (Qt.Horizontal) or below it (Qt.Vertical)."""
        self.restore()
        parent = vp.parentWidget()
        new = self._new_viewport(like=vp)
        idx = parent.indexOf(vp)
        sizes = parent.sizes()
        if parent.count() == 1:
            parent.setOrientation(orientation)
        if parent.orientation() == orientation:
            parent.insertWidget(idx + 1, new)
            half = sizes[idx] // 2
            parent.setSizes(sizes[:idx] + [sizes[idx] - half, half] + sizes[idx + 1:])
        else:
            # Across the previous direction: vp and the new viewport go into a splitter of their own.
            # Insert the splitter first, then pull vp into it – so the GL widget never leaves the window.
            box = QSplitter(orientation)
            parent.insertWidget(idx, box)
            box.addWidget(vp)
            box.addWidget(new)
            box.setSizes([SPLIT_HALF, SPLIT_HALF])
            parent.setSizes(sizes)
        new.show()
        new.setFocus()
        return new

    def close_viewport(self, vp):
        if self.count() <= 1:
            return
        self.restore()
        parent = vp.parentWidget()
        self.ws.viewports.remove(vp)
        if self.ws.current is vp:
            self.ws.current = self.viewports()[0]
        vp.area = None
        vp.hide()
        vp.deleteLater()
        rest = [parent.widget(i) for i in range(parent.count()) if parent.widget(i) is not vp]
        if len(rest) == 1 and parent is not self.root:  # Dissolve a splitter with only one child left
            grand = parent.parentWidget()
            idx, sizes = grand.indexOf(parent), grand.sizes()
            grand.insertWidget(idx, rest[0])
            grand.setSizes(sizes)
            parent.hide()
            parent.deleteLater()
        self.ws.current.setFocus()
        self.ws.current.update()

    # --- Maximize (Space + F) ---
    def is_maximized(self):
        return bool(self._hidden)

    def toggle_maximize(self, vp):
        if self._hidden:
            self.restore()
            return
        w = vp
        while w is not self.root:
            parent = w.parentWidget()
            for i in range(parent.count()):
                sibling = parent.widget(i)
                if sibling is not w and sibling.isVisible():
                    sibling.hide()
                    self._hidden.append(sibling)
            w = parent
        vp.update()

    def restore(self):
        for w in self._hidden:
            w.show()
        self._hidden = []

    # --- Save / load (part of the scene file) ---
    def state(self):
        def node(w):
            if isinstance(w, QSplitter):
                return {"split": "h" if w.orientation() == Qt.Horizontal else "v", "sizes": w.sizes(),
                        "children": [node(w.widget(i)) for i in range(w.count())]}
            return {"camera": _camera_dict(w.cam)}
        return node(self.root)

    def set_state(self, data):
        """Restore layout and cameras from the scene file."""
        self.restore()
        for vp in self.viewports():
            self.ws.viewports.remove(vp)
            vp.area = None
        old = self.root
        self.root = QSplitter(Qt.Horizontal)
        self.layout().replaceWidget(old, self.root)
        old.hide()
        old.deleteLater()
        self.ws.current = None

        def build(d, splitter):
            if "camera" in d:
                vp = self._new_viewport()
                _apply_camera(vp.cam, d["camera"])
                splitter.addWidget(vp)
                return
            box = splitter if splitter.count() == 0 and splitter is self.root else QSplitter()
            box.setOrientation(Qt.Horizontal if d.get("split") == "h" else Qt.Vertical)
            if box is not splitter:
                splitter.addWidget(box)
            for child in d.get("children", []):
                build(child, box)
            if d.get("sizes"):
                box.setSizes(d["sizes"])

        build(data, self.root)
        if not self.viewports():
            self.root.addWidget(self._new_viewport())
        self.ws.current = self.viewports()[0]
        self.ws.current.setFocus()

    def set_single_camera(self, data):
        """Old scene files: one camera for the first viewport."""
        _apply_camera(self.viewports()[0].cam, data)
        self.ws.current.update()
