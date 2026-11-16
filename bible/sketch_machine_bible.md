# Sketch Machine workflow bible

This public copy starts with technique and tool entries. How a build runs (roles, reviews, gates) is set by the way-of-working package in each brief, not here.

Workflows, checks and pitfalls from projects built from Sketch Machine briefs. AI models read it before planning a
work step and add to it at the end of each project.

## Protocol

1. **Own strategy first.** Before you read the entries for a step, write down your own best strategy. Then read the
   matching entries, compare and choose – and say why. An entry is a suggestion, not a rule: newer models and tools
   may know better ways, and trying a new way is part of the work.
2. **Weigh age and evidence.** Prefer entries that were confirmed often and recently; treat old or unconfirmed ones
   with care. An entry is not wrong because an older model wrote it – and not right because it is written here.
3. **Only what holds in general** – for kinds of objects, steps, tools or checks, never about one object
   ("pivots of hinged parts on existing meshes: …", not "the glider's wing hinge sits at …"). Failures count as
   much as successes.
4. **Rate from results, not from impression:** attempts until the reviewer accepted, the reviewer's verdict, the
   artist's verdict.
5. **Sign** every entry and every remark: model name, tools (with versions where known), date.
6. **When you used an entry,** add one line under it: confirmed or contradicted, signed, with one sentence why.
7. **Keep it short.** One entry per workflow, check or pitfall; extend an existing entry instead of writing a
   similar one. Never delete – mark an outdated entry "superseded by …, because …".

## Entry format

```

### <short title>
- Kind: workflow | check | pitfall
- Applies to: kind of object, step, tool (e.g. "organic surfaces, Houdini SOPs")
- What: the approach or check in a few lines
- Result: attempts until accepted, reviewer's verdict, artist's verdict
- Signed: <model>, <tools>, <date>
- Confirmed / contradicted: <one line each, signed>
```

## Entries

### Each part from function plus one chosen photo
- Kind: workflow
- Applies to: mechanical hard-surface parts built from a blockout, any tool
- What: Before building a part, state what it does and pick one clear photo reference; read the photo first and try to let it set main form and scale, not only details. Primary colours from the project palette, secondary ones from the photo. Then check the part from the hero camera, not only close up.
- Result: After several rounds of generic detail the first round built this way was called the best so far by the artist. One pilot on a single part gave only a local gain: for main forms the reviewer called the thesis neither confirmed nor refuted. The artist kept it as the method.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-01
- Confirmed / contradicted: Confirmed, Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02: in a second build, parts got purpose, carrier and photo in a parts list first; reviewers then closed console, valve group and tank mounts, but the artist has not judged them yet.

### Judge look under real light early
- Kind: check
- Applies to: review renders compared with photo-like target images
- What: Viewport or workbench shading has no sky light: undersides go dark and outline shading fakes seams. Tones tuned there are wrong later. Render early with a path tracer under a sky with a soft sun; here a few seconds per view on a scene of several million polygons. Keep the render's material values in one table, separate from the viewport colours. Check the scene for leftover lights first. Measure tones on small windows that lie on the surface; check that a window does not hit background or line work.
- Result: 16 review rounds were tuned on the viewport. The switch brought a large jump in the wide shots (reviewer), together with model changes in the same round. A forgotten 1000 W lamp burned out the first attempts, and two of the builder's measuring windows were wrong. Artist's verdict open.
- Signed: Claude Opus 5.5, Blender 5.2 Cycles, 2026-11-01
- Confirmed / contradicted: Confirmed, Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02: all gates were judged on path-traced images from the start, with no tone rework; not compared with viewport review in this run.

### Parts built from stale transforms sit at the origin unnoticed
- Kind: pitfall
- Applies to: Blender scripts that read matrix_world of hidden objects, headless or not
- What: Hidden objects can report an outdated matrix_world until the view layer updates. A detail pass built from it places everything around the world origin, often inside other geometry where no render shows it. Clear hide_viewport and call view_layer.update first. Check after each pass: the bounding box of each detail part must lie near its parent.
- Result: Doublers and bolts of a whole joint chain lay inside the fuselage, since when was not determined. Found only because a collision count grew with a motion it should not follow, and the reviewer refused the builder's reading of it.
- Signed: Claude Opus 5.5, Blender 5.2, 2026-11-01

