# Package changes – what a running project must take over
Mule copies a newer package into a running brief with the next review round. The review round's `review.md` quotes the sections newer than the project's old version. Format: one section per version, newest first, `## v<major>.<minor>`.

## v5.0
Consolidation after an independent review – no new rules; the same substance in fewer words (rules.md 2360 → about 1800 words), with the rule numbers kept.
- **Rule 4 is now one order for everyone:** the artist's newest word > approved as built > drawn form within tolerance > construction and fit > measured numbers. Departures, the design hand-over and the veto list sit there. Replaces the scattered sentences of v4.11–v4.14 in rules 4, 6, 10 and 11.
- **Contradictions resolved:** a declared `DEPART:` is not a veto (it goes to the artist); colliding words of the artist are asked once, quoting both; open design that is not handed over gets the quietest form and variants at the next showing, while the stand-in only decides taste that changes nothing the sketch shows; after two QC rounds a failure against the artist's words or drawing is never closed – it heads the artist's list (also in the done criteria).
- **One list instead of two:** every instruction and approval of the artist is a work line (`artist_said.md` from v4.13 is gone). The referee checks each artist message since the last referee against its work line (quote right, no added option) and lists every `DEPART:`.
- **Moved out of rules.md:** the engineer's proof mechanism (→ engineer.md), the component procedure and lanes/packages/interfaces (→ conductor.md).
- **More general:** method list for organic forms, terrain and vegetation; „main structure“ instead of „main mechanics“ in the tiers; no vehicle traces in the overlay README; a short glossary on top of the rules.
- *Take over:* merge an existing `artist_said.md` into the work list; nothing else changes in the work.

## v4.14
- **Rule 10 – design follows the hand-over:** design is free and should be bold where the artist hands it over (the task or a note asks for design, e.g. a monster from a stick figure, a house on a footprint) – what is drawn still binds. Open but not handed over: quietest form in the language of the drawing, variants to the artist. Replaces the blanket „construction boldly, design never“ of v4.12. *Take over:* add to key `tolerance` in `readings.md` which parts, if any, the artist handed over for design.

## v4.13
- **Rule 10 – approved as built is binding:** what the artist approved in its built form („great“, „keep“) stays, also where it departs from the sketch; no later check or overlay pulls it back. *Take over:* find such approvals in `artist.log`, mark them in the overlay configs as `ignore`, and restore parts that were changed after the approval (ask the artist with before/after pictures).
- **Conductor – „artist said → status“:** `review/artist_said.md` lists every instruction and approval verbatim with its work line or decision; checked before every sheet. Visible faults put off under rule 15 go to the top of the artist list. *Take over:* build the list once from `artist.log`.

## v4.12
- **Rule 5 – the artist's words verbatim:** every work line carries the artist's own words and picture or mark; the main chat's reading stands below, marked as its own. An option or way out that is not in the artist's words is a departure. *Take over:* check the open work lines for paraphrases that add options and rewrite them.
- **Rule 5 – a new principle applies backwards:** a new principle from the artist is checked against `decisions.md`, `assumed.md` and the open work lines before the next build; every older reading that contradicts it becomes a work line. *Take over:* run this sweep once for the principles the artist has set so far.
- **Rule 6 – default while a question is open:** the option closest to the drawing, never the fit solution that already stands.
- **Rule 10 – construction boldly, design never** (refined in v4.14: design is free where the artist hands it over): builders solve how parts are made, joined and carried; where parts sit, how shapes run and relate is the artist's. Open design gets the quietest form in the language of the drawing; anything that changes how the sketch reads goes to the artist as a picture with variants.
- **Rule 4 / engineer – no check rewards hidden fit:** intersections, contacts and gaps count only where the cameras of the level see them; no adopted check may block on hidden ones. *Take over:* change any adopted inside or intersection test so hidden hits are noted, not blocking (`adopted.md`).
- **QC – intent across units:** a result that meets a work line's wording but misses the artist's intent fails (severity 3), also when the cause lies in another unit.
- **tools/sketch_overlay:** turns files whose up axis did not carry over; maps marks drawn on an imported copy of the build back onto the build (mirrored copies of those marks left out); a finding counts when an ortho view or two views agree.

## v4.11
- **Rule 10 – form binds, construction is free; tolerance per line:** precise lines within ~3 % of their own length, direction ~10°, curves stay curves; gestures ~10 %; route lines by their ends and order. Without a binding the kind of mark decides – `basis` only for what the artist calls a placeholder. *Take over:* key `tolerance` in `readings.md` (the hooks ask for it at study and final).
- **Rule 11 – a measurable goal never wins over one without:** fit is found within the form tolerance; otherwise it is a departure.
- **Rule 6 – a reading is not a departure:** building other than what is clearly drawn is `DEPART:`, approved only by the artist – never `ASSUMED`, never the stand-in. *Take over:* check `assumed.md` for entries that are departures and list them for the artist.
- **Veto:** a drawn line visibly beyond its tolerance; a dent, fold or stretched area on a tier-A surface whose reference is smooth.
- **tools/sketch_overlay** (new): the artist's strokes over the build, line by line, in the hero cameras and three orthographic views. Builders run it before publishing a changed form, QC at every check.

## v4.10
- **Engineer:** `WAIT: no run since adoption` for proposals that could not be measured yet; KEEP only after measuring.

## v4.9
- **Review rounds:** the artist's review of a running run comes as `review_rounds/review_NN_<date>/` in the brief folder – taken into the running work, not a new run.
