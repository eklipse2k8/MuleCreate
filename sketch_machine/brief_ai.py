"""Clarified with the artist: summary and answers the AI confirmed with the artist (MCP write_clarified) are merged
into the scene and written into the brief as their own section; what no longer applies goes to clarified_history.md.
The check never changes notes or settings - it only adds structure.

(Until v0.99.78 an automatic AI check over the Anthropic API also lived here; removed in v0.99.248 - the first round
in the chat does the same over the subscription.)"""
import json
import os

SECTION = "## Clarified with the artist before export"
HISTORY_FILE = "clarified_history.md"  # what no longer applies (replaced, done) - outside the core


def merge_clarified(old, summary="", answers=(), drop=()):
    """Add what was clarified instead of replacing: new answers are added, the same question (case ignored)
    gets the new answer, drop removes questions that no longer apply (also done corrections of a round);
    a new summary replaces the old one, empty: the old one stays. What was replaced and removed moves into the
    history ("Applies now" stays short, nothing is lost).
    old/result: {"summary", "answers": [{"question", "answer"}], "history": [{"question", "answer"}] (only if present)}."""
    old = old or {}
    key = lambda q: " ".join(q.lower().split())
    gone = {key(q) for q in drop}
    history = list(old.get("history", []))
    merged = {}
    for a in old.get("answers", []):
        if key(a["question"]) in gone:
            history.append(a)
        else:
            merged[key(a["question"])] = a
    for q, a in answers:
        if a and a.strip() and key(q) not in gone:
            prev = merged.get(key(q))
            if prev and prev["answer"] != a.strip():
                history.append(prev)
            merged[key(q)] = {"question": q.strip(), "answer": a.strip()}
    if summary.strip() and old.get("summary") and old["summary"] != summary.strip():
        history.append({"question": "Earlier summary", "answer": old["summary"]})
    out = {"summary": summary.strip() or old.get("summary", ""), "answers": list(merged.values())}
    if history:
        out["history"] = history
    return out if out["summary"] or out["answers"] or history else {}


def write_clarified(folder, summary, answers, json_too=True, history=()):
    """Write the confirmed summary and clarified questions into the brief - right after the core, before the
    reference material, at the end of core.md (read again at the start of each session) and into brief.json under
    "clarified". answers: [(question, answer | "decide" | None)]; None = ignored. history: [(question, answer)], what
    no longer applies - only as a pointer in the brief, in full in HISTORY_FILE.
    The section is rewritten completely each time; without content it is dropped."""
    from . import brief
    asked = [(q, a) for q, a in answers if a]
    history = [(q, a) for q, a in history if a]
    empty = not summary.strip() and not asked
    lines = [] if empty else [SECTION, "The artist went through a first reading of this brief before export. This section is "
             "authoritative where it is more specific than the rest.", ""]
    if summary.strip() and lines:
        lines += ["**Summary (confirmed by the artist):**", *[f"> {l}" if l.strip() else ">"
                                                               for l in summary.strip().splitlines()], ""]
    for q, a in asked:
        lines.append(f"- {q} → " + ("the artist leaves this to you: decide, and say what you decided."
                                     if a == "decide" else a.strip()))
    if history and lines:
        lines += ["", f"Earlier answers that no longer apply (replaced, or for a finished round): `{HISTORY_FILE}` "
                  f"({len(history)}) – only when you need to know why something changed; above is what applies now."]
    if lines:
        lines.append("")
    hpath = os.path.join(folder, HISTORY_FILE)
    if history:
        with open(hpath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(["# Clarified earlier – no longer applies", "",
                                "Oldest first. What applies now is in brief.md and core.md under "
                                f"„{SECTION[3:]}“.", "", *[f"- {q} → {a}" for q, a in history]]) + "\n")
    elif os.path.isfile(hpath):
        os.remove(hpath)
    path = os.path.join(folder, "brief.md")
    with open(path, encoding="utf-8") as fh:
        md = fh.read().splitlines()
    if SECTION in md:  # replace up to the next section or the introduction
        start = md.index(SECTION)
        end = next((k for k in range(start + 1, len(md)) if md[k].startswith("## ") or
                    md[k].startswith("This brief was exported") or md[k].startswith("**This brief has a focus")),
                   len(md))
        md[start:end] = []
    # after the core, before the reference material (older briefs: before the introduction)
    at = next((k for k, l in enumerate(md) if l == brief.READ_SECTION or l.startswith("This brief was exported") or
               l.startswith("**This brief has a focus")), 2)
    md[at:at] = lines
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    cpath = os.path.join(folder, brief.CORE_FILE)
    if os.path.isfile(cpath):
        with open(cpath, encoding="utf-8") as fh:
            core = fh.read().splitlines()
        if SECTION in core:
            core = core[:core.index(SECTION)]
        while core and not core[-1].strip():
            core.pop()
        with open(cpath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(core + ([""] + lines if lines else [])).rstrip("\n") + "\n")
    jpath = os.path.join(folder, "brief.json")
    if json_too and os.path.isfile(jpath):
        with open(jpath, encoding="utf-8") as fh:
            data = json.load(fh)
        data["clarified"] = {"summary": summary.strip(),
                             "answers": [{"question": q, "answer": a} for q, a in asked]}
        if history:
            data["clarified"]["history"] = [{"question": q, "answer": a} for q, a in history]
        if empty:
            data.pop("clarified")
        with open(jpath, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
    return not empty