### Collision tests: list what was tested, look at what grows
- Kind: check
- Applies to: rigged assemblies, any tool
- What: Export the moving groups per rig state and count overlaps in a BVH against the big static parts and each other, with mirrored copies across the centre line. Write the tested pairs into the result, not only the hits. Hits that change with the pose come first, but constant hits need clearing too: test the same pair in the original blockout and show them in an image. Test against the finished parts, not only base shapes. State what was not tested.
- Result: Led to the pitfall above: constant and growing hits both came from the same misplaced parts. Rails, membranes and panels of a folding rig came out free against body, other wings and the mirror over five states; parts within one wing, two axes and the mirrored side against the body stayed untested. The result file here named groups and a pair count, not each pair.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-01
- Confirmed / contradicted: Confirmed, Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02: the untested pairs inside one wing, named as open above, hid the known interference; the test reported none until those pairs were added.
- Confirmed, Claude Opus 5.5, Blender 5.2.3, Houdini 22.0.368, 2026-11-07: testing the blockout first showed a hinged bracket already inside the structure at rest; fixing that before modelling saved a rebuild. Houdini's Intersection Analysis was fast enough to run five states per build (6 s each on 0.5 M context faces after cropping the context to a box around the joint).

### Find the free envelope of a moving part with a proxy before modelling it
- Kind: workflow
- Applies to: hinged or swinging parts inside dense assemblies, Houdini SOPs plus any modeller
- What: When a part collides in rest or extreme states, do not model it and then trim. Build a parametric proxy of its outline (a Python SOP with a few numbers: plane, thickness, top and bottom edge), run the collision test in every state, and move the numbers until it is free. Then model the real part to those numbers and show the artist an outline overlay of the old and new shape with the reason.
- Result: Three proxy runs gave a free envelope for a bracket that swung through two structures; the modelled part needed no collision fix afterwards. Two reviewers accepted the reason, and both said the character was partly lost (a deep triangle became a slender frame). Artist's verdict open.
- Signed: Claude Opus 5.5, Blender 5.2.3, Houdini 22.0.368, 2026-11-07

### Intersection Analysis: do not trust sourceprim on merged inputs
- Kind: pitfall
- Applies to: Houdini 22 Intersection Analysis SOP, naming which parts collide
- What: The sourceprim values per intersection point did not match the primitive numbers of a merged second input, so names read from them were wrong (parts 15 m away). Cluster the intersection points and ask the input geometry for nearestPrim at one point per cluster. A Blast with an empty group deletes everything; use a pattern that matches nothing as the "off" state.
- Result: The first collision table named wrong parts; after the switch every hit pointed at a part that the image confirmed.
- Signed: Claude Opus 5.5, Houdini 22.0.368, 2026-11-07

### Reused procedural networks can hide a world-axis assumption
- Kind: pitfall
- Applies to: copying a working Houdini network to similar parts
- What: A network that works on one part may choose its input by world position (for example a Sort SOP by Y picks "the lower curve", or a perimeter sort picks an edge). On a sibling part in another position it silently does the opposite, without an error. Compare an intermediate attribute (here a direction vector) between the working and the new copy before tuning anything.
- Result: Folded membranes of two wings did not gather and reached across the centre line of the tail (measured minimum x below 0). One sort parameter fixed it after two wrong guesses at the input shape.
- Signed: Claude Opus 5.5, Houdini 22.0.368, 2026-11-01

### Even-offset inset can throw a corner off the surface
- Kind: pitfall
- Applies to: panel and plate generators on curved or faceted skins, Blender bmesh inset_region
- What: With even offset, sharp corners of a cell can shoot out along the normal, and a radial limit does not catch them. Test each inset vertex against a BVH of the original cell and fall back to no gap. Keep the removed inset faces as a dark seam on the surface, so plate edges read under real light without outline shading.
- Result: A 24 cm spike changed a silhouette and was first mistaken for blockout form. The seam faces made plates read as sheet in the path-traced renders (reviewer).
- Signed: Claude Opus 5.5, Blender 5.2, 2026-11-01

### Parameters of a reused asset can reach far outside the part
- Kind: pitfall
- Applies to: procedural line or hose assets placed on new parts, and geometry cached across sessions
- What: Check new instances from far away as well, against the silhouette. A clamp option written for one place drew an 8 m bar to the next structure. Find such parts by ray scanning the image region instead of guessing. Also compare primitive counts between the session and a fresh process: a USD stage already open in a session stays stale until it is reloaded.
- Result: The bar stood in the sky for four versions and was first blamed on other new tubes. The count comparison found stale wings that looked correct.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-01
- Confirmed / contradicted: Confirmed, Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02: a chamfer parameter on a generic panel recipe threw two strips 240 m away and scattered rivets. Ray picking named the object at once; guessing had cost one full build.

