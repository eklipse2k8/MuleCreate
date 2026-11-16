"""Read arrows in the note board: what does a painted stroke connect?

For every stroke in the board it checks what its ends lie on – a caption (text block), on an
image or in the empty. A stroke from a caption to an image is a connection "text → place in the image",
from one image to another "image → place in the image" (e.g. reference photo → screenshot); a closed stroke
(circle) or a stroke entirely on an image is a marking. Deliberately only in the board (2D): arrows often point
only in one direction – what exactly is meant, the AI reads from text and image (and otherwise clarifies it with the artist);
a seemingly exact 3D assignment would rather mislead.

Works on a QGraphicsScene of the board (note_board: the same elements as in the board), so that the board while
painting and the brief at export give the same answer.
"""
import math

END_REACH = 30.0  # a stroke end must lie this close (board units) to text/image to belong to it
MIN_LENGTH = 25.0  # shorter strokes (arrowheads, ticks) are not a connection
CLOSED_GAP = 0.25  # start and end this close (share of the length): closed marking (circle, frame)

def _rect_dist(r, p):
    dx = max(r.left() - p.x(), 0.0, p.x() - r.right())
    dy = max(r.top() - p.y(), 0.0, p.y() - r.bottom())
    return math.hypot(dx, dy)


def _nearest(gscene, p, kind, skip):
    """(distance, element) of the nearest element of kind kind at board point p (0: lies on it)."""
    best = (math.inf, None)
    for item in gscene.items():
        if item is not skip and isinstance(item, kind):
            d = _rect_dist(item.sceneBoundingRect(), p)
            if d < best[0]:
                best = (d, item)
    return best


def _length(pts):
    return sum(math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in zip(pts, pts[1:]))


def _uv(out):
    """Place of the tip in the target image (0..1, v from the top)."""
    from .note_board import ImageItem
    target = out["target"]
    if not isinstance(target, ImageItem):
        return
    local = target.mapFromScene(out["tip"])
    r = target.image_rect()
    if r.width() <= 0 or r.height() <= 0:
        return
    u, v = (local.x() - r.left()) / r.width(), (local.y() - r.top()) / r.height()
    out["uv"] = (min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0))


