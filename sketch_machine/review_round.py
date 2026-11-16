"""Review rounds (2026-11-15): a brief export "builds on <brief folder>" is not a new run, but feedback
for the running chat – like a stack of screenshots handed to it. Mule puts it without a folder prompt into
<brief folder>/review_rounds/review_NN_<date>/: no new brief and no working folder, but review.md with only
what changed in the notes since the last export (new, changed, deleted), plus the current state
for reference (scene.usd, views/, notes/, brief.json). It is compared with the brief.json of the last round or of the
brief; notes via their fixed identifier (uid), older exports without uid via the heading. If the package in the
brief folder is older than the one from Mule, the round brings the new one along (brief_v4.update_package) and review.md says what changed
in the rules (2026-11-16)."""
import datetime
import json
import os
import re

ROUNDS_DIR = "review_rounds"
ROUND_FILE = "review.md"
_ROUND_RE = re.compile(r"^review_(\d+)(_|$)")
PART_LISTS = ("objects", "surfaces", "meshes", "hierarchy")  # named parts (identifiers can shift)


def base_of(folder):
    """Brief folder that is built on (even if a round inside it was chosen)."""
    folder = os.path.abspath(os.path.normpath(folder))
    if _ROUND_RE.match(os.path.basename(folder)) and os.path.basename(os.path.dirname(folder)) == ROUNDS_DIR:
        return os.path.dirname(os.path.dirname(folder))
    if os.path.basename(folder) == ROUNDS_DIR:
        return os.path.dirname(folder)
    return folder


def is_brief(folder):
    return bool(folder) and os.path.isfile(os.path.join(base_of(folder), "brief.json"))


def rounds(base):
    """[(number, folder)] of the rounds of a brief, ascending."""
    d = os.path.join(base_of(base), ROUNDS_DIR)
    if not os.path.isdir(d):
        return []
    out = []
    for name in os.listdir(d):
        m = _ROUND_RE.match(name)
        if m and os.path.isdir(os.path.join(d, name)):
            out.append((int(m.group(1)), os.path.join(d, name)))
    return sorted(out)


def next_folder(base, today=None):
    """Folder of the next round (only created at export)."""
    base = base_of(base)
    n = (rounds(base)[-1][0] if rounds(base) else 0) + 1
    day = (today or datetime.date.today()).isoformat()
    return os.path.join(base, ROUNDS_DIR, f"review_{n:02d}_{day}")


def round_number(folder):
    m = _ROUND_RE.match(os.path.basename(folder))
    return int(m.group(1)) if m else 0


def previous(base, skip=None):
    """(brief.json of the last export: last round, otherwise the brief, folder) or (None, None). skip: not this round
    (it is being written right now)."""
    base = base_of(base)
    for _, f in reversed(rounds(base)):
        if skip and os.path.abspath(f) == os.path.abspath(skip):
            continue
        data = _load(f)
        if data is not None:
            return data, f
    data = _load(base)
    return (data, base) if data is not None else (None, None)