### Own kit of parts with ports, not separate dressing
- Kind: workflow
- Applies to: technical detail on hard-surface models, in code
- What: Keep one small library of parts in absolute sizes. Each part has a foot on a carrier and named ports; lines run only from port to port. Report unused ports. Choose carriers by function: on a list of technical carriers, parts cannot land on the outer skin. Stand a flat part on a curved surface only after checking that the surface is flat under it. A part with an unused port reads as decoration.
- Result: Reduced open ends of the lines in the port plan to zero, but the first placements brought regressions (blocks on the skin, tilted covers, hoses pressed through a window opening). Each was found on the control sheets. Reviewer still read the kit largely as boxes and cylinders; artist's verdict open.
- Signed: Claude Opus 5.5, Blender 5.2, 2026-11-01
- Confirmed / contradicted: Confirmed, Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02: lines inherited by a sibling part that landed on the nearest vertex instead of a port ran through its joints. Port blocks found by ray on the structure cut those overlaps by about 90 percent.

### Compare suspicious forms with the original source mesh
- Kind: check
- Applies to: anything built on a blockout through cuts, booleans or generators
- What: When a form looks odd, a ray test in the working file only shows what is there now. Import the original source and compare: for each vertex of the working mesh, measure the distance to the original. Clusters mark what the process added. Boolean cuts on non-closed meshes can leave material, and their new floors can pick up surface detail meant for the skin.
- Result: A box on the back was first called blockout and then given details; the same kind of mistake had already happened with a spike. The comparison placed it exactly on one failed cut. Removing that cut and marking cut floors by material also removed bright empty floors.
- Signed: Claude Opus 5.5, Blender 5.2, 2026-11-01
- Confirmed / contradicted: Confirmed, Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02: a plain box a reviewer wanted removed turned out to be part of the blockout, so it stayed and got a purpose. Checking generated panels against the source surface also found what a bounding box test missed.

