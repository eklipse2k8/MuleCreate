## Look images (before building)
Before you build anything, make a visual target with an image generator:
1. Write one strong image prompt per hero camera, built from this brief and its notes: what the object is (and what it is for, where that matters); its form, proportions and main parts as in the hero picture; materials, surfaces and colors; light, mood and background; the camera (angle as in the picture, lens feel); the style (e.g. photoreal product shot or concept art); one line on what to avoid. Nothing the brief does not support. Show the prompts to the artist and wait for an OK – if a camera already has an approved prompt below, use that one.
2. Generate 2–3 variants per camera, using the clean hero picture as structure input (image-to-image or reference image) so proportions and camera hold. Hero angles only – never orthographic views: generated front, side and top views do not agree with each other and must not be read as measurements.
3. Save them as `gen/<camera>_a.png`, `gen/<camera>_b.png` … next to this brief and let the artist pick. If you have no image tool, hand the prompts and pictures to the artist and wait for the images in `gen/`.
4. Build only after the artist picked. The picked images are orientation for look, detail distribution and shading, not something to copy: on conflict the sketch geometry wins over the notes, and the notes win over generated images.

Cameras for this step: every hero camera above – input `views/<camera>.png` → `gen/<camera>_a.png`, `gen/<camera>_b.png` …
{{#cameras}}
{{#prompt}}
- `{{id}}` – prompt approved by the artist (use it, no need to ask again): {{prompt}}
{{/prompt}}
{{/cameras}}