def _load(folder):
    try:
        with open(os.path.join(folder, "brief.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# --- Comparison ------------------------------------------------------------------------------------------------------
def _targets(note):
    out = []
    for a in note.get("anchors", []):
        t = a.get("target")
        if t:
            out.append(f"{t.get('name', '')} ({t.get('path') or t.get('id', '')})")
    return out


def _sig(note):
    return {"title": note.get("title", ""), "text": list(note.get("text", [])),
            "images": [os.path.basename(i) for i in note.get("images", [])], "targets": _targets(note),
            "drawings": int(note.get("drawings", 0) or 0), "draft": bool(note.get("review_draft"))}


def _match(prev_notes, cur_notes):
    """[(old or None, new)] + leftover old ones. First via uid, then via the heading."""
    pairs, left = [], list(prev_notes)
    by_uid = {}
    for p in left:
        if p.get("uid"):
            by_uid.setdefault(p["uid"], []).append(p)
    rest = []
    for c in cur_notes:
        hit = by_uid.get(c.get("uid"), [])
        if c.get("uid") and len(hit) == 1 and hit[0] in left:
            left.remove(hit[0])
            pairs.append((hit[0], c))
        else:
            rest.append(c)
    for c in rest:
        hit = next((p for p in left if p.get("title") == c.get("title")
                    and not (p.get("uid") and c.get("uid") and p["uid"] != c["uid"])), None)
        if hit is not None:
            left.remove(hit)
        pairs.append((hit, c))
    order = {id(c): k for k, c in enumerate(cur_notes)}
    pairs.sort(key=lambda pc: order[id(pc[1])])
    return pairs, left


def _changes(old, new):
    """What changed in a note -> dict (empty: nothing)."""
    a, b = _sig(old), _sig(new)
    out = {}
    if a["title"] != b["title"]:
        out["title_was"] = a["title"]
    added = [t for t in b["text"] if t not in a["text"]]
    removed = [t for t in a["text"] if t not in b["text"]]
    if added:
        out["text_added"] = added
    if removed:
        out["text_removed"] = removed
    imgs_new = [i for i in b["images"] if i not in a["images"]]
    imgs_gone = [i for i in a["images"] if i not in b["images"]]
    if imgs_new:
        out["images_added"] = imgs_new
    if imgs_gone:
        out["images_removed"] = imgs_gone
    if a["targets"] != b["targets"]:
        out["targets_were"] = a["targets"]
    if a["drawings"] != b["drawings"]:
        out["drawings"] = (a["drawings"], b["drawings"])
    if a["draft"] and not b["draft"]:
        out["confirmed"] = True
    return out


def _renames(prev, cur):
    """Parts whose identifier shifted since the last export: [(old, new, name)] – only unambiguous names."""
    def names(data):
        seen, out = {}, {}
        for lst in PART_LISTS:
            for e in data.get(lst, []) or []:
                if isinstance(e, dict) and e.get("name") and e.get("id"):
                    key = (lst, e["name"])
                    seen[key] = seen.get(key, 0) + 1
                    out[key] = e["id"]
        return {k: v for k, v in out.items() if seen[k] == 1}
    a, b = names(prev), names(cur)
    return [(a[k], b[k], k[1]) for k in b if k in a and a[k] != b[k]]


def delta(prev, cur):
    """Difference between two brief.json states: new, changed, deleted notes, project note, shifted identifiers,
    changed export hints."""
    prev = prev or {}
    pairs, gone = _match(prev.get("notes", []), cur.get("notes", []))
    out = {"new": [], "changed": [], "same": [], "removed": gone}
    for old, new in pairs:
        if old is None:
            out["new"].append(new)
            continue
        ch = _changes(old, new)
        (out["changed"] if ch else out["same"]).append((new, ch) if ch else new)
    pa, pb = prev.get("project_note") or {}, cur.get("project_note") or {}
    out["project"] = _changes(pa, pb) if pa or pb else {}
    out["renames"] = _renames(prev, cur)
    ta, tb = prev.get("task") or {}, cur.get("task") or {}
    out["task"] = {k: tb[k] for k in ("task", "notes") if tb.get(k) and tb.get(k) != ta.get(k)}
    return out


# --- review.md -----------------------------------------------------------------------------------------------------
def _quote(text):
    return "\n".join("> " + line if line.strip() else ">" for line in text.strip().splitlines())


def _pictures(note):
    """Images of a note as lines: screenshot with camera or reference image with caption."""
    shots = {s["image"]: s for s in note.get("screenshots", [])}
    caps = note.get("captions", {})
    out = []
    for img in dict.fromkeys(note.get("images", [])):  # the same image twice on the board: mention it once
        if img in shots:
            cam = shots[img]["camera"]
            out.append(f"  - `{img}` – screenshot of the sketch (camera eye {cam['eye']}, target {cam['target']}, "
                       f"{cam['projection']})")
        else:
            out.append(f"  - `{img}` – reference picture" + (f": „{caps[img]}“" if img in caps else ""))
    return out


def _anchor_lines(note):
    out = []
    for a in note.get("anchors", []):
        t = a.get("target")
        if t:
            out.append(f"{t['id']} „{t.get('name', '')}“" + (f" ({t['path']})" if t.get("path") else "")
                       + (f", line {a['line']}" if a.get("line") else ""))
    return out


def _note_block(note, ch=None):
    lines = [f"### {note['id']} „{note.get('title', '')}“"]
    if note.get("review_draft"):
        lines.append("- **Draft from a review recording** – the artist has not confirmed it yet in Mule; treat it as "
                     "a proposal, ask before you act on anything it alone decides.")
    anchors = _anchor_lines(note)
    if anchors:
        lines.append("- Points at: " + "; ".join(anchors))
    if ch is None:  # new: everything
        for t in note.get("text", []):
            lines += ["", _quote(t)]
        if note.get("images"):
            lines += ["", "- Pictures:"] + _pictures(note)
    else:
        if ch.get("title_was") is not None:
            lines.append(f"- Title was „{ch['title_was']}“")
        if ch.get("confirmed"):
            lines.append("- Was a review draft – the artist has confirmed it since.")
        if ch.get("targets_were") is not None:
            lines.append("- Pointed before at: " + ("; ".join(ch["targets_were"]) or "nothing"))
        for t in ch.get("text_added", []):
            lines += ["", "New text:", "", _quote(t)]
        for t in ch.get("text_removed", []):
            lines += ["", "Text no longer on the board (removed or rewritten – what was established from it holds "
                      "unless the new text says otherwise):", "", _quote(t)]
        if ch.get("images_added"):
            new = {os.path.basename(i) for i in ch["images_added"]}
            shown = [ln for img, ln in zip(dict.fromkeys(note.get("images", [])), _pictures(note))
                     if os.path.basename(img) in new]
            lines += ["", "- New pictures:"] + shown
        if ch.get("images_removed"):
            lines.append("- Pictures removed: " + ", ".join(f"`{i}`" for i in ch["images_removed"]))
        if ch.get("drawings"):
            lines.append(f"- Drawing on the board changed ({ch['drawings'][0]} → {ch['drawings'][1]} strokes) – "
                         "look at the whole board.")
    if note.get("board"):
        lines.append(f"- Whole board: `{note['board']}`"
                     + (" – sections: " + ", ".join(f"`{s['image']}`" for s in note.get("sections", []))
                        if note.get("sections") else ""))
    return lines


def _package_block(pkg):
    """Section for a newer package brought along (brief_v4.update_package)."""
    from . import brief_v4
    return ["", f"## The rules were updated: package {pkg['old']} → {pkg['new']}",
            "Mule copied a newer package into the brief folder with this round: `rules.md`, `levels.md`, "
            "`conductor.md`, `roles/`, the agent types and hooks in `.claude/`, and the tools in the work folder. "
            "The run's settings (`gate.conf`, `gate.local.conf`, level), the work folder and everything established "
            "stay. **The new rules hold from now on, also for the work already done:**",
            "1. Read `rules.md`, `levels.md` and `conductor.md` again now, and the role files of the agents you start.",
            "2. Apply the changes below backwards before the next build: check `decisions.md`, `readings.md`, "
            "`assumed.md` and the open work lines against them; every older reading or built part that contradicts "
            "them becomes a work line (rule 5). Tell the artist in a few lines what changes for the running work.",
            "3. Settle what the hooks now ask for (for example a new first-round key) before the next builder.", "",
            brief_v4.changes_since(pkg["old"] if pkg["old"] != "unknown" else "")]


def markdown(d, cur, scene_name, folder, base, prev_folder, pkg=None):
    n = round_number(folder)
    rel_prev = os.path.relpath(prev_folder, folder).replace(os.sep, "/") if prev_folder else None
    md = [f"# Review round {n} – {scene_name}", "",
          f"Written by Mule on {datetime.date.today().isoformat()}. **This is not a new brief and not a new run.** It "
          f"continues the run of the brief two folders up (`{base.replace(os.sep, '/')}`). Everything established "
          "there stays as it is – " + ("level, decisions, readings, units, bauwissen, the clarified points, the way "
                                        "you work with the artist; only the rules were updated (section below). "
                                        if pkg else
                                        "rules, roles, hooks, level, decisions, readings, units, bauwissen, the "
                                        "clarified points, the way you work with the artist. ")
          + "This folder adds the artist's review: take it like a big stack of screenshots and comments the artist "
          "drops into the chat.", "",
          "## How to take it in",
          "1. Read this file completely and open every picture it names, the whole boards included.",
          "2. Fit the review into the running work: what it changes in decisions, readings, units and the work list. "
          "Where a note here contradicts something established, the note wins – list each case in your answer "
          "(established · now · source).",
          "3. Ask only what this review leaves open, each question with a picture where the spot is marked – the "
          "artist may answer by exception.",
          "4. Then go on with the work as before" + (" under the updated rules. " if pkg else
                                                      ": same rules, same level, same hooks. ")
          + "Nothing here asks you to start over.", "",
          f"Compared with the last export (`{rel_prev}`)." if rel_prev else
          "Mule found no earlier export to compare with – every note below counts as new.",
          "Ids (N#, S#, F#, M#, H#, L#) follow **this round's** `brief.json`; they can shift between exports – "
          "names and paths stay."]
    if pkg:
        md += _package_block(pkg)
    if d["renames"]:
        md += ["", "Parts whose id moved since the last export:", "", "| was | now | name |", "|---|---|---|"]
        md += [f"| {a} | {b} | {name} |" for a, b, name in d["renames"]]
    if d["task"]:
        md += ["", "## The artist's words for this round"]
        if d["task"].get("task"):
            md += ["", f"Goal: {d['task']['task']}"]
        if d["task"].get("notes"):
            md += ["", _quote(d["task"]["notes"])]
    if not (d["new"] or d["changed"] or d["removed"] or d["project"]):
        md += ["", "## No changed notes",
               "The notes are the same as in the last export. Look at the current state below (the geometry may "
               "have changed) and ask the artist what this round is about."]
    if d["new"]:
        md += ["", f"## New notes ({len(d['new'])})"]
        for note in d["new"]:
            md += [""] + _note_block(note)
    if d["changed"]:
        md += ["", f"## Changed notes ({len(d['changed'])})"]
        for note, ch in d["changed"]:
            md += [""] + _note_block(note, ch)
    if d["removed"]:
        md += ["", f"## Notes no longer in the scene ({len(d['removed'])})",
               "Deleted or rewritten under a new title. This revokes nothing: what was established from them – "
               "decisions, readings, built parts – holds unless a note of this round says otherwise."]
        md += [f"- „{p.get('title', '')}“ (was {p.get('id', '?')})" for p in d["removed"]]
    if d["project"]:
        md += ["", "## Project note (whole project, changed)"]
        md += _note_block({**(cur.get("project_note") or {}), "id": "Project"}, d["project"])[1:]
    md += ["", "## Current state, for looking things up",
           "- `scene.usd` – the whole sketch as it is now.",
           "- `views/` – overview pictures and hero cameras of the current state.",
           "- `brief.json` – full data of the current state (all notes, parts, cameras).",
           "- `notes/` – all note pictures and whole boards."]
    if d["same"]:
        md.append("- Unchanged since the last export: " + ", ".join(f"{s['id']} „{s.get('title', '')}“"
                                                                    for s in d["same"]) + ".")
    return "\n".join(md) + "\n"


def write(cur, folder, scene_name):
    """Write review.md into the round (cur: brief.json data of this round); an older package in the brief folder is
    renewed in the process (brief_v4.update_package, 2026-11-16). -> file name."""
    from . import brief_v4
    base = base_of(folder)
    prev, prev_folder = previous(base, skip=folder)
    d = delta(prev, cur)
    pkg = brief_v4.update_package(base, scene_name)
    with open(os.path.join(folder, ROUND_FILE), "w", encoding="utf-8") as fh:
        fh.write(markdown(d, cur, scene_name, folder, base, prev_folder, pkg))
    return ROUND_FILE