### Sheet panels from a cage through blockout points
- Kind: workflow
- Applies to: hard-surface skins over a blockout, Blender bmesh with Solidify, Subsurf, Bevel
- What: Treat the blockout as a cage. Each panel is a quad patch in cage parameter space, evaluated by a Hermite surface through the points. Give edges support loops and real chamfers instead of creases. Use a real gap of a few millimetres with a dark strap below, an L-section stiffener with a rivet row at free edges, and a flange on framed cuts. Rivets follow the panel grid. No booleans or panelize on the raw blockout.
- Result: Reviewer rejected the pilot three times over facets on one keel; the artist called the panels fantastic from attempt two on and asked for all sheet parts in the same way. Checks: open edges and vertex distance to the source mesh.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Generic panel recipe on an unknown mesh needs a surface check afterwards
- Kind: pitfall
- Applies to: running a panel or strip generator automatically over many blockout faces
- What: Parameters sized for large panels can run out of a short or narrow strip and extrapolate far away. Measure every generated part after the modifiers against a BVH of the source surface, parts of merged rivet or edge objects per island. A bounding box test is too coarse on large or ring-shaped parts, and here it also removed good panels. Fall back to a plain thick sheet for strips that fail, and log them. Probe in the real build order: removing old parts from a finished file can give different results.
- Result: Two bars hung several metres below the model and rivets floated in the air. The first two fixes targeted the wrong cause; only the per-part surface check found two strips off by 240 m and restored panels the box test had deleted.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Solve a pose collision without damaging the rest pose
- Kind: check
- Applies to: folding or moving assemblies, any tool
- What: After removing an interference in the extreme pose, look at the rest pose from the main views first. Cutting back a part may clear the count and expose bare structure in the view that matters most. Consider a small moving part driven by the same control, so the rest pose keeps its outline. Show it in rest, mid and end pose.
- Result: A trimmed panel cleared most of a 555-pair overlap, but in the unfolded state left a gap and a bare arm. A hinged edge flap restored the outline and left 113 pairs, with the rest pose unchanged. The artist has not seen it yet.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Map each image finding to an object before fixing
- Kind: workflow
- Applies to: review findings given as image positions, any renderer with ray access
- What: Rebuild the review camera and cast rays through a small grid around the given position, skipping hidden helpers. List the first visible object and hit point. Then map hit points to generated lines or parts in the plan. Convert coordinates between tools first: a missed axis swap sent one search to the wrong lines.
- Result: Turned reviewer positions into named parts within one job: a hose reported outside the skin lay inside and showed through an opening, and a box reported as dressing was blockout. Each changed the fix.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Decide visible overlaps on images, with a filter only to prepare
- Kind: workflow
- Applies to: dense generated lines or hoses inside finished parts
- What: A count of overlaps says little about what is visible. Filter lines whose centre crosses a big part, then have a fresh reviewer list clear cases on images, map each position to a line by ray casting and remove that line. Include every big part in the filter and log how many lines it removes. A zero in that log means the filter may be broken, not that all is clean. Removing lines by a radius can take a whole bundle, so check the count afterwards.
- Result: A name mismatch switched the filter off silently, seen only because it logged nothing. A missing carrier let main hoses run through an arch, found by the reviewer. Filter plus image check removed 142 lines, of which 34 went with one radius; density ended at 76 percent against a target of 80.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Rebuild rig parts in dependency order, and read the numbers of the fresh test
- Kind: pitfall
- Applies to: rigs with a master control linked into generated sub-networks
- What: Rebuilding a sub-rig on its own can drop its link to the master control, and no error appears. A passing check for errors and primitive counts does not catch it. Compare bounding boxes per pose in the fresh-process test against earlier values, and always rebuild in the same order.
- Result: One wing stopped folding after a rebuild in the wrong order. Errors were zero and the count looked right; the width staying at 26 m at full fold showed it. A reviewer or artist would have seen it only in a folded view.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Check that the artist's scene really shows the current build
- Kind: pitfall
- Applies to: pipelines where one tool builds and another shows the model
- What: A build can pass all checks in the building tool while the artist looks at an older export in another. Export every part in every full build, reload in the target and compare a file timestamp, not only a status line.
- Result: The artist kept reporting a removed part and misplaced new parts. The fuselage and two wings in the Houdini scene were hours old, the checks in Blender were right. After that was found, the feedback matched the build again.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Author MaterialX shaders as plain USD for a portable first look
- Kind: workflow
- Applies to: first material pass on a large asset without UVs, Karma
- What: Bake one mesh per material class, carry a random per part and an edge attribute as primvars, and write the shader graph with UsdShade and ND ids. Use triplanar maps. Put palettes in a variant set, and author the value only inside the variant, because a local value is stronger. Houdini names Cd as displayColor in USD, and sopimport writes time samples and needs a flattened save.
- Result: A 6.4 million polygon asset rendered in Karma within a day's iteration, with four palettes and two fold states. Each of the listed traps cost one failed render first. The artist's verdict is open.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-02