def stroke_link(gscene, stroke):
    """What a painted stroke in the board connects – dict:
      kind:   "link"  caption -> place (image or other text),
              "image" image -> place in another image (e.g. reference photo -> screenshot),
              "mark"  marking on an image (circle, stroke on it),
              "unclear" otherwise
      source: text or image at the start, target: element at the tip, tip: board point of the tip,
      uv: place in the target image (0..1)
    None: too short (arrowhead, tick)."""
    from PySide6.QtCore import QPointF

    from .note_board import ImageItem, TextBlock
    o = stroke.pos()
    pts = [p + o for p in stroke.pts]
    length = _length(pts)
    if len(pts) < 2 or length < MIN_LENGTH:
        return None
    a, b = pts[0], pts[-1]
    out = {"kind": "unclear", "source": None, "target": None, "tip": b, "uv": None}
    if math.hypot(b.x() - a.x(), b.y() - a.y()) < CLOSED_GAP * length:  # closed: marking around a place
        tip = QPointF(sum(p.x() for p in pts) / len(pts), sum(p.y() for p in pts) / len(pts))
        d, img = _nearest(gscene, tip, ImageItem, stroke)
        out.update(kind="mark", tip=tip, target=img if d == 0 else None)
        _uv(out)
        return out
    # source: the end that lies closer to a caption (arrows begin next to their text, often already above
    # the image); the tip at the other end belongs to the image it lies on, otherwise to the nearest element
    ta, tb = _nearest(gscene, a, TextBlock, stroke), _nearest(gscene, b, TextBlock, stroke)
    ia, ib = _nearest(gscene, a, ImageItem, stroke), _nearest(gscene, b, ImageItem, stroke)
    if min(ta[0], tb[0]) <= END_REACH:
        start_text = ta[0] <= tb[0]
        src, tip, tip_txt, tip_img = (ta[1], b, tb, ib) if start_text else (tb[1], a, ta, ia)
        target = tip_img[1] if tip_img[0] == 0 else tip_txt[1] if tip_txt[0] <= END_REACH else \
            tip_img[1] if tip_img[0] <= END_REACH else None
        out.update(kind="link", source=src, target=target, tip=tip)
    elif ia[0] == 0 and ib[0] == 0 and ia[1] is ib[1]:  # entirely on an image: place = middle of the stroke
        out.update(kind="mark", target=ia[1], tip=pts[len(pts) // 2])
    elif ia[0] <= END_REACH and ia[1] is ib[1]:  # both ends at the same image (one just beside it): marking
        out.update(kind="mark", target=ia[1], tip=pts[len(pts) // 2])
    elif ia[0] <= END_REACH and ib[0] <= END_REACH:  # image -> other image; tip: on a screenshot
        if ia[1].view and not ib[1].view:
            out.update(kind="image", source=ib[1], target=ia[1], tip=a)
        else:
            out.update(kind="image", source=ia[1], target=ib[1], tip=b)
    else:
        out.update(target=ib[1] if ib[0] <= END_REACH else ia[1] if ia[0] <= END_REACH else None)
    _uv(out)
    return out


def found(link):
    """Does the stroke connect anything? Connection with target or marking on an image – not: too short, unclear,
    arrow into the void, closed squiggle beside every image (letters, doodles)."""
    return link is not None and link["target"] is not None and link["kind"] in ("link", "image", "mark")


def label_of(text_item, n=28):
    """First line of a caption, shortened."""
    line = text_item.toPlainText().strip().split("\n")[0].strip()
    return line if len(line) <= n else line[:n - 1] + "…"


# --- Sections of a board ------------------------------------------------------------------------------

SECTION_GAP = 120.0  # texts/images whose frames are at most this far apart belong together


def sections(gscene, gap=SECTION_GAP):
    """Split the board into sections. A backdrop is a section (the artist said what belongs together;
    for nested ones the smallest counts); what lies in none is grouped by proximity: texts and images that
    lie close together belong together (by proximity only – long arrows across the board would otherwise turn everything into
    one giant section; they appear as connections in links). Strokes belong to the section of their target
    (otherwise their source). List of dicts (top to bottom, left to right): title (title of the backdrop or
    None), items (texts and images in reading order), links [(stroke, stroke_link)], rect."""
    from .note_board import BackdropItem, ImageItem, StrokeItem, TextBlock
    every = [i for i in gscene.items() if isinstance(i, ImageItem) or
             (isinstance(i, TextBlock) and i.toPlainText().strip())]
    drops = sorted((i for i in gscene.items() if isinstance(i, BackdropItem)),
                   key=lambda b: b.sceneBoundingRect().width() * b.sceneBoundingRect().height())
    owner = {}  # id(element) -> smallest backdrop in which its center lies
    for it in every:
        c = it.sceneBoundingRect().center()
        owner[id(it)] = next((b for b in drops if b.sceneBoundingRect().contains(c)), None)
    items = [it for it in every if owner[id(it)] is None]
    index = {id(it): k for k, it in enumerate(items)}
    parent = list(range(len(items)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        parent[find(a)] = find(b)

    rects = [it.sceneBoundingRect() for it in items]
    for i, ri in enumerate(rects):
        grown = ri.adjusted(-gap, -gap, gap, gap)
        for j in range(i + 1, len(rects)):
            if grown.intersects(rects[j]):
                union(i, j)
    links = []
    for s in gscene.items():
        if isinstance(s, StrokeItem):
            link = stroke_link(gscene, s)
            if link is not None:
                links.append((s, link))
    groups = {}
    for k in range(len(items)):
        groups.setdefault(find(k), []).append(items[k])
    found = [(None, members) for members in groups.values()]
    found += [(b, [it for it in every if owner[id(it)] is b]) for b in drops]
    out = []
    for drop, members in found:
        mine = {id(it) for it in members}
        sec_links = [(s, l) for s, l in links
                     if id(l["target"]) in mine or (l["target"] is None and id(l["source"]) in mine)]
        if drop is not None and not members and not sec_links:
            continue  # empty backdrop
        rect = drop.sceneBoundingRect() if drop is not None else members[0].sceneBoundingRect()
        for it in members:
            rect = rect.united(it.sceneBoundingRect())
        for s, _ in sec_links:
            rect = rect.united(s.sceneBoundingRect())
        out.append({"title": drop.title.toPlainText().strip() or None if drop is not None else None,
                    "items": sorted(members, key=_reading_key), "links": sec_links, "rect": rect})
    return sorted(out, key=lambda sec: _reading_key_rect(sec["rect"]))


ROW = 120.0  # reading order: what starts this close above each other is in one row (then left to right)


def _reading_key_rect(r):
    return (round(r.top() / ROW), r.left())


def _reading_key(item):
    return _reading_key_rect(item.sceneBoundingRect())