### Keep rigid parts in joint space and freeze deforming parts in the rest pose
- Kind: workflow
- Applies to: handing a SOP rig to a USD asset, Houdini
- What: Measure every part across several poses with a rigid fit. Put rigid parts in the local space of their joint under nested Xforms, put deforming parts and parts without a joint under one branch in the rest pose. An animation layer then only overrides joint matrices, points, normals, extent and visibility.
- Result: The artist proposed the frozen rest pose. All 36 joints matched the rig with 0 deviation and point counts matched. The layer cost about 21 MB per frame. A bound computed from boxes overstated the size by 2 m after rotation, only a bound from the points was reliable.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### A primer colour must follow the paint
- Kind: pitfall
- Applies to: shared wear masks on dark and light paint, MaterialX
- What: One wear mask alone does not make parts age alike. A fixed light primer read as large grey islands on dark frames and vanished on light panels. Derive primer from the paint and keep exposed rust close to aged paint in brightness.
- Result: After this change the dark frame and light panels read as aged together in my image check. A reviewer has not seen this state.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Write time samples frame by frame when usd_rop stalls
- Kind: pitfall
- Applies to: Houdini 22 usd_rop with a frame range on heavy SOP chains
- What: A range render did not finish within 400 s for a static test pose, while the same chain wrote one frame in under a second. Write single frames and copy points, normals and extent into one layer with the USD API.
- Result: Two frames took about 11 s. I did not find the cause of the stall.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Ask for UVs before subdividing a mesh for shading data
- Kind: pitfall
- Applies to: wear and mask fields that need more resolution than the topology, any production asset
- What: To carry edge and rivet distance fields as primvars I cut big polygons with a brick grid. That bakes density into the mesh and leaves irregular polygons and T-junctions. When shading data outgrows the topology, say so before building and propose automated UVs with baked maps. Render-time subdivision does not help, it only interpolates the coarse values.
- Result: The mesh grew from 6.6 M to 11.4 M polygons and the file from 513 MB to 1067 MB. The artist did not expect that and asked for UVs as the default next time. The grid stays only as a working state to settle the look.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Separate paint loss from corrosion in a wear shader
- Kind: workflow
- Applies to: painted metal wear, MaterialX
- What: Measure distance to edges, seams and rivets, and let noise only fray those regions instead of deciding where wear sits. Use two controls: wear for how much paint is gone, rust for how much of the opening has corroded and how far it creeps under paint. Keep rust tied to nearby damage.
- Result: Rust moved from a global mask onto rivets and edges and the tiling was gone. An independent review against photos still rated colour, edges and regulator behaviour as not there yet, and the artist still reads the edge as CG noise. Work continues.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Look at a baked field as grey emission before tuning the shader
- Kind: workflow
- Applies to: shaders driven by baked primvars or maps, Karma
- What: When a shader result does not move as expected, render the single field as flat emission and print its statistics per material before changing weights. Filter neighbours by normal when measuring curvature on thin sheets, because the back of the sheet lies inside the search radius.
- Result: Two of my guesses about the cause were wrong and cost a bake each. The grey picture showed curvature near 1 on all flat sheets at once. After the fix the rust moved onto edges. Part of the look the artist liked had come from that bug and had to be rebuilt on purpose.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Match primvar types to what the shader reads
- Kind: pitfall
- Applies to: MaterialX geompropvalue_float, USD primvars from SOPs
- What: A geompropvalue_float does not read an int primvar and silently returns its default. Store flags as float. Also local input values on a shader are stronger than values authored inside a variant, so leave the input unset in the base.
- Result: A UV flag and two palette values had no effect, with no error. Both were found only by reading the composed stage.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Remesh a voxel union with Quad Remesh for welded tube frames
- Kind: tip
- Applies to: tube frames from sketch curves, Blender and Houdini 22
- What: Close each tube, union them with a voxel remesh, smooth only near junctions, then run Houdini's Quad Remesh node. A skin modifier broke on acute branches.
- Result: 270,392 faces became 12,034 pure quads in 2 s with at most 0.41 cm deviation. The artist has not judged the final topology yet.
- Signed: Claude Opus 5.5, Blender 5.2, Houdini 22.0.368, 2026-11-03

### Line-art animation from exported curves in a browser page
- Kind: workflow
- Applies to: logo and line-drawing animation, motion that stays in the drawing plane
- What: Export the curves with width per point, draw them as ribbons in WebGL with the tool's own brush shader, compute the pose of every frame from time alone (springs baked once in advance). Any frame can then be reproduced for review sheets and the final image sequence. Judge the still against the original logo before animating anything.
- Result: the look matched the logo on the first comparison; ten versions until the artist accepted, nearly all of them on motion and timing.
- Signed: Claude Opus 5.5, WebGL2 and Mule curve export, 2026-11-04

### Single frames do not judge motion
- Kind: check
- Applies to: animation reviewed by a sub-agent
- What: A reviewer on contact sheets reliably finds overlaps, gaps, colour faults and wrong direction, and it cannot judge rhythm, flicker or character. Give it dense frames around every transition and let the artist judge the motion in playback. Give it the artist's feedback as ranking above the references, or it argues against explicit wishes.
- Result: found a colour fault and a wrong ear direction in the first round; the artist still found twitching that the sheets did not show.
- Signed: Claude Opus 5.5, WebGL2 and Mule curve export, 2026-11-04

### Reveal only what stays covered or stays
- Kind: pitfall
- Applies to: parts that move away and uncover something, 2D and layered animation
- What: Elements added to hide a gap must not fade or shrink away while visible, because the eye catches it. Place them where a moving part covers them at rest, or keep them permanently.
- Result: fading added hair was rejected at once; hair placed under the moving part was accepted.
- Signed: Claude Opus 5.5, WebGL2 and Mule curve export, 2026-11-04
