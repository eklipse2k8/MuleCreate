"""OpenGL rendering (moderngl): shaded meshes, planes with depth, GPU picking.

The viewport draws strokes and gizmos afterwards via QPainter as an overlay on top.
Picking: meshes are rendered into an invisible buffer that stores per pixel the
world position and the mesh number. Reading one pixel costs the same regardless
of the triangle count.
"""
import math
import time

import moderngl
import numpy as np


from . import theme
from . import counters, lru

PENCIL_GRAIN = 1.0  # strength of the pencil texture (0 = smooth strokes)
PICTURE_UNIT = 13  # texture unit of the projected images
SURF_UNIT = 12  # texture unit of the surface table (SURF_DATA)
SURF_COLS = 10  # texels per surface in the table
SURF_ROWS = 4096  # this many surfaces stacked, then the next column group (tests: small, checks the wrap)
# Surface table: all surfaces live in ONE buffer and are drawn with ONE call per pass. What differs per
# surface (material, coloring, state, position in the drag ...) is in a data texture, one row per surface;
# each corner carries the number of its surface (in_slot). Before: one call per surface and pass, each preceded by a
# dozen uniforms (harbor 11.11.: 944 surfaces, 3,868 calls per frame).
#   0: tint.rgb, material     1: anchor.xyz, tex_scale     2: offset.xyz, grid_step     3: state
#   4: grid_color.rgb, grid_alpha     5: lift, opacity, id, carried along?     6: coverage radius, opacity value, covers?
#   7–9: rows of the position matrix (only if carried along)
SURF_DATA = """
uniform sampler2D surf_data;
uniform int surf_rows;
vec4 surf(int slot, int col) {
    return texelFetch(surf_data, ivec2(col + %d * (slot / surf_rows), slot %% surf_rows), 0);
}
""" % SURF_COLS
PLANE_DEPTH_BIAS = 2e-5  # plane depth minimally to the back: strokes on the plane stay clearly in front
GL_MULTISAMPLE = 0x809D
# blend color normally but add up alpha: otherwise the image alpha drops below 1 and Qt
# mixes the window with the light background (semi-transparent surfaces would get lighter instead of see-through)
GL_DEPTH_BUFFER_BIT = 0x100
GL_POINT_SPRITE = 0x8861
# Coverage map: per pixel the frontmost covering layer (surfaces, meshes). Drawing aids and
# strokes compare their distance to the camera against it (world units, the same at every zoom level). Tolerance perpendicular
# to the surface in surfel radii: (own surface - e.g. drawn on it or outline line, membership unknown -
# planes, free mode, foreign surface)
OCCL_TOL = (0.5, 0.3, 0.02)
OCCL_MIN_COVER = 0.0  # without minimum opacity: what lies behind shines through according to the opacity of the layer
OCCL_ACC_UNIT = 7  # texture unit of the opacity of the frontmost layer
WIRE_DEPTH_BIAS = 2e-4  # wireframe on opaque meshes: depth offset toward the camera (fraction of the depth range)
MESH_OCCL_RADIUS = 1e-6  # meshes in the coverage map: "radius" in world units - practically none, the pixels count
SURFACE_OCCL_RADIUS = 0.02  # surfaces in the coverage map: "radius" as a fraction of their diagonal (tolerance on them)
OCCL_UNIT = 6  # texture unit of the coverage map
XRAY_BEHIND = 0.4  # X-Ray: what is hidden at this fraction of the opacity of the front layer
SHADOW_SIZE = 4096  # resolution of the shadow map
SHADOW_BIAS = 0.0015  # bias against self-shadowing (depth 0..1 over the scene)
SHADOW_LINE_PX = 2.0  # lines cast shadows at this width (pixels of the shadow map)
SHADOW_UNIT = 5  # texture unit of the shadow map
LIGHT_EDGE_GAIN = 0.25  # light edge of the lines: this much lighter than the line (subtle, no hard white fringe)
STROKE_BIAS = 3e-5  # depth lead of the strokes (they lie visibly on surfaces)
BLEND_OVER = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ONE, moderngl.ONE)

NOISE = """
// Rauschen für Papier- und Bleistiftstruktur (Hash ohne Textur, stabil auf allen Treibern)
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), f.x),
               mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), f.x), f.y);
}
"""

PAPER_LIB = """
// 3D-Rauschen (für die Blickkugel des Hintergrunds)
float hash13(vec3 p3) {
    p3 = fract(p3 * 0.1031);
    p3 += dot(p3, p3.zyx + 31.32);
    return fract((p3.x + p3.y) * p3.z);
}
float vnoise3(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = mix(mix(hash13(i), hash13(i + vec3(1, 0, 0)), f.x), mix(hash13(i + vec3(0, 1, 0)), hash13(i + vec3(1, 1, 0)), f.x), f.y);
    float b = mix(mix(hash13(i + vec3(0, 0, 1)), hash13(i + vec3(1, 0, 1)), f.x), mix(hash13(i + vec3(0, 1, 1)), hash13(i + vec3(1, 1, 1)), f.x), f.y);
    return mix(a, b, f.z);
}
// Papier auf einer Fläche, p in Welteinheiten. fw = Weltgröße eines Pixels: Details, die kleiner
// als ein Pixel würden, werden ausgeblendet (sonst flimmert es beim Herauszoomen)
float paper2(vec2 p, float fw) {
    float blotch = vnoise(p * 0.7) - 0.5;
    float fibers = (vnoise(p * vec2(26.0, 5.0)) + vnoise(p * vec2(5.0, 26.0) + 41.0)) * 0.5 - 0.5;
    float tooth = vnoise(p * 70.0) - 0.5;
    fibers *= 1.0 - smoothstep(0.02, 0.08, fw);
    tooth *= 1.0 - smoothstep(0.008, 0.03, fw);
    return blotch * 0.04 + fibers * 0.6 + tooth * 0.7;  // Flecken nur noch unterbewusst
}
// triplanar: aus drei Richtungen projiziert, nach der Flächennormale gemischt
float paper_triplanar(vec3 p, vec3 n, float fw) {
    vec3 w = pow(abs(n), vec3(4.0));
    w /= max(w.x + w.y + w.z, 1e-6);
    return paper2(p.yz, fw) * w.x + paper2(p.zx + 13.0, fw) * w.y + paper2(p.xy + 29.0, fw) * w.z;
}
"""

SHADOW_LIB = """
uniform float bands;  // Licht-Stufen: 0 = fließend, sonst so viele Helligkeitsstufen (Cel-Shading)
float band(float x) {
    if (bands < 1.5) return x;
    return floor(clamp(x, 0.0, 1.0) * (bands - 1.0) + 0.5) / (bands - 1.0);
}
uniform float shadow_on;
uniform mat4 shadow_vp;
uniform sampler2D shadow_map;
uniform float shadow_bias;
uniform float shadow_lift;  // Weltabstand zur Sonne hin, um den Linien geprüft werden
float in_shadow(vec3 world) {
    // Schattenkarte der Sonne: liegt zwischen diesem Punkt und der Sonne etwas? (3x3 gemittelt: weiche Kanten)
    if (shadow_on < 0.5) return 0.0;
    vec4 sp = shadow_vp * vec4(world, 1.0);
    vec3 q = sp.xyz / sp.w * 0.5 + 0.5;
    if (q.x <= 0.0 || q.x >= 1.0 || q.y <= 0.0 || q.y >= 1.0 || q.z >= 1.0) return 0.0;
    vec2 texel = 1.0 / vec2(textureSize(shadow_map, 0));
    float hit = 0.0;
    for (int i = -1; i <= 1; i++)
        for (int j = -1; j <= 1; j++)
            hit += q.z - shadow_bias > texture(shadow_map, q.xy + vec2(i, j) * texel).r ? 1.0 : 0.0;
    return hit / 9.0;
}
uniform float dome;  // Anteil des Himmelslichts (Domelight): Formen bleiben auch im Schatten lesbar
vec3 sun_and_sky(vec3 n, float sun_part, vec3 sky) {
    // sun_part: Sonnenlicht samt Schatten; dazu Licht vom ganzen Himmel – oben voll, nach unten weniger, leicht blau
    float up = band(0.5 + 0.5 * n.y);
    return mix(vec3(sun_part), up * mix(vec3(1.0), sky, 0.5), dome);
}
"""

MESH_VS = """
#version 330
uniform mat4 mvp;
uniform mat4 model;
in vec3 in_pos;
in vec3 in_color;
out vec3 v_world;
out vec3 v_color;
void main() {
    v_world = (model * vec4(in_pos, 1.0)).xyz;
    v_color = in_color;
    gl_Position = mvp * vec4(in_pos, 1.0);
}
"""

MESH_FS = """
#version 330
uniform vec3 eye;
uniform vec4 tint;
uniform float alpha;
uniform float lift;  // Schatten-Prüfpunkt so weit von der Fläche weg (Welteinheiten)
uniform float light_on;
uniform vec3 sun_dir;
uniform vec3 sun_col;
uniform vec3 sky_col;
uniform float away_dark;
uniform float shadow_dark;
in vec3 v_world;
in vec3 v_color;
out vec4 f_color;
""" + SHADOW_LIB + """
void main() {
    // Flächennormale aus Bildschirm-Ableitungen: keine Normalen nötig, flach schattiert
    vec3 n = normalize(cross(dFdx(v_world), dFdy(v_world)));
    vec3 l = normalize(eye - v_world);
    if (dot(n, l) < 0.0) n = -n;  // die Seite, die man sieht
    vec3 c;
    if (light_on > 0.5) {
        // Licht-Modus: Sonne, abgewandte Seite und Schatten wie bei den Flächen
        float nl = dot(n, sun_dir);
        float k = band(smoothstep(-0.25, 0.9, nl));
        float sh = band(in_shadow(v_world + (nl >= 0.0 ? n : -n) * lift + sun_dir * lift));
        float lit = min(mix(1.0 - away_dark, 1.0, k), 1.0 - shadow_dark * sh);
        c = v_color * sun_and_sky(n, lit, sky_col) * mix(sky_col, sun_col, k * (1.0 - sh));
    } else {
        float d = band(dot(n, l));
        c = v_color * (0.72 + 0.28 * d);  // importierte Meshes: mittelgrau, flach schattiert (Bleistift bleibt lesbar)
    }
    f_color = vec4(mix(c, tint.rgb, tint.a), alpha);
}
"""

WIRE_VS = """
#version 330
uniform mat4 mvp;
uniform float bias;  // Anteil der Tiefe: Kanten liegen knapp vor ihrer Fläche
in vec3 in_pos;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    gl_Position.z -= bias * gl_Position.w;
}
"""

WIRE_FS = """
#version 330
uniform vec4 color;  // Drahtgitter der Meshes: Kantenfarbe mit Deckkraft des Reglers
out vec4 f_color;
void main() {
    f_color = color;
}
"""

OCCL_VIEW = """
uniform vec3 eye;
uniform vec3 view_back;
uniform float ortho;
"""

OCCL_LIB = """
uniform sampler2D occl_map;  // je Pixel: Abstand der vordersten deckenden Schicht, |cos| Blick/Normale, Radius, Flächen-id
uniform float occl_on;
uniform float xray_behind;   // Verdecktes: 0 = unsichtbar, X-Ray: sanft (Deckkraft)
uniform vec3 occl_tol;       // Spielraum in Radien: eigene Fläche, unbekannt, fremde Fläche
uniform sampler2D occl_acc;  // Deckkraft der vordersten Schicht je Pixel (als -log(1 - a) aufsummiert)
uniform float occl_min;      // ab dieser Deckkraft deckt sie (0: Deckkraft nicht prüfen)
bool occl_dense_at(ivec2 q) {
    return occl_min <= 0.0 || 1.0 - exp(-texelFetch(occl_acc, q, 0).r) >= occl_min;
}
bool occl_dense() { return occl_dense_at(ivec2(gl_FragCoord.xy)); }
// vorderste deckende Schicht im 3x3-Umfeld (am Umriss einer Fläche liegt die Pixelmitte oft knapp daneben – ohne
// Umfeld schiene Verdecktes dort als Punkte durch); liefert die Karte dort und schreibt ihre Lage nach q
vec4 occl_front(out ivec2 q) {
    ivec2 c = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(occl_map, 0);
    vec4 best = texelFetch(occl_map, c, 0);
    q = c;
    for (int i = -1; i <= 1; i++)
        for (int j = -1; j <= 1; j++) {
            ivec2 t = clamp(c + ivec2(i, j), ivec2(0), size - 1);
            vec4 m = texelFetch(occl_map, t, 0);
            if (m.b > 0.0 && (best.b <= 0.0 || m.r < best.r) && occl_dense_at(t)) {
                best = m;
                q = t;
            }
        }
    return best;
}
float view_dist(vec3 p) { return ortho > 0.5 ? dot(eye - p, view_back) : length(p - eye); }
// 1.0: vorne bzw. auf der vordersten Fläche; sonst xray_behind. owners: Flächen-ids, zu denen p gehört (-1 = keine),
// other: Spielraum gegenüber fremden Flächen (Radien)
float cover_t(vec3 p, vec4 owners, float other) {
    if (occl_on < 0.5) return 1.0;
    ivec2 q;
    vec4 m = occl_front(q);
    if (m.b <= 0.0 || !occl_dense_at(q)) return 1.0;  // hier deckt nichts (bzw. nur dünn)
    float d = view_dist(p);
    float diff = d - m.r;
    float eps = 2e-5 * abs(d);
    if (diff <= eps) return 1.0;
    bool own = m.a >= 0.0 && any(equal(owners, vec4(m.a)));
    bool known = m.a >= 0.0 && max(max(owners.x, owners.y), max(owners.z, owners.w)) >= 0.0;
    float tol = own ? occl_tol.x : (known ? other : occl_tol.y);
    // senkrecht zur Fläche messen (Blickwinkel egal), entlang des Blicks höchstens wenige Radien
    if (diff * m.g <= tol * m.b + eps && diff <= (own ? 4.0 : 2.0) * m.b) return 1.0;
    // dahinter: so weit, wie die vorderste Schicht durchlässt (deckende Fläche: nichts; X-Ray: sanft)
    return max(xray_behind, exp(-texelFetch(occl_acc, q, 0).r));
}
float cover(vec3 p, vec4 owners) { return cover_t(p, owners, occl_tol.z); }
// Deckkraft-Durchgang: gehört p zur vordersten Schicht genau an seinem Pixel? Nicht im 3x3-Umfeld wie cover() – an
// jeder Tiefenkante (ein näheres Teil im Nachbarpixel) fiele die hintere Seite sonst heraus, hätte dort keine Deckkraft,
// und was dahinter liegt, schiene als Sprenkel durch (dichte Meshes: überall Kanten)
bool front_here(vec3 p, vec4 owners) {
    if (occl_on < 0.5) return true;
    vec4 m = texelFetch(occl_map, ivec2(gl_FragCoord.xy), 0);
    if (m.b <= 0.0) return true;
    float d = view_dist(p);
    float diff = d - m.r;
    float eps = 2e-5 * abs(d);
    if (diff <= eps) return true;
    bool own = m.a >= 0.0 && any(equal(owners, vec4(m.a)));
    bool known = m.a >= 0.0 && max(max(owners.x, owners.y), max(owners.z, owners.w)) >= 0.0;
    float tol = own ? occl_tol.x : (known ? occl_tol.z : occl_tol.y);
    return diff * m.g <= tol * m.b + eps && diff <= (own ? 4.0 : 2.0) * m.b;
}
// Flächen untereinander: sichtbar, wenn sie an irgendeinem Pixel des 3x3-Umfelds vorne ist – am Umriss einer davor
// liegenden Fläche entscheidet dann der Tiefentest je Sample (Kantenglättung), statt dass dort Papier durchscheint
float cover_at(vec3 p, vec4 owners, ivec2 q) {
    vec4 m = texelFetch(occl_map, q, 0);
    if (m.b <= 0.0 || !occl_dense_at(q)) return 1.0;
    float d = view_dist(p);
    float diff = d - m.r;
    float eps = 2e-5 * abs(d);
    if (diff <= eps) return 1.0;
    bool own = m.a >= 0.0 && any(equal(owners, vec4(m.a)));
    bool known = m.a >= 0.0 && max(max(owners.x, owners.y), max(owners.z, owners.w)) >= 0.0;
    float tol = own ? occl_tol.x : (known ? occl_tol.z : occl_tol.y);
    if (diff * m.g <= tol * m.b + eps && diff <= (own ? 4.0 : 2.0) * m.b) return 1.0;
    return max(xray_behind, exp(-texelFetch(occl_acc, q, 0).r));
}
float cover_edge(vec3 p, vec4 owners) {
    if (occl_on < 0.5) return 1.0;
    ivec2 c = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(occl_map, 0);
    float v = 0.0;
    for (int i = -1; i <= 1; i++)
        for (int j = -1; j <= 1; j++)
            v = max(v, cover_at(p, owners, clamp(c + ivec2(i, j), ivec2(0), size - 1)));
    return v;
}
// Zeichenhilfen: liegt p auf oder hinter der vordersten Fläche? Dann wird sie vor der Fläche
// gezeichnet und von ihr zugedeckt (weich an Rändern, unsichtbar im Inneren)
uniform float aid_pass;  // 0: Durchgang unter den Flächen, 1: darüber (davor bzw. ohne Fläche, Lasur der aktiven Ebene)
// Deckkraft der vordersten Schicht hier (0 = keine Fläche): inaktive Zeichenhilfen davor blenden so weit aus
float front_opacity() {
    if (occl_on < 0.5) return 0.0;
    if (texelFetch(occl_map, ivec2(gl_FragCoord.xy), 0).b <= 0.0) return 0.0;
    return 1.0 - exp(-texelFetch(occl_acc, ivec2(gl_FragCoord.xy), 0).r);
}
bool on_layer(vec3 p) {
    if (occl_on < 0.5) return false;
    vec4 m = texelFetch(occl_map, ivec2(gl_FragCoord.xy), 0);
    return m.b > 0.0 && view_dist(p) > m.r - occl_tol.x * m.b;
}
"""

SHADOW_LINE_VS = """
#version 330
uniform mat4 svp;
in vec3 in_pos;
void main() {
    gl_Position = svp * vec4(in_pos, 1.0);
}
"""

SHADOW_LINE_FS = """
#version 330
void main() {
}
"""

PICK_VS = """
#version 330
uniform mat4 mvp;
uniform mat4 model;
in vec3 in_pos;
out vec3 v_world;
void main() {
    v_world = (model * vec4(in_pos, 1.0)).xyz;
    gl_Position = mvp * vec4(in_pos, 1.0);
}
"""

PICK_GATHER_VS = """
#version 330
uniform float count;
in vec2 in_xy;          // Pixel im Positionspuffer
flat out ivec2 v_xy;
void main() {
    v_xy = ivec2(in_xy);
    gl_PointSize = 1.0;
    gl_Position = vec4((float(gl_VertexID) + 0.5) / count * 2.0 - 1.0, 0.0, 0.0, 1.0);  // Pixel k der Zeile
}
"""

PICK_GATHER_FS = """
#version 330
uniform sampler2D pick_tex;
uniform sampler2D prim_tex;
flat in ivec2 v_xy;
layout(location = 0) out vec4 f_out;
layout(location = 1) out float f_prim;
void main() {
    ivec2 xy = clamp(v_xy, ivec2(0), textureSize(pick_tex, 0) - 1);
    f_out = texelFetch(pick_tex, xy, 0);
    f_prim = texelFetch(prim_tex, xy, 0).r;
}
"""

# visibility of individual points (point symbols in edit): one pixel of a row per point, there the same occlusion rule
# as for strokes (coverage map, 3x3 neighborhood) - only this row is read
POINT_VIS_VS = """
#version 330
uniform float count;
uniform mat4 vp;
uniform vec2 size;
in vec3 in_pos;
flat out ivec2 v_xy;
flat out int v_front;
out vec3 v_p;
void main() {
    vec4 c = vp * vec4(in_pos, 1.0);
    v_front = c.w > 0.0 ? 1 : 0;
    vec2 ndc = c.xy / max(abs(c.w), 1e-12);
    v_xy = ivec2(floor((ndc * 0.5 + 0.5) * size));
    v_p = in_pos;
    gl_PointSize = 1.0;
    gl_Position = vec4((float(gl_VertexID) + 0.5) / count * 2.0 - 1.0, 0.0, 0.0, 1.0);  // Pixel k der Zeile
}
"""

POINT_VIS_FS = """
#version 330
""" + OCCL_VIEW + OCCL_LIB + """
flat in ivec2 v_xy;
flat in int v_front;
in vec3 v_p;
out float f_vis;
void main() {
    if (occl_on < 0.5 || v_front == 0) { f_vis = 1.0; return; }
    ivec2 size = textureSize(occl_map, 0);
    float v = 0.0;
    for (int i = -1; i <= 1; i++)
        for (int j = -1; j <= 1; j++)
            v = max(v, cover_at(v_p, vec4(-1.0), clamp(v_xy + ivec2(i, j), ivec2(0), size - 1)));
    f_vis = v;
}
"""

PICK_FS = """
#version 330
uniform float mesh_index;
in vec3 v_world;
layout(location = 0) out vec4 f_out;
layout(location = 1) out float f_prim;  // Nummer des getroffenen Dreiecks (genauer Schnitt nur mit diesem)
void main() {
    f_out = vec4(v_world, mesh_index);
    f_prim = float(gl_PrimitiveID);
}
"""

PICTURE_FS = """
#version 330
uniform mat4 picture_m;
uniform sampler2D picture;
uniform vec3 eye;
uniform vec3 view_back;
uniform float ortho;
uniform vec4 owner;
uniform float under;
in vec3 v_world;
out vec4 f_color;
""" + "%OCCL%" + """
void main() {
    vec4 c = picture_m * vec4(v_world, 1.0);
    if (c.w <= 0.0) discard;
    vec2 uv = c.xy / c.w * 0.5 + 0.5;
    vec4 tex = texture(picture, uv);
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) discard;
    float vis = cover(v_world, owner);
    if (vis <= 0.0) discard;
    f_color = vec4(tex.rgb, tex.a * vis);
}
"""

FLAT_VS = """
#version 330
uniform mat4 vp;
uniform float bias;  // > 0: minimal nach hinten (Tiefen-Durchgang der Ebenen)
in vec3 in_pos;
out vec3 v_world;
void main() {
    v_world = in_pos;
    vec4 c = vp * vec4(in_pos, 1.0);
    gl_Position = vec4(c.xy, c.z + bias * c.w, c.w);
}
"""

FLAT_FS = """
#version 330
uniform vec4 color;
uniform float grain;  // Transparentpapier: Papierstruktur in der Füllung (fest auf der Ebene)
uniform vec3 eye;
uniform vec3 view_back;
uniform float ortho;
uniform float milk;   // unter flachem Blick milchiger (wie echtes Pauspapier)
uniform vec4 owner;   // Ebene/Zeichenfläche (für die Deckungskarte)
uniform float under;  // auf einer Fläche: diese Deckkraft (Lasur der Ebene, 0 = weg), < 0 = unverändert
uniform float soft;   // 1: unbeteiligte Ebene (weder Zeichenebene noch gewählt) – auch VOR einer Fläche nur die Lasur
in vec3 v_world;
out vec4 f_color;
""" + NOISE + PAPER_LIB + OCCL_LIB + """
void main() {
    // Ableitungen vor jedem discard (danach sind sie in den Nachbarpixeln undefiniert: schwarze Pixel am Flächenrand)
    vec3 cr = cross(dFdx(v_world), dFdy(v_world));
    vec3 n = length(cr) > 1e-20 ? normalize(cr) : vec3(0.0, 1.0, 0.0);
    float fw_w = length(fwidth(v_world));
    float vis = cover(v_world, owner);  // Zeichenhilfen hinter einer Fläche: weg (X-Ray: sanft)
    if (vis <= 0.0) discard;
    float tex = 0.0;
    float a = color.a;
    if (grain > 0.0) {
        tex = paper_triplanar(v_world, n, fw_w);
        vec3 view = ortho > 0.5 ? view_back : normalize(eye - v_world);
        a = min(a * (1.0 + milk * (1.0 - abs(dot(n, view)))), 1.0);
    }
    bool low = on_layer(v_world);
    if (aid_pass < 0.5) {
        if (!low) discard;  // unter den Flächen: nur was auf/hinter ihnen liegt
    } else if (low) {
        if (under <= 0.0) discard;  // über einer Fläche nur die Lasur der Ebene
        a = under;
    } else if (under <= 0.0) {
        a *= 1.0 - front_opacity();  // ohne Lasur vor einer Fläche: verdeckt sie nicht
    } else if (soft > 0.5) {
        a = mix(a, under, front_opacity());  // unbeteiligt vor einer Fläche: nur die Lasur, vor dem Papier voll
    }
    if (a <= 0.0) discard;
    f_color = vec4(color.rgb * (1.0 + grain * 0.06 * tex), a * vis);
}
"""

INFINITE_FS = """
#version 330
uniform vec3 origin;
uniform vec3 axis_u;
uniform vec3 axis_v;
uniform vec2 half_size;   // Kern (das sichtbare Rechteck): dort zeichnet die normale Ebene
uniform float has_core;   // 0: Grundraster ohne Kern (überall)
uniform vec2 tile_size;   // Kachelgröße
uniform vec2 tile_offset; // Kachelgrenzen: Ränder des Kerns (Ebene) bzw. durch den Ursprung (Grundraster)
uniform vec2 grid_step;
uniform vec4 fill;        // Milch: Farbe + Deckkraft
uniform vec3 line;
uniform float grid_alpha;
uniform float tile_alpha; // Kacheln in der Größe der Ebene (Rechteck wiederholt sich)
uniform vec3 eye;
uniform vec3 view_back;
uniform float ortho;
uniform float reach;      // ausblenden bis zu dieser Entfernung
uniform vec4 owner;
in vec3 v_world;
out vec4 f_color;
""" + OCCL_LIB + """
void main() {
    vec3 d = v_world - origin;
    float s = dot(d, axis_u), t = dot(d, axis_v);
    vec2 g = vec2(s, t) / grid_step;
    vec2 fw = max(fwidth(g), vec2(1e-6));  // Ableitungen vor jedem discard
    vec2 k = (vec2(s, t) + tile_offset) / tile_size;
    vec2 kw = max(fwidth(k), vec2(1e-6));
    float vis = cover(v_world, owner);
    if (vis <= 0.0 || on_layer(v_world) != (aid_pass < 0.5)) discard;
    vis *= 1.0 - front_opacity();  // vor einer Fläche: verdeckt sie nicht
    if (has_core > 0.5 && abs(s) < half_size.x && abs(t) < half_size.y) discard;
    vec2 f = abs(fract(g - 0.5) - 0.5) / fw;
    float lines = (1.0 - min(min(f.x, f.y), 1.0)) * (1.0 - smoothstep(0.12, 0.45, max(fw.x, fw.y)));
    vec2 kf = abs(fract(k - 0.5) - 0.5) / kw;
    float tiles = (1.0 - min(min(kf.x, kf.y), 1.0)) * (1.0 - smoothstep(0.12, 0.45, max(kw.x, kw.y)));
    vec3 n = normalize(cross(axis_u, axis_v));
    vec3 view = ortho > 0.5 ? view_back : normalize(eye - v_world);
    float dist = ortho > 0.5 ? length(vec2(s, t)) : length(v_world - eye);
    float fade = (1.0 - smoothstep(reach * 0.12, reach, dist)) * smoothstep(0.02, 0.3, abs(dot(n, view)));
    float ink = max(grid_alpha * lines, tile_alpha * tiles);
    float a = (fill.a + ink) * fade * vis;
    if (a < 0.002) discard;
    f_color = vec4(mix(fill.rgb, line, min(1.0, ink / max(a / max(fade, 1e-6), 1e-6))), a);
}
"""

PAPER_VS = """
#version 330
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);  // ein Dreieck über den ganzen Bildschirm
    gl_Position = vec4(p * 2.0 - 1.0, 0.999, 1.0);
}
"""

PAPER_FS = """
#version 330
uniform vec3 paper;
uniform vec2 size;
uniform float stain;
uniform float grain;
uniform float vignette;
uniform vec3 cam_right;   // Kamera-Basis: das Papier liegt auf einer Kugel um die Kamera
uniform vec3 cam_up;
uniform vec3 cam_back;
uniform float view_tan;   // tan(halber Öffnungswinkel), auch orthografisch (dreht dann nur mit)
out vec4 f_color;
""" + NOISE + PAPER_LIB + """
void main() {
    vec2 ndc = gl_FragCoord.xy / size * 2.0 - 1.0;
    vec3 dir = normalize(-cam_back + ndc.x * view_tan * (size.x / size.y) * cam_right + ndc.y * view_tan * cam_up);
    // Struktur auf der Blickkugel: 3D-Rauschen auf der Richtung, ohne Nähte und Pole
    float blotch = vnoise3(dir * 3.0) * 0.6 + vnoise3(dir * 7.0 + 5.0) * 0.4 - 0.5;   // große, weiche Flecken
    float fibers = (vnoise3(dir * vec3(380.0, 70.0, 380.0)) + vnoise3(dir * vec3(70.0, 380.0, 70.0) + 9.0)) * 0.5 - 0.5;
    float tooth = vnoise3(dir * 1300.0) - 0.5;                                        // Körnung
    vec2 uv = gl_FragCoord.xy / size - 0.5;
    float shade = 1.0 + stain * 2.0 * blotch + grain * (0.9 * tooth + 0.6 * fibers);
    shade *= 1.0 - vignette * dot(uv, uv) * 1.6;
    f_color = vec4(paper * shade, 1.0);
}
"""

RIBBON_VS = """
#version 330
uniform mat4 vp;
uniform vec2 half_vp;   // halbe Framebuffer-Größe in Pixeln
uniform float focal;    // 1 / tan(fov/2), orthografisch 1 / halbe Bildhöhe (w ist dann 1)
uniform float min_px;   // Mindestbreite, damit ferne Striche nicht verschwinden
uniform float bias;     // leicht zur Kamera ziehen, damit Striche auf Flächen nicht flackern
in vec3 in_pos;
in vec3 in_prev;
in vec3 in_next;
in float in_width;
in float in_side;
in float in_arc;   // Bogenlänge in Strichbreiten (Textur klebt am Strich)
in vec4 in_color;
uniform vec3 eye;        // Licht-Modus: Blickrichtung je Punkt (perspektivisch) …
uniform vec3 view_back;  // … bzw. orthografisch
uniform float ortho;
uniform vec3 sun_dir;    // Richtung zur Sonne
out vec4 v_color;
out float v_w;
out float v_side;
out float v_arc;
out float v_px;
out float v_brush;
out float v_light;       // > 0: Seite +1 zeigt zur Sonne, < 0: Seite -1; Betrag: wie deutlich
out vec3 v_wpos;
out vec3 v_tan;           // Strichrichtung im Raum (Röhre für die Verdeckung, 0: Malstrich)
out float v_rad;          // halbe Strichbreite in Welteinheiten (0: flach)
in vec4 in_owner;         // Zeichenflächen, zu denen der Strich gehört (-1 = keine)
flat out vec4 v_owner;
in vec3 in_normal;        // Malstrich: Flächennormale (sonst 0)
in float in_layer;        // Malstrich: Reihenfolge 0..1 (neuer = höher = oben)
void main() {
    v_wpos = in_pos;
    v_owner = in_owner;
    float brush = step(1.5, abs(in_side));  // Pinsel: Seite ±2
    if (length(in_normal) > 0.5) {
        // Malstrich: flach in der Fläche (Breite quer zum Strich in der Flächenebene), wird unter flachem Blick
        // schmaler wie Farbe auf Papier; Tiefe = Malreihenfolge (der neueste liegt oben, Verdecken regelt die
        // Deckungskarte)
        float fside = in_side / (1.0 + brush);
        vec3 T = in_next - in_prev;
        T = length(T) > 1e-9 ? normalize(T) : vec3(1.0, 0.0, 0.0);
        vec3 B = cross(normalize(in_normal), T);
        B = length(B) > 1e-6 ? normalize(B) : vec3(0.0, 1.0, 0.0);
        vec4 cf = vp * vec4(in_pos + B * fside * in_width * 0.5, 1.0);
        float wf = max(cf.w, 1e-5);
        gl_Position = vec4(cf.xy, (0.9 - 1.8 * in_layer) * cf.w, cf.w);
        v_color = in_color;
        v_w = cf.w;
        v_side = fside;
        v_arc = in_arc;
        v_px = max(in_width * focal * half_vp.y / wf, min_px);
        v_brush = brush;
        v_light = 0.0;  // keine aufgemalte Lichtkante (liegt auf der Fläche); Schatten gilt
        v_tan = vec3(0.0);
        v_rad = 0.0;
        return;
    }
    float side = in_side / (1.0 + brush);
    vec4 c = vp * vec4(in_pos, 1.0);
    vec4 a = vp * vec4(in_prev, 1.0);
    vec4 b = vp * vec4(in_next, 1.0);
    float w = max(c.w, 1e-5);
    vec2 sc = c.xy / w * half_vp;
    vec2 d = b.xy / max(b.w, 1e-5) * half_vp - a.xy / max(a.w, 1e-5) * half_vp;
    if (length(d) < 1e-6) d = vec2(1.0, 0.0);
    vec2 n = normalize(vec2(-d.y, d.x));
    // Weltbreite -> Pixel (Perspektive macht ferne Striche dünner), mit Mindestbreite
    float px = max(in_width * focal * half_vp.y / w, min_px);
    vec2 s = sc + n * px * 0.5 * side;
    gl_Position = vec4(s / half_vp * w, c.z - bias * w, w);
    v_color = in_color;
    v_w = c.w;
    v_side = side;
    v_arc = in_arc;
    v_px = px;
    v_brush = brush;
    // Querrichtung des Strichs im Raum (senkrecht zu Strich und Blick), Vorzeichen wie die Bildschirmseite
    vec3 T = in_next - in_prev;
    T = length(T) > 1e-9 ? normalize(T) : vec3(1.0, 0.0, 0.0);
    v_tan = T;
    v_rad = in_width * 0.5;
    vec3 V = ortho > 0.5 ? view_back : normalize(eye - in_pos);
    vec3 B = cross(V, T);
    float bl = length(B);
    v_light = 0.0;
    if (bl > 1e-5) {
        B /= bl;
        vec4 cb = vp * vec4(in_pos + B * max(in_width, 1e-4), 1.0);
        vec2 sb = cb.xy / max(cb.w, 1e-5) * half_vp - sc;
        if (dot(sb, n) < 0.0) B = -B;
        v_light = dot(B, sun_dir);
    }
}
"""

OCCL_ACC_MESH_FS = """
#version 330
""" + OCCL_VIEW + OCCL_LIB + """
uniform vec4 owner;
uniform float acc_value;  // -log(1 - Deckkraft): Meshes voll (20), Flächen nach ihrem Regler
in vec3 v_world;
out float f_acc;
void main() {
    if (!front_here(v_world, owner)) discard;
    f_acc = acc_value;
}
"""

OCCL_MESH_FS = """
#version 330
""" + OCCL_VIEW + """
uniform float radius;
uniform float mesh_id;
const float OCCL_MIN_PX = 3.0;  // Spielraum mindestens so viele Pixel
in vec3 v_world;
out vec4 f_cover;
void main() {
    vec3 n = normalize(cross(dFdx(v_world), dFdy(v_world)));
    vec3 view = ortho > 0.5 ? view_back : normalize(eye - v_world);
    float d = ortho > 0.5 ? dot(eye - v_world, view_back) : length(v_world - eye);
    // Spielraum mindestens ein paar Pixel (in Welteinheiten hier): sonst verdeckt sich eine kleine oder ferne Fläche
    // im 3x3-Umfeld selbst und verschwindet beim Herauszoomen
    float px = length(fwidth(v_world));
    f_cover = vec4(d, abs(dot(n, view)), max(radius, OCCL_MIN_PX * px), mesh_id);
}
"""

# the same passes for surfaces: radius, id and opacity per surface from the surface table
OCCL_SURF_FS = OCCL_MESH_FS.replace("uniform float radius;\nuniform float mesh_id;\n", SURF_DATA + "flat in int v_slot;\n") \
    .replace("void main() {\n", "void main() {\n    float radius = surf(v_slot, 6).x;\n    float mesh_id = surf(v_slot, 5).z;\n")
OCCL_ACC_SURF_FS = OCCL_ACC_MESH_FS.replace("uniform vec4 owner;\nuniform float acc_value;", SURF_DATA + "flat in int v_slot;") \
    .replace("void main() {\n", "void main() {\n    vec4 owner = vec4(surf(v_slot, 5).z, -1.0, -1.0, -1.0);\n"
             "    float acc_value = surf(v_slot, 6).y;\n")
assert "v_slot" in OCCL_SURF_FS and "acc_value = surf" in OCCL_ACC_SURF_FS

# --- Mesh block: all imported meshes in one buffer (position included), per point the number of its part ---
# Per part three texels in the block table: 0 tint (rgba) · 1 (id, drawn, -, -) · 2 (picking number, triangle
# start high, low, -). Highlighting and hiding change only the table, not the buffer.
BLOCK_UNIT = 11  # texture unit of the block table
BLOCK_TAB = """
uniform sampler2D block_tab;
vec4 tab(int s, int j) { int k = s * 3 + j; return texelFetch(block_tab, ivec2(k % 1024, k / 1024), 0); }
"""
BLOCK_VS = """
#version 330
uniform mat4 mvp;
uniform int vis_col;  // 1: gezeichnet (Bild, Deckung, Schatten) · 2: in diesem Picking
in vec3 in_pos;
in vec3 in_color;
in float in_slot;
out vec3 v_world;
out vec3 v_color;
flat out int v_slot;
""" + BLOCK_TAB + """
void main() {
    v_slot = int(in_slot + 0.5);
    v_world = in_pos;
    v_color = in_color;
    bool shown = vis_col == 2 ? tab(v_slot, 2).x > 0.5 : tab(v_slot, 1).y > 0.5;
    gl_Position = shown ? mvp * vec4(in_pos, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);  // ausgeblendet: außerhalb, verworfen
}
"""
BLOCK_MESH_FS = MESH_FS.replace("uniform vec4 tint;\n", BLOCK_TAB + "flat in int v_slot;\n") \
    .replace("void main() {\n", "void main() {\n    vec4 tint = tab(v_slot, 0);\n", 1)
BLOCK_PICK_FS = PICK_FS.replace("uniform float mesh_index;\n", BLOCK_TAB + "flat in int v_slot;\n") \
    .replace("    f_out = vec4(v_world, mesh_index);\n    f_prim = float(gl_PrimitiveID);\n",
             "    vec4 t = tab(v_slot, 2);\n    f_out = vec4(v_world, t.x);\n"
             "    f_prim = float(gl_PrimitiveID - (int(t.y) * 65536 + int(t.z)));  // Dreieck im eigenen Mesh\n")
BLOCK_OCCL_FS = OCCL_MESH_FS.replace("uniform float mesh_id;\n", BLOCK_TAB + "flat in int v_slot;\n") \
    .replace("void main() {\n", "void main() {\n    float mesh_id = tab(v_slot, 1).x;\n", 1)
BLOCK_OCCL_ACC_FS = OCCL_ACC_MESH_FS.replace("uniform vec4 owner;\n", BLOCK_TAB + "flat in int v_slot;\n") \
    .replace("void main() {\n", "void main() {\n    vec4 owner = vec4(tab(v_slot, 1).x, -1.0, -1.0, -1.0);\n", 1)
assert "tab(v_slot, 0)" in BLOCK_MESH_FS and "t.x" in BLOCK_PICK_FS and "tab(v_slot, 1).x" in BLOCK_OCCL_FS \
    and "vec4 owner = vec4(tab" in BLOCK_OCCL_ACC_FS
BLOCK_MIN = 64  # from this many imported meshes a block is drawn instead of one per mesh
BLOCK_REBUILD = 64  # this many meshes outside the block (new, moved) -> rebuild as soon as nothing is being dragged

RIBBON_FS = """
#version 330
uniform float grain;
uniform float fade;  // < 1: verdeckte Striche (hinter ausgeblendeten Zeichenflächen) abgeschwächt
in vec4 v_color;
in float v_w;
in float v_side;
in float v_arc;
in float v_px;
in float v_brush;
in float v_light;
in vec3 v_wpos;
in vec3 v_tan;
in float v_rad;
uniform float light_on;
uniform vec3 sun_dir;
uniform vec3 sun_col;
uniform vec3 sky_col;
uniform float shadow_dark;
flat in vec4 v_owner;
out vec4 f_color;
""" + NOISE + SHADOW_LIB + OCCL_VIEW + OCCL_LIB + """
// Hilfsebenen tönen, was hinter ihnen liegt: Ebenen verdecken nichts und werden vor den Strichen gezeichnet – ohne das
// schienen Striche und Malerei dahinter ungetönt durch (Hafentest 09.11.). Je Ebene: liegt sie zwischen Auge und p
// (innerhalb ihres Rechtecks), wird die Farbe mit ihrer Füllfarbe gemischt (Deckkraft wie die Ebene selbst).
uniform int plane_n;
uniform vec3 plane_o[16];
uniform vec3 plane_u[16];  // halbe Kante in u (Welt)
uniform vec3 plane_v[16];  // halbe Kante in v (Welt)
uniform vec4 plane_c[16];  // Füllfarbe + Deckkraft
uniform float plane_k[16];  // Lasur der Ebene auf einer Fläche, 0: keine
uniform float plane_s[16];  // 1: unbeteiligte Ebene – auch vor einer Fläche nur die Lasur
vec3 plane_glaze(vec3 p, vec3 rgb) {
    vec3 e = ortho > 0.5 ? p + view_back * 1.0e6 : eye;
    vec3 d = p - e;
    for (int i = 0; i < plane_n; i++) {
        vec3 nrm = cross(plane_u[i], plane_v[i]);
        float den = dot(nrm, d);
        if (abs(den) < 1e-12) continue;
        vec3 q;       // wo der Sehstrahl die Ebene trifft
        bool behind;  // die Ebene liegt hier hinter dem Punkt
        if (ortho > 0.5) {
            // Auge im Unendlichen: Abstand entlang der Blickrichtung in Welteinheiten. (Über das ferne Ersatz-Auge
            // gerechnet galt jede Ebene näher als 100 Einheiten vor dem Strich als „nicht davor“ – in orthografischen
            // Ansichten tönten Ebenen die Striche dahinter praktisch nie.)
            float s = dot(nrm, plane_o[i] - p) / dot(nrm, view_back);
            q = p + view_back * s;
            behind = s <= 1e-3;
        } else {
            float t = dot(nrm, plane_o[i] - e) / den;
            if (t <= 0.0) continue;  // Ebene liegt hinter dem Auge
            q = e + d * t;
            behind = t >= 1.0 - 1e-4;
        }
        // … dann zählt sie nur, wo sie trotzdem über die Fläche gezeichnet ist: Taucht eine Ebene in eine Fläche ein,
        // lasiert sie die Fläche noch ein Stück weit (Spielraum der Deckungskarte). Malerei und Striche auf dieser
        // Fläche liegen dort VOR der Ebene und blieben ungetönt – sie fraßen sich als Flecken in den Rand der Ebene
        // (Artist 12.11.).
        // (gefragt wie die Ebene selbst: als fremde Zeichenhilfe mit einer id, die keine Fläche trägt – mit „keine id“
        // gälte der weite Spielraum für Unbekanntes, und Malerei würde auch über einer tief vergrabenen Ebene getönt)
        if (behind && (plane_k[i] <= 0.0 || !on_layer(q) || cover(q, vec4(1.0e9, -1.0, -1.0, -1.0)) < 0.5)) continue;
        vec3 x = q - plane_o[i];
        float a = dot(x, plane_u[i]) / max(dot(plane_u[i], plane_u[i]), 1e-12);
        float b = dot(x, plane_v[i]) / max(dot(plane_v[i], plane_v[i]), 1e-12);
        if (abs(a) <= 1.0 && abs(b) <= 1.0) {
            // so deckend wie die Ebene an dieser Stelle selbst gezeichnet ist (FLAT_FS): liegt sie hier auf einer
            // Fläche, nur ihre Lasur; davor voll – außer sie lasiert nicht (weder Zeichenebene noch gewählt), dann
            // weicht sie der Fläche. Sonst wäre Malerei hinter der Ebene anders getönt als die Fläche, auf der sie
            // liegt (fleckiger, „ausgefressener“ Rand), und eine unbeteiligte Ebene färbte nur die Striche um.
            float alpha = plane_c[i].a;
            if (behind || on_layer(q)) alpha = plane_k[i];
            else if (plane_k[i] <= 0.0) alpha *= 1.0 - front_opacity();
            else if (plane_s[i] > 0.5) alpha = mix(alpha, plane_k[i], front_opacity());
            rgb = mix(rgb, plane_c[i].rgb, alpha);
        }
    }
    return rgb;
}

uniform float edge_gain;  // Lichtkante: Linienfarbe um so viel heller (in Sonnenfarbe getönt)
vec3 light_edge(vec3 rgb) {
    // Licht-Modus: aufgemalte Lichtkante – ein schmaler, leicht gebrochener heller Saum an der Seite zur Sonne;
    // der Strich selbst bleibt flach wie gezeichnet
    if (light_on < 0.5) return rgb;
    float sh = band(in_shadow(v_wpos + sun_dir * shadow_lift));  // ein Stück zur Sonne: Linien auf Flächen nicht selbst verschattet
    if (sh > 0.5) return rgb * (1.0 - shadow_dark * sh) * mix(vec3(1.0), sky_col, sh);  // im Schatten: keine Kante
    float strength = smoothstep(0.12, 0.45, abs(v_light));
    float toward = v_side * sign(v_light);
    float thr = 0.3 + 0.18 * (hash12(floor(vec2(v_arc * 2.5, 9.0))) - 0.5);
    return toward > thr ? min(rgb * (1.0 + edge_gain * strength * sun_col), vec3(1.0)) : rgb;
}
void main() {
    if (v_w <= 0.0) discard;  // hinter der Kamera
    // Verdeckung an der Oberfläche einer gedachten Röhre statt an der Mittellinie: ein dicker Strich durch eine Fläche
    // wird rund (als Ellipse) geschnitten, nicht an einer geraden Kante quer übers Band (Hafentest 09.11.)
    vec3 p = v_wpos;
    if (v_rad > 0.0 && length(v_tan) > 0.5) {
        vec3 V = ortho > 0.5 ? view_back : normalize(eye - v_wpos);
        vec3 np = V - dot(V, v_tan) * v_tan;
        float nl = length(np);
        if (nl > 1e-5) {
            np /= nl;
            float s = clamp(v_side, -1.0, 1.0);
            p = v_wpos + v_rad * (sqrt(max(1.0 - s * s, 0.0)) * np + s * cross(v_tan, np));
        }
    }
    float vis = cover(p, v_owner);  // hinter Flächen/Meshes: weg (X-Ray: sanft)
    if (vis <= 0.0) discard;
    float k = vis >= 1.0 ? fade : vis * fade;
    if (v_brush > 0.5) {
        // Ölpinsel: Borsten-Streifen entlang des Strichs, ausfransende Ränder, Farbe mal satt, mal trockener
        float across = v_side * 0.5 + 0.5;
        float bristle = vnoise(vec2(across * 7.0, v_arc * 0.06));          // Borsten-Rillen entlang des Strichs
        float fine = hash12(floor(vec2(across * 26.0, v_arc * 0.5)));       // einzelne Borsten
        float fray = smoothstep(0.45, 1.0, abs(v_side) + 0.45 * (vnoise(vec2(v_arc * 0.9, 5.0)) - 0.5));
        float dry = smoothstep(0.45, 0.85, vnoise(vec2(v_arc * 0.16, across * 2.5 + 11.0)));  // trockener Pinsel
        float gaps = fray * 0.9 + dry * 0.55 * fine;
        gaps *= smoothstep(1.2, 3.5, v_px);  // sehr dünne Striche nicht zerlöchern
        if (gaps > 0.4 + 0.3 * fine) discard;
        float ridge = 0.72 + 0.45 * bristle + 0.12 * (fine - 0.5);       // Farbe in den Rillen dunkler, auf den Graten heller
        vec3 oil = clamp(v_color.rgb * ridge + 0.06 * (bristle - 0.5), 0.0, 1.0);
        // Deckkraft > 1 = Farbe der Oberfläche (Auswahl, Hover): immer in voller Leuchtkraft – weder Licht und
        // Schatten noch die Tönung einer Hilfsebene davor dürfen sie verdunkeln (sonst ist Gewähltes nicht zu erkennen)
        f_color = vec4(v_color.a > 1.5 ? oil : plane_glaze(v_wpos, light_edge(oil)), min(v_color.a, 1.0) * k);
        return;
    }
    // Bleistift: Grafit bleibt nur an den "Zähnen" des Papiers hängen. Körnung in Strich-Koordinaten
    // (entlang: Bogenlänge, quer: Seite), zu den Rändern hin lückenhafter. Lücken statt Transparenz:
    // so werden Kreuzungen dichter und dunkler, und das zweite Zeichnen der Striche ändert nichts.
    float edge = abs(v_side);
    // Grafit-Streifen entlang der Strichrichtung: längliche Zellen (lang entlang, schmal quer)
    float streak = hash12(floor(vec2(v_arc * 1.4, (v_side + 1.0) * 2.5)));
    float tooth = hash12(floor(vec2(v_arc * 5.0, (v_side + 1.0) * 3.0)) + 31.0);
    float pressure = vnoise(vec2(v_arc * 0.35, 3.0));  // Druck schwankt entlang des Strichs
    float holes = (mix(0.07, 0.38, smoothstep(0.3, 1.0, edge)) + 0.06 * (0.5 - pressure)) * grain;
    holes *= smoothstep(1.2, 3.5, v_px);  // sehr dünne Striche nicht zerlöchern
    if (streak * 0.55 + tooth * 0.45 < holes) discard;
    float shade = 0.94 + 0.12 * (1.0 - pressure) + 0.1 * (streak - 0.5);
    vec3 graphite = min(v_color.rgb * shade, vec3(1.0));
    f_color = vec4(v_color.a > 1.5 ? graphite : plane_glaze(v_wpos, light_edge(graphite)), min(v_color.a, 1.0) * k);
}
"""


SURFACE_VS = """
#version 330
uniform mat4 vp;
uniform float bias;  // < 0: minimal nach hinten (Tiefen-Durchgang)
uniform int occluders_only;  // 1 (Deckungskarte): Hilfsflächen verdecken nichts – ihre Ecken fallen aus dem Bild
""" + SURF_DATA + """
in vec3 in_pos;
in vec3 in_normal;  // geglättete Normale (unter flachem Blick milchiger)
in vec3 in_calm;    // stark geglättete Normale: nur fürs Licht mit Licht-Stufen (kleine Wellen ohne Stufenkanten)
in float in_slot;   // Nummer der Fläche in der Flächen-Tabelle
out vec3 v_world;
out vec3 v_normal;
out vec3 v_calm;
flat out int v_slot;
void main() {
    int slot = int(in_slot + 0.5);
    v_slot = slot;
    vec3 p = in_pos;
    v_normal = in_normal;
    v_calm = in_calm;
    if (occluders_only == 1 && surf(slot, 6).z < 0.5) {
        v_world = p;
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        return;
    }
    if (surf(slot, 5).w > 0.5) {  // starr mitgetragen (Gizmo-Zug): Netz vom Zugbeginn mal Lage-Matrix
        // nur Drehung/gleichmäßige Skalierung: Normalen mitdrehen, Länge wie vorher
        mat4 model = transpose(mat4(surf(slot, 7), surf(slot, 8), surf(slot, 9), vec4(0.0, 0.0, 0.0, 1.0)));
        mat3 r = mat3(model);
        p = (model * vec4(in_pos, 1.0)).xyz;
        v_normal = normalize(r * in_normal) * length(in_normal);
        v_calm = normalize(r * in_calm) * length(in_calm);
    }
    v_world = p;
    vec4 c = vp * vec4(p, 1.0);
    gl_Position = vec4(c.xy, c.z - bias * c.w, c.w);
}
"""

CAP_VS = """
#version 330
uniform mat4 vp;
uniform vec2 half_vp;
uniform float focal;
uniform float min_px;
uniform float bias;
in vec3 in_pos;
in float in_width;
in vec4 in_color;
out vec4 v_color;
out float v_w;
out float v_seed;
out float v_px;
out vec3 v_wpos;
in vec4 in_owner;
flat out vec4 v_owner;
in float in_style;     // 2: Pinsel
flat out float v_brush;
in vec3 in_normal;     // Malstrich: Flächennormale (sonst 0)
in float in_layer;
flat out float v_flat;
flat out mat2 v_inv;   // Malstrich: Bildschirm-Pixel -> Koordinaten der flachen Scheibe
flat out float v_size;
void main() {
    v_wpos = in_pos;
    v_owner = in_owner;
    v_brush = step(1.5, in_style);
    vec4 c = vp * vec4(in_pos, 1.0);
    float w = max(c.w, 1e-5);
    v_flat = 0.0;
    v_inv = mat2(1.0);
    gl_PointSize = max(in_width * focal * half_vp.y / w, min_px);
    gl_Position = vec4(c.xy, c.z - bias * c.w, c.w);
    if (length(in_normal) > 0.5) {
        // Malstrich: rundes Ende flach in der Fläche – im Bild eine Ellipse (Punkt-Sprite deckt sie ab)
        vec3 N = normalize(in_normal);
        vec3 U = normalize(cross(N, abs(N.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
        vec3 W = cross(N, U);
        float r = in_width * 0.5;
        vec2 s0 = c.xy / w * half_vp;
        vec4 cu = vp * vec4(in_pos + U * r, 1.0);
        vec4 cw = vp * vec4(in_pos + W * r, 1.0);
        vec2 a = cu.xy / max(cu.w, 1e-5) * half_vp - s0;
        vec2 b = cw.xy / max(cw.w, 1e-5) * half_vp - s0;
        mat2 m = mat2(a, b);
        v_flat = abs(determinant(m)) > 1e-6 ? 1.0 : 0.0;
        v_inv = v_flat > 0.5 ? inverse(m) : mat2(1.0);
        gl_PointSize = 2.0 * sqrt(dot(a, a) + dot(b, b)) + 2.0;
        gl_Position = vec4(c.xy, (0.9 - 1.8 * in_layer) * c.w, c.w);
    }
    v_size = gl_PointSize;
    v_color = in_color;
    v_w = c.w;
    v_seed = fract(dot(in_pos, vec3(12.9898, 78.233, 37.719)));
    v_px = gl_PointSize;
}
"""

CAP_FS = """
#version 330
uniform float grain;
uniform float fade;  // < 1: verdeckte Striche (hinter ausgeblendeten Zeichenflächen) abgeschwächt
in vec4 v_color;
in float v_w;
in float v_seed;
in float v_px;
in vec3 v_wpos;
flat in vec4 v_owner;
flat in float v_brush;
flat in float v_flat;
flat in mat2 v_inv;
flat in float v_size;
out vec4 f_color;
uniform float light_on;
uniform vec3 sun_dir;
uniform vec3 sky_col;
uniform float shadow_dark;
""" + NOISE + SHADOW_LIB + OCCL_VIEW + OCCL_LIB + """
// Hilfsebenen tönen, was hinter ihnen liegt: Ebenen verdecken nichts und werden vor den Strichen gezeichnet – ohne das
// schienen Striche und Malerei dahinter ungetönt durch (Hafentest 09.11.). Je Ebene: liegt sie zwischen Auge und p
// (innerhalb ihres Rechtecks), wird die Farbe mit ihrer Füllfarbe gemischt (Deckkraft wie die Ebene selbst).
uniform int plane_n;
uniform vec3 plane_o[16];
uniform vec3 plane_u[16];  // halbe Kante in u (Welt)
uniform vec3 plane_v[16];  // halbe Kante in v (Welt)
uniform vec4 plane_c[16];  // Füllfarbe + Deckkraft
uniform float plane_k[16];  // Lasur der Ebene auf einer Fläche, 0: keine
uniform float plane_s[16];  // 1: unbeteiligte Ebene – auch vor einer Fläche nur die Lasur
vec3 plane_glaze(vec3 p, vec3 rgb) {
    vec3 e = ortho > 0.5 ? p + view_back * 1.0e6 : eye;
    vec3 d = p - e;
    for (int i = 0; i < plane_n; i++) {
        vec3 nrm = cross(plane_u[i], plane_v[i]);
        float den = dot(nrm, d);
        if (abs(den) < 1e-12) continue;
        vec3 q;       // wo der Sehstrahl die Ebene trifft
        bool behind;  // die Ebene liegt hier hinter dem Punkt
        if (ortho > 0.5) {
            // Auge im Unendlichen: Abstand entlang der Blickrichtung in Welteinheiten. (Über das ferne Ersatz-Auge
            // gerechnet galt jede Ebene näher als 100 Einheiten vor dem Strich als „nicht davor“ – in orthografischen
            // Ansichten tönten Ebenen die Striche dahinter praktisch nie.)
            float s = dot(nrm, plane_o[i] - p) / dot(nrm, view_back);
            q = p + view_back * s;
            behind = s <= 1e-3;
        } else {
            float t = dot(nrm, plane_o[i] - e) / den;
            if (t <= 0.0) continue;  // Ebene liegt hinter dem Auge
            q = e + d * t;
            behind = t >= 1.0 - 1e-4;
        }
        // … dann zählt sie nur, wo sie trotzdem über die Fläche gezeichnet ist: Taucht eine Ebene in eine Fläche ein,
        // lasiert sie die Fläche noch ein Stück weit (Spielraum der Deckungskarte). Malerei und Striche auf dieser
        // Fläche liegen dort VOR der Ebene und blieben ungetönt – sie fraßen sich als Flecken in den Rand der Ebene
        // (Artist 12.11.).
        // (gefragt wie die Ebene selbst: als fremde Zeichenhilfe mit einer id, die keine Fläche trägt – mit „keine id“
        // gälte der weite Spielraum für Unbekanntes, und Malerei würde auch über einer tief vergrabenen Ebene getönt)
        if (behind && (plane_k[i] <= 0.0 || !on_layer(q) || cover(q, vec4(1.0e9, -1.0, -1.0, -1.0)) < 0.5)) continue;
        vec3 x = q - plane_o[i];
        float a = dot(x, plane_u[i]) / max(dot(plane_u[i], plane_u[i]), 1e-12);
        float b = dot(x, plane_v[i]) / max(dot(plane_v[i], plane_v[i]), 1e-12);
        if (abs(a) <= 1.0 && abs(b) <= 1.0) {
            // so deckend wie die Ebene an dieser Stelle selbst gezeichnet ist (FLAT_FS): liegt sie hier auf einer
            // Fläche, nur ihre Lasur; davor voll – außer sie lasiert nicht (weder Zeichenebene noch gewählt), dann
            // weicht sie der Fläche. Sonst wäre Malerei hinter der Ebene anders getönt als die Fläche, auf der sie
            // liegt (fleckiger, „ausgefressener“ Rand), und eine unbeteiligte Ebene färbte nur die Striche um.
            float alpha = plane_c[i].a;
            if (behind || on_layer(q)) alpha = plane_k[i];
            else if (plane_k[i] <= 0.0) alpha *= 1.0 - front_opacity();
            else if (plane_s[i] > 0.5) alpha = mix(alpha, plane_k[i], front_opacity());
            rgb = mix(rgb, plane_c[i].rgb, alpha);
        }
    }
    return rgb;
}

vec3 cap_light(vec3 rgb) {
    // Licht-Modus: Schatten genau wie das Band am letzten Linienpunkt (v_wpos ist dieser Punkt) – die Kappe hat
    // dieselbe Helligkeit wie das Linienstück daneben, egal wie sie zur Kamera steht
    if (light_on < 0.5) return rgb;
    float sh = band(in_shadow(v_wpos + sun_dir * shadow_lift));
    if (sh > 0.5) return rgb * (1.0 - shadow_dark * sh) * mix(vec3(1.0), sky_col, sh);
    return rgb;
}
void main() {
    float vis = cover(v_wpos, v_owner);
    if (vis <= 0.0) discard;
    // runde Strichenden: Kreis im Punkt-Sprite (Malstrich: flache Scheibe in der Fläche), Rand gekörnt wie der Strich
    vec2 q = gl_PointCoord * 2.0 - 1.0;
    if (v_flat > 0.5) {
        vec2 px = (gl_PointCoord - 0.5) * v_size;
        q = v_inv * vec2(px.x, -px.y);  // Punkt-Sprite zählt y nach unten
    }
    float r = length(q);
    if (r > 1.0 || v_w <= 0.0) discard;
    if (v_brush > 0.5) {
        // Pinsel-Ende: rund wie beim Stift, aber mit ausfransendem Rand und Borsten-Struktur wie der Strich
        float ang = atan(q.y, q.x);
        float fray = vnoise(vec2(ang * 2.2 + v_seed * 40.0, 3.0));
        if (r > 0.72 + 0.2 * fray * smoothstep(1.2, 3.5, v_px)) discard;  // so breit wie der ausfransende Strich
        float bristle = vnoise(q * 3.5 + v_seed * 17.0);
        vec3 rgb = clamp(v_color.rgb * (0.78 + 0.4 * bristle), 0.0, 1.0);
        f_color = vec4(v_color.a > 1.5 ? rgb : plane_glaze(v_wpos, cap_light(rgb)),
                       min(v_color.a, 1.0) * (vis >= 1.0 ? fade : vis * fade));
        return;
    }
    float fine = hash12(floor(vec2(q.x * 2.5, (q.y + 1.0) * 3.0)) + v_seed * 97.0);  // Körnung so fein wie im Strich
    float holes = mix(0.07, 0.38, smoothstep(0.3, 1.0, r)) * grain * smoothstep(1.2, 3.5, v_px);
    if (fine < holes) discard;
    f_color = vec4(v_color.a > 1.5 ? v_color.rgb : plane_glaze(v_wpos, cap_light(v_color.rgb)),
                   min(v_color.a, 1.0) * (vis >= 1.0 ? fade : vis * fade));
}
"""

MATERIAL_LIB = """
// Materialien der Flächen (nur Darstellung): nahtlos und prozedural, triplanar projiziert. p in Textur-Einheiten,
// fw = Größe eines Pixels darin (Details unter einem Pixel werden ausgeblendet, sonst flimmert es). Alle hell/weißlich.
float fbm2(vec2 p) {
    return vnoise(p) * 0.5 + vnoise(p * 2.03 + 7.1) * 0.25 + vnoise(p * 4.01 + 3.7) * 0.125 + vnoise(p * 8.07 + 1.3) * 0.0625;
}
float fbm3(vec3 p) {
    return vnoise3(p) * 0.5 + vnoise3(p * 2.03 + 7.1) * 0.25 + vnoise3(p * 4.01 + 3.7) * 0.125 + vnoise3(p * 8.07 + 1.3) * 0.0625;
}
float fade_px(float feature, float fw) { return 1.0 - smoothstep(0.35, 1.0, fw / max(feature, 1e-6)); }
// Papier (gekörntes Aquarellpapier): weiche Buckel, von oben links beleuchtet, feiner Zahn
vec3 m_papier(vec2 p, float fw) {
    float s = 22.0;
    float e = 0.35 / s;
    float h0 = fbm2(p * s), hx = fbm2((p + vec2(e, 0.0)) * s), hy = fbm2((p + vec2(0.0, e)) * s);
    float relief = ((h0 - hx) + (h0 - hy)) * 2.2 * fade_px(1.0 / s, fw);
    float tooth = (vnoise(p * 140.0) - 0.5) * fade_px(1.0 / 140.0, fw);
    float t = (0.968 + relief * 0.05 + tooth * 0.015 + (vnoise(p * 1.1) - 0.5) * 0.01) * 0.91;  // etwas dunkler als Weiß (Artist: 70 % zurück von 0.7)
    return vec3(t, t * 0.997, t * 0.99);
}
// Stoff (Leinen): Kett- und Schussfäden in Leinwandbindung, einzelne Fäden dicker oder dünner (Noppen)
vec3 m_stoff(vec2 p, float fw) {
    float f = 45.0;
    vec2 q = p * f;
    float k = fade_px(1.0 / f, fw);
    vec2 cell = floor(q), fr = fract(q);
    float thick_u = 0.75 + 0.5 * vnoise(vec2(cell.x * 2.3, p.y * 2.5));   // Faden über seine Länge ungleich
    float thick_v = 0.75 + 0.5 * vnoise(vec2(p.x * 2.5, cell.y * 1.9 + 50.0));
    float warp = 1.0 - pow(abs(fr.x - 0.5) * 2.0, 2.0 / thick_u);          // Fadenmitte hell, Fuge dunkel
    float weft = 1.0 - pow(abs(fr.y - 0.5) * 2.0, 2.0 / thick_v);
    float over = mod(cell.x + cell.y, 2.0);                                  // oben liegt abwechselnd Kette/Schuss
    float thread = mix(warp * (0.85 + 0.15 * weft), weft * (0.85 + 0.15 * warp), over);
    float slub = (vnoise(vec2(cell.x * 0.7, p.y * 0.8)) + vnoise(vec2(p.x * 0.8, cell.y * 0.7 + 9.0))) * 0.5 - 0.5;
    float t = 0.968 - (1.0 - thread) * 0.06 * k + slub * 0.03 * k + (fbm2(p * 1.5) - 0.5) * 0.015;
    return vec3(t, t, t * 0.994);
}
// Finnpappe: hell, leicht bräunlich, kurze krause Fasern, wolkig, vereinzelt dunkle Einschlüsse
vec3 m_pappe(vec2 p, float fw) {
    // Fasern: Rauschen, dessen Richtung selbst langsam wandert (keine sichtbare Schraffur)
    float ang = fbm2(p * 6.0) * 6.2832;
    vec2 d = vec2(cos(ang), sin(ang));
    vec2 r = vec2(dot(p, d), dot(p, vec2(-d.y, d.x)));
    float fib = (vnoise(r * vec2(150.0, 22.0)) - 0.5) * fade_px(1.0 / 150.0, fw);
    float fine = (vnoise(p * 220.0) - 0.5) * fade_px(1.0 / 220.0, fw);
    float cloud = fbm2(p * 2.5) - 0.5;
    vec2 cell = floor(p * 30.0);
    vec2 jitter = vec2(hash12(cell + 3.1), hash12(cell + 7.7)) - 0.5;
    float speck = step(0.993, hash12(cell)) * (1.0 - smoothstep(0.05, 0.16, length(fract(p * 30.0) - 0.5 - jitter * 0.6)));
    speck *= fade_px(1.0 / 30.0, fw);
    float light_fib = smoothstep(0.7, 0.9, vnoise(r.yx * vec2(120.0, 16.0) + 3.0)) * fade_px(1.0 / 120.0, fw);
    float t = 1.0 + fib * 0.13 + fine * 0.05 + light_fib * 0.035 + cloud * 0.05 - speck * 0.3;
    return vec3(0.94, 0.905, 0.85) * t;
}
// Holz: hell, feine dichte Maserung längs (leicht wellig), dunklere schmale Linien, Poren
vec3 m_holz(vec2 p, float fw) {
    float warp = fbm2(p * vec2(0.35, 0.08)) * 2.5 + fbm2(p * vec2(1.5, 0.3)) * 0.35;
    float x = p.x * 16.0 + warp * 4.0;
    float line = 1.0 - smoothstep(0.0, 0.09, abs(fract(x) - 0.5) * 2.0 - 0.0);   // schmale Linie je Jahresring
    line *= 0.5 + 0.5 * vnoise(vec2(floor(x) * 3.1, p.y * 1.5));                // mal deutlicher, mal kaum
    float pores = (vnoise(p * vec2(160.0, 7.0)) - 0.5) * fade_px(1.0 / 160.0, fw);
    float band = fbm2(vec2(x * 0.15, p.y * 0.1)) - 0.5;                           // breite helle/dunkle Zonen
    float t = 1.0 - line * 0.07 * fade_px(1.0 / 16.0, fw) + pores * 0.04 + band * 0.04;
    return vec3(0.955, 0.915, 0.855) * t;
}
// Sprühfarbe, malerisch: ausgefranste Farbinseln und Sprenkel mit harten Kanten, in wenigen Tonstufen (stilisiert,
// kaum Verläufe), dazu rauhes Korn. Die Kanten sind über ein verzerrtes Raster unruhig wie gemalt
vec3 m_spruehfarbe(vec2 p, float fw) {
    vec2 warp = vec2(fbm2(p * 3.1), fbm2(p * 3.1 + 17.3)) - 0.5;
    vec2 q = p + warp * 0.2;
    float edge = clamp(fw * 6.0, 0.004, 0.08);                    // Kantenbreite: hart, aber ohne Treppen
    float islands = smoothstep(0.5 - edge, 0.5 + edge, fbm2(q * 1.8));              // große satte/dünne Inseln
    float patches = smoothstep(0.56 - edge, 0.56 + edge, fbm2(q * 6.5 + 5.0));      // mittlere Flecken
    float k1 = fade_px(1.0 / 48.0, fw), k2 = fade_px(1.0 / 110.0, fw);
    float speck = smoothstep(0.71 - edge, 0.71 + edge, vnoise(q * 48.0 + 2.0)) * k1;   // Sprenkel
    float fine = smoothstep(0.78 - edge, 0.78 + edge, vnoise(q * 110.0 + 9.0)) * k2;   // feine Sprenkel
    float tone = islands * 0.3 + patches * 0.3 + speck * 0.25 + fine * 0.15;
    tone = floor(tone * 4.0 + 0.5) / 4.0;                         // vier Tonstufen: stilisiert statt Verlauf
    float rough = (vnoise(q * vec2(150.0, 38.0)) + vnoise(q * vec2(38.0, 150.0) + 4.0) - 1.0) * k2;
    float t = 0.95 - tone * 0.17 + rough * 0.025;
    return vec3(t * 0.995, t, t * 1.005);
}

// Größe der Strukturen je Material (Papier = 1): die anderen gröber, damit alle in derselben Größenordnung leben
const float MAT_SCALE[5] = float[5](1.0, 0.45, 0.4, 0.5, 0.35);
// Helligkeit je Material: alle haben im Mittel dieselbe Luminanz wie das Papier (gemessen, Artist)
const float MAT_GAIN[5] = float[5](1.0, 0.9325, 0.9664, 0.957, 0.976);  // Sprühfarbe nach den Tonstufen neu gemessen
// Flecken je Material: nur Papier, Pappe und Sprühfarbe (nicht Stoff, nicht Holz)
const float MAT_STAIN[5] = float[5](1.0, 0.0, 1.0, 0.0, 1.0);
vec3 material2(int m, vec2 p, float fw) {
    int i = clamp(m, 0, 4);
    float k = MAT_SCALE[i];
    p *= k;
    fw *= k;
    vec3 c;
    if (m == 1) c = m_stoff(p, fw);
    else if (m == 2) c = m_pappe(p, fw);
    else if (m == 3) c = m_holz(p, fw);
    else if (m == 4) c = m_spruehfarbe(p, fw);
    else c = m_papier(p, fw);
    return c * MAT_GAIN[i];
}
// Tonstufen (Artist): die Struktur der Materialien wirkt abgestuft wie die Licht-Stufen, nicht als feiner Verlauf –
// die Helligkeit springt in Schritten von TONE_STEP
const float TONE_STEP = 0.022;
vec3 tone_steps(vec3 c) {
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float q = (floor(l / TONE_STEP) + 0.5) * TONE_STEP;
    return c * (q / max(l, 1e-4));
}
vec3 material_triplanar(int m, vec3 q, vec3 n, float fw) {
    vec3 w = pow(abs(n), vec3(6.0));
    w /= max(w.x + w.y + w.z, 1e-6);
    vec3 c = vec3(0.0);
    if (w.x > 0.01) c += material2(m, q.zy, fw) * w.x;
    if (w.y > 0.01) c += material2(m, q.xz + 13.7, fw) * w.y;
    if (w.z > 0.01) c += material2(m, q.xy + 29.3, fw) * w.z;
    return c / max(w.x * float(w.x > 0.01) + w.y * float(w.y > 0.01) + w.z * float(w.z > 0.01), 1e-6);
}
// Flecken über allen Materialien (wie Wasser-/Kaffeeflecken): großflächig, mit dunklerem Rand. 3D-Rauschen im
// Texturraum der Fläche: jede Fläche ein eigenes Stück (Versatz), keine Nähte
vec3 stains(vec3 q, float strength) {
    if (strength <= 0.0) return vec3(1.0);
    float s = fbm3(q * 0.3);
    float body = smoothstep(0.5225, 0.6075, s);  // Flächenanteil ~19 % (30 % weniger als zuvor 28 %)
    float rim = smoothstep(0.5025, 0.5275, s) * (1.0 - smoothstep(0.5325, 0.5825, s));  // Rand etwas dunkler (Trockenrand)
    float mottled = fbm3(q * 1.3 + 31.0);
    float k = (body * (0.5 + 0.5 * mottled) * 0.12 + rim * 0.09) * strength;
    return mix(vec3(1.0), vec3(0.80, 0.70, 0.55), k);
}
"""

MATERIAL_FS = """
#version 330
// je Fläche, aus der Flächen-Tabelle (load_surface, als Erstes in main):
int material;
vec3 tint;          // Färbung (weiß = Material wie es ist)
vec3 anchor;        // Bezugspunkt der Fläche: verschiebt man sie, wandert die Textur mit
vec3 offset;        // Zufalls-Versatz je Fläche (Textur-Einheiten)
float tex_scale;    // Welteinheiten je Textur-Einheit (global, etwas mit der Flächengröße)
vec4 state;         // Zustand: Farbe + Stärke (aktiv, gewählt, Flächenmodus)
float grid_step;    // Raster der aktiven Zeichenfläche (Welteinheiten, 0 = keins)
float grid_alpha;
vec3 grid_color;
float opacity;      // Deckkraft der Fläche (Regler im Outliner)
vec4 owner;
float lift;         // Schatten-Prüfpunkt so weit von der Fläche weg (Welteinheiten)
flat in int v_slot;
uniform float lift_min;     // … mindestens so weit (ein paar Texel der Schattenkarte)
uniform float stain;        // Stärke der Flecken
uniform float layer;        // 0: Verdecktes (X-Ray), 1: vorderste Schicht
uniform float front_alpha;  // Deckkraft der vordersten Schicht (1, X-Ray: Regler)
uniform float mono;
uniform float light_on;
uniform vec3 sun_dir;
uniform vec3 sun_col;
uniform vec3 sky_col;
uniform float away_dark;
uniform float shadow_dark;
uniform float calm;         // Anteil der stark geglätteten Normale am Licht (mit Licht-Stufen, sonst 0)
in vec3 v_world;
in vec3 v_normal;
in vec3 v_calm;
out vec4 f_color;
""" + SURF_DATA + NOISE + PAPER_LIB + MATERIAL_LIB + SHADOW_LIB + OCCL_VIEW + OCCL_LIB + """
void load_surface() {
    vec4 a = surf(v_slot, 0), b = surf(v_slot, 1), c = surf(v_slot, 2), d = surf(v_slot, 4), e = surf(v_slot, 5);
    tint = a.rgb; material = int(a.a + 0.5);
    anchor = b.xyz; tex_scale = b.w;
    offset = c.xyz; grid_step = c.w;
    state = surf(v_slot, 3);
    grid_color = d.rgb; grid_alpha = d.a;
    lift = max(e.x, lift_min); opacity = e.y;
    owner = vec4(e.z, -1.0, -1.0, -1.0);
}
void main() {
    load_surface();
    // Ableitungen vor jedem discard (danach sind sie in den Nachbarpixeln undefiniert); entartet die Normale am Rand
    // (Länge 0), gilt die geglättete
    vec3 vn = length(v_normal) > 1e-9 ? normalize(v_normal) : vec3(0.0, 1.0, 0.0);
    vec3 cr = cross(dFdx(v_world), dFdy(v_world));
    vec3 n_geo = length(cr) > 1e-20 ? normalize(cr) : vn;
    vec3 q = (v_world - anchor) / tex_scale + offset;
    float fw = min(length(fwidth(q)), 1e3);
    vec3 g = v_world / max(grid_step, 1e-9);
    vec3 gw = max(fwidth(g), vec3(1e-6));
    float vis = cover_edge(v_world, owner);  // dahinter: weg (X-Ray: sanft); am Umriss davor: Tiefentest
    bool front = vis >= 1.0;
    if (front != (layer > 0.5) || vis <= 0.0) discard;
    vec3 view = ortho > 0.5 ? view_back : normalize(eye - v_world);
    vec3 c = tone_steps(material_triplanar(material, q, n_geo, fw) * stains(q, stain * MAT_STAIN[clamp(material, 0, 4)]))
             * tint;
    vec3 nrm = vn;
    if (dot(nrm, view) < 0.0) nrm = -nrm;  // die Seite, die man sieht
    float facing = abs(dot(nrm, view));
    if (light_on > 0.5) {
        // mit Licht-Stufen: die großen Formen schattieren, nicht jede kleine Welle der Netzfläche (sonst Tarnmuster)
        vec3 cn = length(v_calm) > 1e-9 ? normalize(v_calm) : nrm;
        if (dot(cn, nrm) < 0.0) cn = -cn;
        vec3 ln = normalize(mix(nrm, cn, calm));
        float nl = dot(ln, sun_dir);
        float k = band(smoothstep(-0.25, 0.9, nl));
        float sh = band(in_shadow(v_world + (nl >= 0.0 ? ln : -ln) * lift + sun_dir * lift));
        float lit = min(mix(1.0 - away_dark, 1.0, k), 1.0 - shadow_dark * sh);
        c *= sun_and_sky(ln, lit, sky_col) * mix(sky_col, sun_col, k * (1.0 - sh));
    } else {
        c *= 0.9 + 0.1 * facing;  // dezent: schräg gesehene Flächen etwas dunkler (Form bleibt lesbar)
    }
    if (grid_step > 0.0 && grid_alpha > 0.0) {  // aktive Zeichenfläche: Raster
        vec3 dist = abs(fract(g - 0.5) - 0.5) / gw;
        vec3 w = pow(abs(n_geo), vec3(4.0));
        w /= max(w.x + w.y + w.z, 1e-6);
        float lx = 1.0 - min(min(dist.y, dist.z), 1.0);
        float ly = 1.0 - min(min(dist.x, dist.z), 1.0);
        float lz = 1.0 - min(min(dist.x, dist.y), 1.0);
        c = mix(c, grid_color, (w.x * lx + w.y * ly + w.z * lz) * grid_alpha);
    }
    c = mix(c, state.rgb, state.a);
    vec3 lw = vec3(0.2126, 0.7152, 0.0722);
    c = mix(c, vec3(dot(c, lw)), mono);
    f_color = vec4(c, (front ? front_alpha : vis) * opacity);
}
"""


_NORMALS_CACHE = {}  # id(vertices) -> (vertices, normals): drawing surfaces come cached


def _smooth_normals(verts, tris):
    """Smoothed normals per point (mean of the adjacent triangles) - curved drawing surfaces
    become evenly milkier under a flat view instead of faceted."""
    hit = _NORMALS_CACHE.get(id(verts))
    if hit is not None and hit[0] is verts:
        return hit[1]
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    face = np.cross(b - a, c - a)
    normals = np.zeros_like(verts, dtype=float)
    for k in range(3):
        np.add.at(normals, tris[:, k], face)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    lru.trim(_NORMALS_CACHE, 8192)
    _NORMALS_CACHE[id(verts)] = (verts, normals)
    return normals


def _vertex_normals(verts, tris):
    """Simply averaged normal per point (area-weighted) - fast, for surfaces currently deforming in a drag."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    face = np.cross(b - a, c - a)
    flat = tris.reshape(-1)
    normals = np.empty((len(verts), 3))
    for ax in range(3):
        normals[:, ax] = np.bincount(flat, weights=np.repeat(face[:, ax], 3), minlength=len(verts))
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    return normals


from .components import SHARP_FROM_DEG as CREASE_FROM_DEG, SHARP_FULL_DEG as CREASE_FULL_DEG  # noqa: E402 – like the hardness


def _rigid_rotation(old, new, tol=1e-5):
    """Rotation R if new = s·R·old + t for ALL points (rigid motion, uniform scaling, no mirroring),
    otherwise None. Fast (one matrix fit, one check over all points) - cheaper than recomputing normals."""
    old, new = np.asarray(old, float), np.asarray(new, float)
    if old.shape != new.shape or len(old) < 3:
        return None
    co, cn = old.mean(axis=0), new.mean(axis=0)
    a, b = old - co, new - cn
    size = float(np.sqrt((a * a).sum(axis=1).max()))
    if size < 1e-12:
        return None
    u, sv, vt = np.linalg.svd(b.T @ a)
    if sv[1] <= 1e-9 * max(sv[0], 1e-30):
        return None  # points on a line: rotation about the line undetermined - recompute
    d = np.ones(3)
    d[2] = 1.0 if np.linalg.det(u @ vt) > 0 else -1.0  # Kabsch: never mirror (flat shapes: normal unambiguous)
    rot = (u * d) @ vt
    s = float((sv * d).sum() / max((a * a).sum(), 1e-30))
    if s <= 0:
        return None
    err = np.abs(b - s * (a @ rot.T)).max()  # mirrored shapes fall through here (winding) and are recomputed
    return rot if err <= tol * size * max(s, 1.0) else None


PARALLEL_MIN = 4  # from this many new shapes the thread pool pays off
_POOL = []


def _pool():
    """Shared thread pool for independent numpy computations per shape (created once)."""
    if not _POOL:
        import os
        from concurrent.futures import ThreadPoolExecutor
        _POOL.append(ThreadPoolExecutor(max_workers=max(2, min(16, (os.cpu_count() or 4)))))
    return _POOL[0]


def _corner_normals(verts, tris):
    """Normals per triangle corner (T, 3, 3) and how strongly the corner lies on a fold (T, 3): only the
    triangles at the point that face a similar direction are averaged - fully up to 15° kink, not at all from 45°, in between
    proportionally (like hardness). A hard fold thus gets its own light on each side (one averaged normal per point
    smeared it over a cell width); a smooth surface stays smooth."""
    key = ("corner", id(verts))
    hit = _NORMALS_CACHE.get(key)
    if hit is not None and hit[0] is verts:
        return hit[1]
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    face = np.cross(b - a, c - a)  # length = double the area (weight)
    unit = face / np.maximum(np.linalg.norm(face, axis=1, keepdims=True), 1e-18)
    # neighborhood (which triangles at which corner) depends only on the meshing: when deforming in a drag it stays,
    # only the positions change - remembered like the smoothing matrix (_CALM_OPS)
    tkey = (len(verts), hash(np.ascontiguousarray(tris).tobytes()))
    topo = _CORNER_TOPO.get(tkey)
    if topo is None:
        flat = tris.reshape(-1)
        order = np.argsort(flat, kind="stable")
        counts = np.bincount(flat, minlength=len(verts))
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        deg = int(counts.max()) if len(counts) else 0
        # per point the triangles on it (padded with -1)
        pad = -np.ones((len(verts), max(deg, 1)), int)
        rank = np.arange(len(flat)) - np.repeat(starts, counts)
        pad[flat[order], rank] = order // 3
        nb = pad[tris]  # (T, 3, D)
        valid = nb >= 0
        lru.trim(_CORNER_TOPO, 256)
        topo = _CORNER_TOPO[tkey] = (valid, np.where(valid, nb, 0))
    valid, nbc = topo
    cos = np.einsum("tkdi,ti->tkd", unit[nbc], unit)
    ang = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    w = np.clip((CREASE_FULL_DEG - ang) / (CREASE_FULL_DEG - CREASE_FROM_DEG), 0.0, 1.0) * valid
    area = np.linalg.norm(face, axis=1)[nbc] * valid
    normals = np.einsum("tkd,tkdi->tki", w, face[nbc])
    normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1e-18)
    split = 1.0 - (w * area).sum(axis=2) / np.maximum(area.sum(axis=2), 1e-18)
    out = (normals, split)
    lru.trim(_NORMALS_CACHE, 8192)
    _NORMALS_CACHE[key] = (verts, out)
    return out


_CORNER_TOPO = {}  # meshing -> (valid, neighbor triangles per corner) for _corner_normals
CALM_TIME = 400.0  # smoothing of the light normals: diffusion time (in neighbor steps) - small waves go, shapes stay
CALM_FULL, CALM_NONE = 5.0, 30.0  # light steps: up to 5 steps fully smoothed, from 30 not at all (in between proportionally)


def calm_for_bands(bands):
    """Fraction of the smoothed light normals: the fewer light steps, the stronger (flowing light: none)."""
    if bands < 1.5:
        return 0.0
    return float(min(max((CALM_NONE - bands) / (CALM_NONE - CALM_FULL), 0.0), 1.0))
_CALM_OPS = {}  # meshing -> factorized smoothing matrix (when deforming only the positions change, not the meshing)


def _calm_normals(verts, tris):
    """Strongly smoothed normals per point: implicit diffusion (I + t L) x = n over the neighborhood of the points. For
    light with light steps - small waves of the net surfaces should not get step edges (blotches), large shapes
    should. Without scipy: the simply smoothed normals."""
    key = ("calm", id(verts))
    hit = _NORMALS_CACHE.get(key)
    if hit is not None and hit[0] is verts:
        return hit[1]
    normals = _smooth_normals(verts, tris)
    import scipy.sparse as sparse
    from scipy.sparse.linalg import splu
    n = len(verts)
    tkey = (n, hash(np.ascontiguousarray(tris).tobytes()))
    lu = _CALM_OPS.get(tkey)
    if lu is None:
        edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        edges = np.concatenate([edges, edges[:, ::-1]])
        a = sparse.csr_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n))
        a.data[:] = 1.0  # double edges count once
        deg = np.asarray(a.sum(axis=1)).ravel()
        lap = sparse.diags(deg) - a
        m = (sparse.identity(n) + CALM_TIME * sparse.diags(1.0 / np.maximum(deg, 1.0)) @ lap).tocsc()
        lru.trim(_CALM_OPS, 128)  # (before 64 slots and everything gone on overflow; discard only the older half)
        lu = _CALM_OPS[tkey] = splu(m)
    out = lu.solve(np.ascontiguousarray(normals, dtype=float))
    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
    _NORMALS_CACHE[key] = (verts, out)
    return out


def _stroke_arrays(curves):
    """All strokes with at least two points strung together: (points, widths, rgba per point,
    point count per stroke). One pass in numpy instead of a loop per stroke (large selections)."""
    curves = [c for c in curves if len(c[0]) >= 2]
    if not curves:
        return None
    counts = np.array([len(c[0]) for c in curves])
    pts = np.concatenate([np.asarray(c[0], dtype="f4") for c in curves])
    widths = np.concatenate([_fit(np.asarray(c[1], dtype="f4"), len(c[0])) for c in curves])
    colors = np.repeat(np.asarray([c[2] for c in curves], dtype="f4"), counts, axis=0)
    styles = np.repeat(np.asarray([c[3] if len(c) > 3 else 1.0 for c in curves], dtype="f4"), counts)
    owners = np.repeat(np.asarray([_owner4(c[4] if len(c) > 4 else ()) for c in curves], dtype="f4"), counts, axis=0)
    # painting strokes: (normals per point, order 0..1); otherwise normal 0
    normals = np.concatenate([np.asarray(c[5][0], dtype="f4") if len(c) > 5 and c[5] is not None
                              else np.zeros((len(c[0]), 3), "f4") for c in curves])
    layers = np.repeat(np.asarray([c[5][1] if len(c) > 5 and c[5] is not None else 0.0 for c in curves], dtype="f4"),
                       counts)
    return pts, widths, colors, counts, styles, owners, normals, layers


def _fit(values, n):
    """Safety net: widths matching the point count (otherwise drawing aborts - colorful boxes in the viewport)."""
    if len(values) == n:
        return values
    if not len(values):
        return np.full(n, 0.02, "f4")
    return np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(values)), values).astype("f4")


def _owner4(ids):
    """Up to four surface ids, padded with -1 (membership of a stroke for the coverage map)."""
    ids = [float(i) for i in ids][:4]
    return ids + [-1.0] * (4 - len(ids))


def stroke_buffers(curves):
    """(vertex data, indices, ends) of the strokes - ribbons and ends from ONE processing of the entries."""
    arrays = _stroke_arrays(curves)
    if arrays is None:
        return None, None, None
    return (*ribbon_vertices(curves, arrays), cap_vertices(curves, arrays))


def ribbon_vertices(curves, arrays=None):
    """[(points (N,3), widths (N,), rgba)] -> (vertex data, indices) for camera ribbons.
    Two vertices per point (left/right), two triangles per segment."""
    arrays = _stroke_arrays(curves) if arrays is None else arrays
    if arrays is None:
        return None, None
    pts, widths, colors, counts, styles, owners, normals, layers = arrays
    last = np.cumsum(counts) - 1
    first = last - counts + 1
    # arc length per stroke in stroke widths: coordinate of the pencil grain along the stroke
    # sum in double precision: the sum runs over ALL strokes - in single precision the grain of a
    # stroke depended on how many precede it in the buffer (and the partial upload of single strokes would deviate)
    seg = np.linalg.norm(np.diff(pts.astype("f8"), axis=0), axis=1)
    seg[last[:-1]] = 0.0  # no jump from the end of one stroke to the next
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    arc -= np.repeat(arc[first], counts)
    arc /= np.maximum(np.repeat(np.add.reduceat(widths, first) / counts, counts), 1e-6)
    prev = np.roll(pts, 1, axis=0)
    prev[first] = pts[first]
    nxt = np.roll(pts, -1, axis=0)
    nxt[last] = pts[last]
    n = len(pts)
    per_point = np.hstack([pts, prev, nxt, widths[:, None]])
    side = (np.tile(np.array([-1.0, 1.0], dtype="f4"), n) * np.repeat(styles, 2))[:, None]  # brush: ±2
    verts = np.hstack([np.repeat(per_point, 2, axis=0), side, np.repeat(arc[:, None], 2, axis=0),
                       np.repeat(colors, 2, axis=0), np.repeat(owners, 2, axis=0), np.repeat(normals, 2, axis=0),
                       np.repeat(layers[:, None], 2, axis=0)])
    seg = np.ones(n, bool)
    seg[last] = False  # no segment from the end of one stroke to the start of the next
    base = 2 * np.flatnonzero(seg)
    idx = np.stack([base, base + 1, base + 2, base + 1, base + 3, base + 2], axis=1).reshape(-1)
    return np.ascontiguousarray(verts, dtype="f4"), idx.astype("i4")


def _stroke_same(a, b):
    """Two stroke entries with the same content? Arrays by identity (they are never changed in place; the
    remembered entry holds them, so an id cannot have been reassigned), the rest by value."""
    if a is b:
        return True
    if a[0] is not b[0] or a[1] is not b[1] or len(a) != len(b) or tuple(a[2]) != tuple(b[2]):
        return False
    if len(a) > 3 and a[3] != b[3]:
        return False
    if len(a) > 4 and list(a[4]) != list(b[4]):
        return False
    if len(a) > 5:
        if a[5] is None or b[5] is None:
            return a[5] is b[5]
        return a[5][0] is b[5][0] and a[5][1] == b[5][1]
    return True


def _stroke_diff(old, new):
    """Indices of the entries that have changed - or None if the layout is different (different number of
    strokes, different point count, painting/line swapped): then everything must be reprocessed."""
    if len(old) != len(new):
        return None
    changed = []
    for k, (a, b) in enumerate(zip(old, new)):
        if _stroke_same(a, b):
            continue
        if len(a[0]) != len(b[0]) or len(a[1]) != len(b[1]) or \
                (len(a) > 5 and a[5] is not None) != (len(b) > 5 and b[5] is not None):
            return None
        changed.append(k)
    return changed


def cap_vertices(curves, arrays=None):
    """End points of all strokes as (position, width, rgba) for the round ends."""
    arrays = _stroke_arrays(curves) if arrays is None else arrays
    if arrays is None:
        return None
    pts, widths, colors, counts, styles, owners, normals, layers = arrays
    last = np.cumsum(counts) - 1
    ends = np.stack([last - counts + 1, last], axis=1).reshape(-1)
    return np.ascontiguousarray(np.hstack([pts[ends], widths[ends, None], colors[ends], owners[ends],
                                           styles[ends, None], normals[ends], layers[ends, None]]), dtype="f4")


def _mat_bytes(m):
    return np.asarray(m, dtype="f4").T.tobytes()  # GLSL expects column-major


CULL_PX = 1.0  # meshes whose bounding box on screen is smaller are not drawn (overview shots of large scenes)


def view_matrix(cam):
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = cam.right, cam.up, cam.back
    m[:3, 3] = -m[:3, :3] @ cam.eye
    return m


def projection_matrix(fov, aspect, near, far):
    f = 1.0 / math.tan(fov / 2)
    return np.array([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
        [0, 0, -1, 0],
    ])


def ortho_matrix(half_height, aspect, depth):
    """Orthographic, visible from -depth to +depth around the camera (also "behind" it)."""
    return np.array([
        [1 / (half_height * aspect), 0, 0, 0],
        [0, 1 / half_height, 0, 0],
        [0, 0, -1 / depth, 0],
        [0, 0, 0, 1],
    ])


# vertex/index data of the meshes are shared by all viewports (the GL contexts share their buffers,
# see AA_ShareOpenGLContexts); only the vertex arrays belong to each context itself.
_SHARED_MESH_DATA = {}  # id(Geometry) -> (vbo, cbo, ibo, geo)


def _mesh_data(ctx, geo):
    data = _SHARED_MESH_DATA.get(id(geo))
    if data is None or data[3] is not geo:
        data = _SHARED_MESH_DATA[id(geo)] = (ctx.buffer(geo.vertices.tobytes()), ctx.buffer(geo.colors.tobytes()),
                                             ctx.buffer(geo.faces.tobytes()), geo)
    return data


def _release_mesh_data(alive):
    for key in [k for k in _SHARED_MESH_DATA if k not in alive]:
        for res in _SHARED_MESH_DATA.pop(key)[:3]:
            res.release()


def shadow_ribbons(lines, sun, min_w, r):
    """Triangles of the lines for the shadow map: per segment a ribbon across the sun at the stroke width (min. min_w),
    extended by half the width at both ends (no gaps at kinks) - thick strokes cast thick shadows.
    The ribbon lies half the width behind the line (away from the sun, like the back of a tube): this way
    a thick stroke does not shadow itself. lines: [(points, widths)] - per point or one number."""
    # all lines in one go (before, one by one per line: harbor scene 12.11., 9,000 strokes, ~0.5 s per change with light)
    sun = np.asarray(sun, float)
    lines = [(np.asarray(pts, float), w) for pts, w in lines if len(pts) >= 2]
    if not lines:
        return np.zeros((0, 3), "f4")
    counts = np.array([len(pts) for pts, _ in lines])
    pts = np.concatenate([pts for pts, _ in lines])
    hw = np.concatenate([np.broadcast_to(np.asarray(w, float), (len(p),)) for p, w in lines])
    hw = np.maximum(hw, min_w) * 0.5
    pts = pts - sun * hw[:, None]
    seg = np.ones(len(pts) - 1, bool)
    seg[np.cumsum(counts)[:-1] - 1] = False  # no segment between two lines
    i = np.flatnonzero(seg)
    a, b, ha, hb = pts[i], pts[i + 1], hw[i, None], hw[i + 1, None]
    t = b - a
    lt = np.linalg.norm(t, axis=1, keepdims=True)
    t = t / np.maximum(lt, 1e-12)
    a, b = a - t * ha, b + t * hb
    side = np.cross(t, sun)
    ln = np.linalg.norm(side, axis=1, keepdims=True)
    side = np.where(ln > 1e-9, side / np.maximum(ln, 1e-12), r)
    sa, sb = side * ha, side * hb
    q = [a - sa, a + sa, b + sb, b - sb]
    return np.stack([q[0], q[1], q[2], q[0], q[2], q[3]], axis=1).reshape(-1, 3).astype("f4")

class _MeshBuffers:
    def __init__(self, ctx, geo, shade_prog, pick_prog, occl_prog, occl_acc_prog):
        # moderngl checks context membership: bind the shared GL buffers here only as foreign buffers
        vbo, cbo, ibo = (b if b.ctx is ctx else ctx.external_buffer(b.glo, b.size) for b in _mesh_data(ctx, geo)[:3])
        attrs = [(vbo, "3f", "in_pos"), (cbo, "3f", "in_color")]
        self.shade = ctx.vertex_array(shade_prog, attrs, index_buffer=ibo, index_element_size=4)
        self.pick = ctx.vertex_array(pick_prog, [(vbo, "3f", "in_pos")], index_buffer=ibo, index_element_size=4)
        self.occl = ctx.vertex_array(occl_prog, [(vbo, "3f", "in_pos")], index_buffer=ibo, index_element_size=4)
        self.occl_acc = ctx.vertex_array(occl_acc_prog, [(vbo, "3f", "in_pos")], index_buffer=ibo, index_element_size=4)
        self._ctx, self._vbo, self._wire, self._edge_buf = ctx, vbo, None, None

    def wire(self, prog, geo):
        """Edges for the wireframe - created only on first switch-on."""
        if self._wire is None:
            self._edge_buf = self._ctx.buffer(geo.edges.tobytes())
            self._wire = self._ctx.vertex_array(prog, [(self._vbo, "3f", "in_pos")], index_buffer=self._edge_buf,
                                                index_element_size=4)
        return self._wire

    def release(self):
        for res in (self.shade, self.pick, self.occl, self.occl_acc, self._wire, self._edge_buf):
            if res is not None:
                res.release()


class _MeshBlock:
    """All (at build time) imported meshes in one buffer: points in world coordinates, per point the number
    (slot) of its mesh. An entry (block, None) in the renderer's mesh lists stands for all parts in it."""

    def __init__(self, ctx, meshes, progs):
        self.meshes = list(meshes)
        self.slot = {id(m): k for k, m in enumerate(self.meshes)}
        self.baked = [(m.geo, m.xform.tobytes()) for m in self.meshes]
        nv = np.array([len(m.geo.vertices) for m in self.meshes], np.int64)
        nt = np.array([m.geo.triangle_count for m in self.meshes], np.int64)
        voff, toff = np.concatenate([[0], np.cumsum(nv)]), np.concatenate([[0], np.cumsum(nt)])
        pos = np.empty((voff[-1], 3), "f4")
        col = np.empty((voff[-1], 3), "f4")
        idx = np.empty((toff[-1], 3), "u4")
        for k, m in enumerate(self.meshes):
            a = np.asarray(m.xform, float)
            pos[voff[k]:voff[k + 1]] = m.geo.vertices @ a[:3, :3].T.astype("f4") + a[:3, 3].astype("f4")
            col[voff[k]:voff[k + 1]] = m.geo.colors
            idx[toff[k]:toff[k + 1]] = m.geo.faces + np.uint32(voff[k])
        slot = np.repeat(np.arange(len(self.meshes), dtype="f4"), nv)
        self.lo, self.hi = pos.min(axis=0).astype(float), pos.max(axis=0).astype(float)
        self.triangle_count = int(toff[-1])
        self.geo = self  # (the mesh lists ask geo.triangle_count)
        self.xform = np.eye(4)
        self.vis_rev = 0  # counts changes, what is drawn (shadow map)
        self._bufs = [ctx.buffer(pos.tobytes()), ctx.buffer(col.tobytes()), ctx.buffer(slot.tobytes()),
                      ctx.buffer(idx.tobytes())]
        self.vaos = {}
        for name, prog in progs.items():
            attrs = [(self._bufs[0], "3f", "in_pos")]
            if "in_color" in prog:
                attrs.append((self._bufs[1], "3f", "in_color"))
            attrs.append((self._bufs[2], "1f", "in_slot"))
            self.vaos[name] = ctx.vertex_array(prog, attrs, index_buffer=self._bufs[3], index_element_size=4)
        n = len(self.meshes)
        self.table = np.zeros((max(-(-n * 3 // 1024), 1) * 1024, 4), "f4")
        rows = self.table[:n * 3].reshape(n, 3, 4)
        rows[:, 1, 0] = [float(m.id) for m in self.meshes]
        rows[:, 2, 1], rows[:, 2, 2] = toff[:-1] // 65536, toff[:-1] % 65536
        self.tex = ctx.texture((1024, len(self.table) // 1024), 4, dtype="f4")
        self.tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._sent = None

    def rows(self):
        return self.table[:len(self.meshes) * 3].reshape(len(self.meshes), 3, 4)

    def current(self, m):
        """Slot of m if m sits unchanged in the block (same geometry and matrix), otherwise None."""
        k = self.slot.get(id(m))
        if k is None or self.meshes[k] is not m:
            return None
        geo, xf = self.baked[k]
        return k if geo is m.geo and xf == m.xform.tobytes() else None

    def world_bounds(self):
        return self.lo, self.hi

    def bind(self, prog, vis_col):
        if self._sent is None or not np.array_equal(self._sent, self.table):
            self.tex.write(self.table.tobytes())
            self._sent = self.table.copy()
        self.tex.use(location=BLOCK_UNIT)
        prog["block_tab"].value = BLOCK_UNIT
        prog["vis_col"].value = vis_col

    def release(self):
        for res in list(self.vaos.values()) + self._bufs + [self.tex]:
            res.release()
        self.vaos, self._bufs = {}, []


class Renderer:
    MSAA_SAMPLES = 8

    def __init__(self, ctx, gl):
        """gl: QOpenGLFunctions of the Qt context, for states moderngl does not manage
        (glDepthMask, GL_MULTISAMPLE)."""
        self.ctx = ctx
        self._gl = gl
        self._depth_mask = gl.glDepthMask
        self._msaa_fbo, self._msaa_size = None, None
        self.mesh_prog = ctx.program(vertex_shader=MESH_VS, fragment_shader=MESH_FS)
        self.pick_prog = ctx.program(vertex_shader=PICK_VS, fragment_shader=PICK_FS)
        self.wire_prog = ctx.program(vertex_shader=WIRE_VS, fragment_shader=WIRE_FS)
        self.flat_prog = ctx.program(vertex_shader=FLAT_VS, fragment_shader=FLAT_FS)
        self.inf_prog = ctx.program(vertex_shader=FLAT_VS, fragment_shader=INFINITE_FS)
        self._infinite = []  # infinite planes of this frame (base grid, active plane), see viewport
        self.ribbon_prog = ctx.program(vertex_shader=RIBBON_VS, fragment_shader=RIBBON_FS)
        self.material_prog = ctx.program(vertex_shader=SURFACE_VS, fragment_shader=MATERIAL_FS)
        self.occl_surf_prog = ctx.program(vertex_shader=SURFACE_VS, fragment_shader=OCCL_SURF_FS)
        self.occl_acc_surf_prog = ctx.program(vertex_shader=SURFACE_VS, fragment_shader=OCCL_ACC_SURF_FS)
        self.shadow_surf_prog = ctx.program(vertex_shader=SURFACE_VS, fragment_shader=SHADOW_LINE_FS)
        self._surface_vaos = {}  # program -> vao on the surface buffer
        self._surfaces = []  # surfaces of this frame (dicts, see render)
        self.material_scale = 1.0  # global material scale (viewport)
        # hold the shadow map fixed (viewport: while a gizmo drag runs). Re-rendering it costs per frame with the
        # scene (all strokes, all surfaces); during a drag the frame rate counts, the shadows follow on release.
        self.shadow_hold = False
        self.occl_mesh_prog = ctx.program(vertex_shader=PICK_VS, fragment_shader=OCCL_MESH_FS)
        self.occl_acc_mesh_prog = ctx.program(vertex_shader=PICK_VS, fragment_shader=OCCL_ACC_MESH_FS)
        self.block_progs = {name: ctx.program(vertex_shader=BLOCK_VS, fragment_shader=fs) for name, fs in (
            ("shade", BLOCK_MESH_FS), ("pick", BLOCK_PICK_FS), ("occl", BLOCK_OCCL_FS), ("occl_acc", BLOCK_OCCL_ACC_FS))}
        self._block = None  # _MeshBlock of the imported meshes (or None)
        self._block_memo = None  # (input list, list with block entry) - same list when rotating
        self._occl = None  # (fbo, coverage texture, size, depth buffer)
        self._occl_on = False
        self._xray_front = 1.0  # opacity of the frontmost layer (X-Ray < 1)
        self._xray_behind = 0.0  # opacity of hidden things (0 = invisible)
        self._xray_on = False
        self._aid_pass = 1.0  # drawing aids: 0 below the surfaces, 1 above them
        self.pictures = []  # projected images of this frame (pictures.draw_list)
        self._picture_textures = {}
        self.picture_prog = ctx.program(vertex_shader=FLAT_VS, fragment_shader=PICTURE_FS.replace("%OCCL%", OCCL_LIB))
        self._occl_dense_on = True  # check the opacity of the frontmost layer (off while it is being created)
        self.shadow_line_prog = ctx.program(vertex_shader=SHADOW_LINE_VS, fragment_shader=SHADOW_LINE_FS)
        self.light = None  # light mode: dict(dir, col, sky, away, shadow) or None
        self._shadow = None  # (fbo, depth texture, size)
        self._shadow_key = None
        self._shadow_vp = np.eye(4)
        self._shadow_bias = 0.002
        self._shadow_lines = None  # (vbo, vao, number of vertices, key)
        self._stroke_rev = 0  # counts every re-upload of the strokes
        # ... and only those where position or width of a stroke changed: the shadow map depends on that. A
        # pure color change (hover, selection) casts no different shadow and does not re-render it.
        self._stroke_geo_rev = 0
        self.paper_prog = ctx.program(vertex_shader=PAPER_VS, fragment_shader=PAPER_FS)
        self._paper_vao = ctx.vertex_array(self.paper_prog, [])
        self.cap_prog = ctx.program(vertex_shader=CAP_VS, fragment_shader=CAP_FS)
        self._caps = None  # (vbo, vao, capacity)
        self._surface_buf = None  # (vbo, vao, capacity)
        self._slot_buf = None  # (vbo, capacity, corner counts per surface): number of the surface per corner
        self._surf_tex = None  # surface table (SURF_DATA)
        self._surf_table = None  # (surface list, scale, values, ...) of the last uploaded table
        self._stroke_state = None  # last uploaded strokes: entries, vertices, ends (partial upload, _patch_strokes)
        self._surface_ranges = []  # (first vertex, count) per drawing surface of this frame
        self._line_buf = None  # (vbo, vao, capacity) for outlines of the drawing surfaces
        self._ribbon = None  # (vbo, ibo, vao, capacity vbo, capacity ibo)
        self._live = (None, None, (0, 0))  # live strokes (running stroke): (ribbon, caps, counts) as above, small
        # flipbook drawings (Timing) of all frames: own buffer, rebuilt only when drawings change; per frame
        # only the ranges of the current drawings are drawn (a frame change uploads nothing)
        self._flip_buf = (None, None)  # (ribbon, caps)
        self._flip_key = None
        self._flip_ranges = {}  # (plane, frame) -> (first index, indices, first end, ends)
        self._flip_jobs = []  # [(range, opacity)] of this frame
        self._meshes = {}  # id(Geometry) -> _MeshBuffers
        self._flat_buf, self._flat_vao, self._flat_cap = None, None, 0
        self._pick_fbo, self._pick_size, self._pick_key = None, None, None
        self._pick_meshes = []

    # --- Resources ---
    def _mesh_buffers(self, geo):
        buf = self._meshes.get(id(geo))
        if buf is None:
            buf = self._meshes[id(geo)] = _MeshBuffers(self.ctx, geo, self.mesh_prog, self.pick_prog, self.occl_mesh_prog,
                                                          self.occl_acc_mesh_prog)
            buf.geo = geo  # keeps the id stable as long as the buffer lives
        return buf

    def release_unused(self, geos):
        alive = {id(g) for g in geos}
        for key in [k for k in self._meshes if k not in alive]:
            self._meshes.pop(key).release()
        _release_mesh_data(alive)

    def _flat_vertices(self, data):
        data = np.ascontiguousarray(data, dtype="f4")
        if data.nbytes > self._flat_cap:
            if self._flat_buf is not None:
                self._flat_vao.release()
                self._flat_buf.release()
            self._flat_cap = max(data.nbytes, 2 * self._flat_cap, 4096)
            self._flat_buf = self.ctx.buffer(reserve=self._flat_cap, dynamic=True)
            self._flat_vao = self.ctx.vertex_array(self.flat_prog, [(self._flat_buf, "3f", "in_pos")])
            self._inf_vao = self.ctx.vertex_array(self.inf_prog, [(self._flat_buf, "3f", "in_pos")])
        self._flat_buf.write(data.tobytes())

    # --- Visible image ---
    def render(self, fbo, cam, proj, focal, light_eye, meshes, planes, strokes, opacity, min_px=1.0, surfaces=(),
               view_tan=0.414, infinite=(), xray=None, wire=None, live=(), flip=None):
        """meshes: [(MeshObject, tint_rgba)], planes: [(Plane, fill_rgba, line_rgba, highlighted)]
        (sorted back to front), strokes: [(points, widths, rgba, side, surface ids)], opacity: opacity
        of the meshes, xray: None or opacity of the front layer in X-Ray (hidden: XRAY_BEHIND of it; meshes
        show each of their layers), wire: None or opacity of the wireframe (edges of the meshes added, only in
        X-Ray - then all; opaque meshes without X-Ray stay without edges).
        proj: projection matrix, focal: pixel scale of the strokes (see RIBBON_VS), light_eye: light source of the
        mesh shading.

        surfaces: surfaces with material (dicts, see _upload_surfaces).
        live: strokes like strokes that change with every mouse movement (the running stroke) - own small
        buffer so that strokes need not be reprocessed each time while drawing.
        flip: flipbook drawings (Timing) as (entries like painting strokes, fingerprint, {group: (first entry,
        count)}, [(group, opacity)]) - own buffer, only the named groups are drawn.

        What is in front is decided by the coverage map (surfaces + meshes, _update_occlusion) - not by the order
        in which things were drawn. Order in the image: meshes -> drawing aids behind -> surfaces opaque with material
        (only the frontmost layer) -> drawing aids in front (hide nothing) -> painting -> strokes on top (on
        their surface always, behind it not)."""
        ctx = self.ctx
        w, h = fbo.size
        target = self._msaa_target((w, h))  # Qt provides no MSAA -> own multisample buffer
        target.use()
        ctx.viewport = (0, 0, w, h)
        ctx.scissor = None
        self._gl.glEnable(GL_MULTISAMPLE)  # Qt's painter turns it off, moderngl does not turn it back on
        self._depth_mask(True)
        target.clear(*theme.rgb(theme.PAPER), 1.0, depth=1.0)
        vp = proj @ view_matrix(cam)
        self._view = (cam.eye, cam.back, getattr(cam, "ortho", False))
        self._frame_vp, self._frame_size = vp, (w, h)  # for points_visible after the frame
        self._draw_paper((w, h), cam, view_tan)

        self._upload_surfaces(surfaces)
        meshes = self._blockify(meshes, build=not self.shadow_hold)  # imported meshes: one block instead of one per mesh
        self._update_shadow(strokes, meshes)  # light mode: shadow map (only on changes)
        meshes = self._in_view(vp, meshes, (w, h))  # everything after this sees only this camera: do not draw meshes outside
        self._xray_front = 1.0 if xray is None else float(xray)
        self._xray_behind = 0.0 if xray is None else float(xray) * XRAY_BEHIND
        self._xray_on = xray is not None
        mesh_alpha = opacity * self._xray_front
        # semi-transparent meshes (slider) cover only in X-Ray - otherwise one sees through them
        occluding = mesh_alpha >= 0.999 or xray is not None
        self._update_occlusion(vp, (w, h), meshes if occluding else (), focal, self._surfaces)
        self._frame_meshes = meshes  # for id_map after the frame
        target.use()
        ctx.viewport = (0, 0, w, h)
        self._upload_strokes(strokes)
        self._upload_live(live)
        self._upload_flip(flip)
        self._infinite = list(infinite or ())

        # 1. Meshes - among themselves via depth buffer, semi-transparent only with their frontmost layer; X-Ray: every
        # layer see-through on top of each other (denser where more layers lie). Wireframe is added only in X-Ray
        # (overlay like in Blender, all edges); opaque meshes without X-Ray stay without edges
        wires = meshes and wire is not None and wire > 0.001
        if meshes and mesh_alpha <= 0.001 and wires:  # meshes fully see-through (slider): only the edges
            ctx.enable_only(moderngl.BLEND)
            ctx.blend_func = BLEND_OVER
            self._draw_wires(vp, meshes, wire)
        elif meshes and mesh_alpha > 0.001:
            ctx.enable_only(moderngl.DEPTH_TEST)
            self._depth_mask(True)
            if xray is not None and mesh_alpha < 0.999:
                ctx.enable_only(moderngl.BLEND)
                ctx.blend_func = BLEND_OVER
                # per layer so much that a closed body (front + back) looks like the front layer
                # with the opacity of the slider
                self._draw_meshes(vp, light_eye, meshes, alpha=1.0 - math.sqrt(max(1.0 - mesh_alpha, 0.0)))
            elif mesh_alpha >= 0.999:
                self._draw_meshes(vp, light_eye, meshes, alpha=1.0)
            else:
                target.color_mask = (False, False, False, False)
                target.use()  # moderngl applies the mask only on activation
                self._draw_meshes(vp, light_eye, meshes, alpha=1.0)
                target.color_mask = (True, True, True, True)
                target.use()
                ctx.enable_only(moderngl.DEPTH_TEST | moderngl.BLEND)
                ctx.blend_func = BLEND_OVER
                ctx.depth_func = "<="
                self._draw_meshes(vp, light_eye, meshes, alpha=mesh_alpha)
                ctx.depth_func = "<"
            if wires and xray is not None:
                xray_wire = xray is not None and mesh_alpha < 0.999  # X-Ray: no depth buffer, all edges
                ctx.enable_only(moderngl.BLEND if xray_wire else moderngl.BLEND | moderngl.DEPTH_TEST)
                ctx.blend_func = BLEND_OVER
                self._depth_mask(False)
                ctx.depth_func = "<="
                self._draw_wires(vp, meshes, wire, bias=0.0 if xray_wire else WIRE_DEPTH_BIAS)
                ctx.depth_func = "<"
                self._depth_mask(True)
            self._gl.glClear(GL_DEPTH_BUFFER_BIT)  # what lies in front of/behind the meshes is decided from here on by the coverage map
        # 2. Drawing aids lying on or behind a surface: below - it covers them
        ctx.enable_only(moderngl.BLEND)
        ctx.blend_func = BLEND_OVER
        self._aid_pass = 0.0
        self._glaze_planes = [(np.asarray(pl.origin, float), np.asarray(pl.axis_u, float) * pl.size_u / 2,
                               np.asarray(pl.axis_v, float) * pl.size_v / 2, tuple(float(x) for x in fill),
                               (self._plane_under(em),), (0.0 if int(em) else 1.0,))
                              for pl, fill, _line, em in planes if len(fill) > 3 and fill[3] > 0.01]
        self._draw_planes(vp, planes)
        self._draw_pictures(vp)
        # 3. Surfaces opaque with their material (only the frontmost layer; X-Ray: hidden things softly)
        self._draw_materials(vp)
        # 4. Drawing aids in front - hide nothing; outlines of the surfaces
        self._aid_pass = 1.0
        self._draw_planes(vp, planes)
        self._draw_pictures(vp)
        self._draw_lines(vp, [(o, s["line"], s["emphasis"], s["id"]) for s in self._surfaces for o in s["outlines"]])
        # 5. Painting: in painting order (depth = order, the newest lies on top), then the strokes on top
        # (depth only among themselves: round ends not blended twice)
        ctx.enable_only(moderngl.DEPTH_TEST | moderngl.BLEND)
        ctx.blend_func = BLEND_OVER
        self._depth_mask(True)
        if getattr(self, "_paint_counts", (0, 0))[0]:
            self._gl.glClear(GL_DEPTH_BUFFER_BIT)
            self._draw_strokes(vp, (w, h), focal, min_px, part="paint")
            self._gl.glClear(GL_DEPTH_BUFFER_BIT)
        if self._flip_jobs:  # flipbook: per plane the current drawing (onion skin faint in front)
            ribbon, capbuf = self._flip_buf
            for (f_idx, n_idx, f_cap, n_cap), fade in self._flip_jobs:
                self._gl.glClear(GL_DEPTH_BUFFER_BIT)
                self._draw_strokes(vp, (w, h), focal, min_px, fade=fade,
                                   only=[(ribbon, capbuf, f_idx, n_idx, f_cap, n_cap)])
            self._gl.glClear(GL_DEPTH_BUFFER_BIT)
        self._draw_strokes(vp, (w, h), focal, min_px)
        ctx.enable_only(moderngl.NOTHING)
        ctx.copy_framebuffer(fbo, target)  # resolve multisample
        fbo.use()

    def _draw_paper(self, size, cam, view_tan):
        """Drawing paper as background: blotches, fibers, grain on a sphere around the camera
        (rotates with the view like a sky), plus slightly darker corners."""
        ctx = self.ctx
        ctx.enable_only(moderngl.NOTHING)
        prog = self.paper_prog
        prog["paper"].value = theme.rgb(theme.PAPER)
        prog["size"].value = (float(size[0]), float(size[1]))
        prog["stain"].value = theme.PAPER_STAIN
        prog["grain"].value = theme.PAPER_GRAIN
        prog["vignette"].value = theme.PAPER_VIGNETTE
        prog["cam_right"].value = tuple(float(x) for x in cam.right)
        prog["cam_up"].value = tuple(float(x) for x in cam.up)
        prog["cam_back"].value = tuple(float(x) for x in cam.back)
        prog["view_tan"].value = float(view_tan)
        self._paper_vao.render(moderngl.TRIANGLES, vertices=3)

    def _occl_uniforms(self, prog, owner=None, under=None):
        """Coverage map to a program: owner = surface id (drawing aids), under = opacity on a surface."""
        if "occl_on" not in prog:
            return
        prog["occl_on"].value = 1.0 if self._occl_on else 0.0
        if "xray_behind" in prog:  # not in the opacity pass (front_here)
            prog["xray_behind"].value = self._xray_behind
        prog["occl_tol"].value = OCCL_TOL
        if "aid_pass" in prog:
            prog["aid_pass"].value = self._aid_pass
        if "occl_min" in prog:
            prog["occl_min"].value = OCCL_MIN_COVER if self._occl_dense_on else 0.0
        eye, back, ortho = self._view
        for name, value in (("eye", tuple(float(x) for x in eye)), ("view_back", tuple(float(x) for x in back)),
                            ("ortho", 1.0 if ortho else 0.0)):
            if name in prog:
                prog[name].value = value
        if self._occl_on:
            self._occl[1].use(location=OCCL_UNIT)
            prog["occl_map"].value = OCCL_UNIT
            if "occl_acc" in prog:
                # while the opacity is being created, its texture is the target - then bind a different one (not read)
                (self._occl[4] if self._occl_dense_on else self._occl[1]).use(location=OCCL_ACC_UNIT)
                prog["occl_acc"].value = OCCL_ACC_UNIT
        self._occl_owner(prog, owner, under)

    @staticmethod
    def _occl_owner(prog, owner=None, under=None):
        """Per drawing aid: its id and the opacity on a surface (the rest stays set by the pass)."""
        if owner is not None and "owner" in prog:
            prog["owner"].value = (float(owner), -1.0, -1.0, -1.0)
        if under is not None and "under" in prog:
            prog["under"].value = float(under)

    def _surface_vao(self, prog):
        """Vertex array of a program on the shared surface buffer (position, normal)."""
        vbo, slots = self._surface_buf[0], self._slot_buf[0]
        cached = self._surface_vaos.get(id(prog))
        if cached is None or cached[0] is not vbo or cached[2] is not slots:
            slot = [(slots, "1f", "in_slot")]
            if "in_calm" in prog:
                vao = self.ctx.vertex_array(prog, [(vbo, "3f 3f 3f", "in_pos", "in_normal", "in_calm")] + slot)
            elif "in_normal" in prog:
                vao = self.ctx.vertex_array(prog, [(vbo, "3f 3f 12x", "in_pos", "in_normal")] + slot)
            else:
                vao = self.ctx.vertex_array(prog, [(vbo, "3f 24x", "in_pos")] + slot)
            cached = self._surface_vaos[id(prog)] = (vbo, vao, slots)
        if "surf_data" in prog:
            self._surf_tex.use(location=SURF_UNIT)
            prog["surf_data"].value = SURF_UNIT
            prog["surf_rows"].value = SURF_ROWS
        if "occluders_only" in prog:
            prog["occluders_only"].value = 0
        return cached[1]

    def _surface_rows(self, surfaces):
        """Values of the surface table (N, SURF_COLS, 4) - see SURF_DATA."""
        rows = np.zeros((len(surfaces), SURF_COLS, 4), "f4")
        for k, s in enumerate(surfaces):
            size = max(s["size"], 1e-6)
            # grain: 90 % global, 10 % by surface size (large surfaces somewhat coarser)
            scale = self.material_scale * (size / theme.MATERIAL_SIZE_REF) ** theme.MATERIAL_SIZE_WEIGHT
            seed = float(s["seed"])
            opacity = float(s.get("opacity", 1.0))
            m = s.get("model")
            r = rows[k]
            r[0, :3], r[0, 3] = s["tint"], int(s["material"])
            r[1, :3], r[1, 3] = s["anchor"], scale
            r[2, :3], r[2, 3] = (seed * 7.31 % 97.0, seed * 3.17 % 89.0, seed * 5.53 % 83.0), s["grid_step"]
            r[3] = s["state"]
            r[4, :3], r[4, 3] = s["grid_color"], s["grid_alpha"]
            # (shadow check point: in the shader at least a few texels of the shadow map away from the surface, lift_min)
            r[5] = (size * 0.004, opacity, float(s["id"]), 0.0 if m is None else 1.0)
            r[6, :3] = (max(s["size"] * SURFACE_OCCL_RADIUS / min(s.get("resolution", 1.0), 1.0), 1e-6),
                        float(-np.log(1.0 - min(max(opacity, 0.0), 0.9999))),
                        1.0 if s["count"] and s.get("occlude", True) else 0.0)
            if m is not None:
                r[7:10] = np.asarray(m, "f4")[:3]
        return rows

    def _upload_surface_table(self, source):
        """Surface table and surface numbers per corner for this frame. source: the list the viewport passed -
        the same list as in the last frame (camera move) means the same values."""
        surfaces = self._surfaces
        counts = [s["count"] for s in surfaces]
        if self._slot_buf is None or self._slot_buf[2] != counts:
            data = np.repeat(np.arange(len(counts), dtype="f4"), counts)
            if self._slot_buf is None or data.nbytes > self._slot_buf[1]:
                if self._slot_buf is not None:
                    for _vbo, vao, _slots in self._surface_vaos.values():  # hang on the old buffer
                        vao.release()
                    self._surface_vaos.clear()
                    self._slot_buf[0].release()
                cap = max(data.nbytes * 2, 1 << 14)
                self._slot_buf = (self.ctx.buffer(reserve=cap, dynamic=True), cap, counts)
            else:
                self._slot_buf = (self._slot_buf[0], self._slot_buf[1], counts)
            if data.nbytes:
                self._slot_buf[0].write(data)
        extra = (theme.MATERIAL_SIZE_REF, theme.MATERIAL_SIZE_WEIGHT, SURF_ROWS)
        last = self._surf_table
        same = last is not None and last[0] is source and last[1] == self.material_scale and last[3] == extra
        if same and not self.VERIFY_STROKES:
            return
        rows = self._surface_rows(surfaces)
        if same:  # test check mode: the same list must yield the same values
            assert rows.shape == last[2].shape and np.array_equal(rows, last[2]), \
                "Flächen-Tabelle: dieselbe Liste wie im letzten Bild, aber andere Werte"
            return
        n = len(surfaces)
        blocks = (n + SURF_ROWS - 1) // SURF_ROWS
        height = SURF_ROWS if blocks > 1 else max(64, 1 << int(np.ceil(np.log2(max(n, 1)))))
        size = (SURF_COLS * blocks, height)
        if self._surf_tex is None or self._surf_tex.size != size:
            if self._surf_tex is not None:
                self._surf_tex.release()
            self._surf_tex = self.ctx.texture(size, 4, dtype="f4")
            self._surf_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        grid = np.zeros((height, SURF_COLS * blocks, 4), "f4")
        for b in range(blocks):
            part = rows[b * SURF_ROWS:(b + 1) * SURF_ROWS]
            grid[:len(part), b * SURF_COLS:(b + 1) * SURF_COLS] = part
        self._surf_tex.write(grid.tobytes())
        self._surf_table = (source, self.material_scale, rows, extra)

    def _upload_surfaces(self, surfaces):
        """Upload the surfaces of this frame (only if one has changed: same arrays = same shape).
        surfaces: [dict(verts, tris, id, material, tint, seed, state, grid_step, grid_alpha, grid_color, outlines, line,
        emphasis)]."""
        self._surfaces = []
        if not surfaces:
            self._surface_key = None
            return
        self._upload_surface_blocks(surfaces)
        self._upload_surface_table(surfaces)

    def _upload_surface_blocks(self, surfaces):
        # draft (surface currently deforming in a gizmo drag): simple normals - belongs to the state, so that after
        # release the same shape is uploaded once more with exact normals
        key = tuple((id(s["verts"]), id(s["tris"]), bool(s.get("draft"))) for s in surfaces)
        first = 0
        chunks = [] if key != getattr(self, "_surface_key", None) or self._surface_buf is None else None
        bounds = getattr(self, "_bounds_cache", {})
        self._bounds_cache = {}
        # per shape (arrays): normals per corner and finished block for uploading - unchanged ones not again. Only shift around
        # when actually uploading (otherwise they would be empty after a frame without changes, and the next change
        # would recompute all surfaces)
        normals = getattr(self, "_normal_cache", {})
        blocks = getattr(self, "_block_cache", {})
        if chunks is not None:
            counters.C["flaechen_upload"] += len(surfaces)
            self._normal_cache, self._block_cache = {}, {}
            self._prefetch_normals(surfaces, normals, blocks)
        for s in surfaces:
            verts, tris = s["verts"], s["tris"]
            n = tris.size
            hit = bounds.get(id(verts))
            if hit is None or hit[0] is not verts:  # compute circumference only for new shapes (otherwise every surface per frame)
                hit = (verts, verts.min(axis=0), verts.max(axis=0))
            self._bounds_cache[id(verts)] = hit
            lo, hi = hit[1], hit[2]
            if s.get("model") is not None:  # carried along: box of the moved net
                m = s["model"]
                box = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                box = box @ m[:3, :3].T + m[:3, 3]
                lo, hi = box.min(axis=0), box.max(axis=0)
            self._surfaces.append(dict(s, first=first, count=n, lo=lo, hi=hi, anchor=(lo + hi) / 2,
                                       size=float(np.linalg.norm(hi - lo))))
            if chunks is not None:
                bk = (id(verts), id(tris))
                draft = bool(s.get("draft"))
                hit = blocks.get(bk) or self._block_cache.get(bk)
                if hit is not None and hit[0] is verts and hit[1] is tris and (draft or not hit[3]):
                    self._block_cache[bk] = hit
                    chunks.append(hit[2])
                    first += n
                    continue
                flat = tris.reshape(-1)
                basis = s.get("basis")  # copy of a generator (only offset): normals of the original, rotated along
                if basis is not None:
                    ov, ot, m3, flip = basis
                    corner, calm, rough = self._corner_data(ov, ot, normals, draft=draft)
                    corner, calm = corner @ m3.T, calm @ m3.T
                    if flip:  # mirrored: winding reversed (the corners of each triangle in new order)
                        corner = corner.reshape(-1, 3, 3)[:, [0, 2, 1]].reshape(-1, 3)
                        calm = calm.reshape(-1, 3, 3)[:, [0, 2, 1]].reshape(-1, 3)
                else:
                    corner, calm, rough = self._corner_data(verts, tris, normals, sid=s.get("id"), draft=draft)
                block = np.empty((len(flat), 9), "f4")
                block[:, :3], block[:, 3:6], block[:, 6:] = verts[flat], corner, calm
                self._block_cache[bk] = (verts, tris, block, rough)
                chunks.append(block)
            first += n
        if chunks is None:
            return
        self._surface_keep = [(s["verts"], s["tris"]) for s in surfaces]  # keeps the ids valid
        old = getattr(self, "_surface_blocks", None)
        self._surface_blocks = chunks
        if (self._surface_buf is not None and old is not None and len(old) == len(chunks)
                and all(a.shape == b.shape for a, b in zip(old, chunks))):
            # same layout: write only the changed surfaces into their place (instead of copying everything anew)
            offset = 0
            for a, b in zip(old, chunks):
                if a is not b:
                    self._surface_buf[0].write(b, offset=offset)
                offset += b.nbytes
            self._surface_key = key
            return
        data = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        if self._surface_buf is None or data.nbytes > self._surface_buf[2]:
            if self._surface_buf is not None:
                self._surface_buf[1].release()
                self._surface_buf[0].release()
            cap = max(data.nbytes * 2, 1 << 16)
            vbo = self.ctx.buffer(reserve=cap, dynamic=True)
            vao = self.ctx.vertex_array(self.material_prog, [(vbo, "3f 3f 3f", "in_pos", "in_normal", "in_calm")])
            self._surface_buf = (vbo, vao, cap)
        self._surface_buf[0].write(data)
        self._surface_key = key

    def _prefetch_normals(self, surfaces, previous, blocks):
        """Normals of all shapes that would have to be recomputed shortly, in advance and in parallel (independent per shape, numpy releases
        the Python lock on large computations) - e.g. after extruding many surfaces: hundreds of new shapes.
        Result lands in previous; _corner_data finds it there. Rotated copies (rigid) stay when rotating along."""
        jobs = []
        by_sid = self.__dict__.get("_normal_by_sid", {})
        for s in surfaces:
            verts, tris = s["verts"], s["tris"]
            if s.get("basis") is not None or s.get("draft"):
                continue
            bk = (id(verts), id(tris))
            hit = blocks.get(bk)
            if hit is not None and hit[0] is verts and hit[1] is tris and not hit[3]:
                continue
            hit = previous.get(bk) or self._normal_cache.get(bk)
            if hit is not None and hit[0] is verts and hit[1] is tris and not hit[4]:
                continue
            old = by_sid.get(s.get("id"))
            if old is not None and old[1].shape == tris.shape and _rigid_rotation(old[0], verts) is not None:
                continue
            jobs.append((verts, tris))
        if len(jobs) < PARALLEL_MIN:
            return
        def work(job):
            verts, tris = job
            flat = tris.reshape(-1)
            corner, split = _corner_normals(verts, tris)
            corner, split = corner.reshape(-1, 3), split.reshape(-1, 1)
            calm = _calm_normals(verts, tris)[flat] * (1 - split) + corner * split
            return (verts, tris, corner, calm, False)
        for hit in _pool().map(work, jobs):
            previous[(id(hit[0]), id(hit[1]))] = hit

    def _corner_data(self, verts, tris, previous, sid=None, draft=False):
        """(corner normals, smoothed normals, only approximate?) per triangle corner (N*3, 3) of a shape - taken over from previous
        (last upload) if the same arrays, otherwise computed. Light normals per corner (folds stay
        hard); the strongly smoothed ones (light steps) yield to the corner normal at a fold, otherwise the
        smoothing would blur the fold. draft (surface deforming in a drag): only the simply averaged normals per point - folds
        and the smoothing for light steps come after release (exactly computed ones are also used during the drag, approximate ones
        never for the finished image)."""
        k = (id(verts), id(tris))
        hit = previous.get(k) or self._normal_cache.get(k)
        if hit is not None and hit[4] and not draft:
            hit = None  # only remembered approximately: now exactly
        if hit is None or hit[0] is not verts or hit[1] is not tris:
            by_sid = self.__dict__.setdefault("_normal_by_sid", {})
            old = by_sid.get(sid) if sid is not None else None
            rot = _rigid_rotation(old[0], verts) if old is not None and (
                old[1] is tris or old[1].shape == tris.shape and np.array_equal(old[1], tris)) else None
            if rot is not None and (draft or not old[4]):
                # same shape, only rotated/shifted/uniformly scaled (gizmo drag of a group): rotate normals along
                hit = (verts, tris, old[2] @ rot.T, old[3] @ rot.T, old[4])
            elif draft:
                rough = _vertex_normals(verts, tris)[tris.reshape(-1)]
                hit = (verts, tris, rough, rough, True)
            else:
                flat = tris.reshape(-1)
                corner, split = _corner_normals(verts, tris)
                corner, split = corner.reshape(-1, 3), split.reshape(-1, 1)
                calm = _calm_normals(verts, tris)[flat] * (1 - split) + corner * split
                hit = (verts, tris, corner, calm, False)
        if sid is not None:
            self.__dict__.setdefault("_normal_by_sid", {})[sid] = hit
        self._normal_cache[k] = hit
        return hit[2], hit[3], hit[4]

    def _draw_materials(self, vp):
        """Surfaces opaque with their material. What is in front is told by the coverage map; X-Ray: first the hidden things softly,
        above them the frontmost layer with the opacity of the slider."""
        if not self._surfaces:
            return
        prog = self.material_prog
        prog["vp"].write(_mat_bytes(vp))
        prog["bias"].value = 0.0
        prog["stain"].value = float(theme.STAIN_STRENGTH)
        prog["mono"].value = 0.0 if theme.COLOR_VIEW else 1.0
        prog["front_alpha"].value = self._xray_front
        self._light_uniforms(prog, surface=True)
        bands = float(self.light.get("bands", 0)) if self.light else 0.0
        prog["calm"].value = calm_for_bands(bands)
        self._occl_uniforms(prog)
        prog["lift_min"].value = 3.0 * getattr(self, "_shadow_texel", 0.0)
        vao = self._surface_vao(prog)
        total = sum(s["count"] for s in self._surfaces)
        # first hidden things (shine through see-through surfaces or in X-Ray), above them the frontmost layer - the one with
        # depth test: where two surfaces both count as front at the outline, it decides per sample (smooth edges)
        for layer in (0.0, 1.0):
            prog["layer"].value = layer
            if layer > 0.5:
                self.ctx.enable_only(moderngl.DEPTH_TEST | moderngl.BLEND)
                self._depth_mask(True)
                self._gl.glClear(GL_DEPTH_BUFFER_BIT)
            vao.render(moderngl.TRIANGLES, vertices=total)  # all surfaces at once (surface table)
            counters.C["zeichenaufrufe"] += 1
        self._gl.glClear(GL_DEPTH_BUFFER_BIT)  # the strokes afterwards bring their own depth
        self.ctx.enable_only(moderngl.BLEND)

    def _draw_lines(self, vp, lines):
        """Thin lines (outlines of the drawing surfaces): [(polyline (N,3), rgba, highlighted, surface id)]."""
        lines = [l for l in lines if len(l[0]) >= 2]
        if not lines:
            return
        counts = [2 * (len(pts) - 1) for pts, *_ in lines]
        key = tuple((id(l[0]), len(l[0])) for l in lines)
        if key != getattr(self, "_line_key", None) or self._line_buf is None:  # upload only on changes
            segs = [np.stack([pts[:-1], pts[1:]], axis=1).reshape(-1, 3) for pts, *_ in lines]
            data = np.ascontiguousarray(np.vstack(segs), dtype="f4")
            if self._line_buf is None or data.nbytes > self._line_buf[2]:
                if self._line_buf is not None:
                    self._line_buf[1].release()
                    self._line_buf[0].release()
                cap = max(data.nbytes * 2, 1 << 15)
                vbo = self.ctx.buffer(reserve=cap, dynamic=True)
                vao = self.ctx.vertex_array(self.flat_prog, [(vbo, "3f", "in_pos")])
                self._line_buf = (vbo, vao, cap)
            self._line_buf[0].write(data.tobytes())
            self._line_key = key
            self._line_keep = [l[0] for l in lines]  # keeps the ids valid
        vbo, vao = self._line_buf[:2]
        prog = self.flat_prog
        prog["vp"].write(_mat_bytes(vp))
        prog["bias"].value = 0.0
        prog["grain"].value = 0.0
        self._occl_uniforms(prog, under=-1.0)
        first = 0
        for (pts, rgba, highlighted, sid), n in zip(lines, counts):
            self._occl_owner(prog, owner=sid)
            _, border_a, width = theme.PLANE_EMPHASIS[int(highlighted)]
            prog["color"].value = (*rgba[:3], border_a)
            self.ctx.line_width = width
            vao.render(moderngl.LINES, vertices=n, first=first)
            first += n
        self.ctx.line_width = 1.0

    def _upload_strokes(self, strokes):
        """Upload ribbon and end-point data; drawn twice if needed. Unchanged strokes
        (same fingerprint as in the last frame, e.g. when rotating the camera) are not
        reprocessed - with thousands of lines the biggest part of the frame time."""
        if strokes is getattr(self, "_stroke_list", None) and self._ribbon is not None:
            return  # same list as in the last frame (viewport kept it, e.g. when rotating): nothing to do
        self._stroke_list = strokes
        ents = [s for s in strokes if len(s[0])]
        old = self._stroke_state
        if old is not None and (self._ribbon is not None or not ents):
            changed = _stroke_diff(old["ents"], ents)
            if changed is not None and not changed:
                old["ents"] = ents  # same content: no new state (empty stays empty)
                return
            if changed is not None and self._ribbon is not None and self._caps is not None:
                # same layout (number of strokes, points per stroke, painting in front): reprocess only the changed strokes
                # and write them to their place in the buffer - when dragging, usually a small part changes,
                # but the processing costs per stroke (harbor scene: 24 ms per frame for 1,300 strokes)
                self._stroke_rev += 1
                olds = old["ents"]
                if any(olds[i][0] is not ents[i][0] or olds[i][1] is not ents[i][1] for i in changed):
                    self._stroke_geo_rev += 1
                counters.C["strich_upload"] += len(changed)
                self._patch_strokes(old, ents, changed)
                if self.VERIFY_STROKES:
                    self._verify_strokes(old)
                return
        self._stroke_rev += 1
        self._stroke_geo_rev += 1
        counters.C["strich_upload"] += len(ents)
        verts, idx, caps = stroke_buffers(ents)
        self._stroke_counts = (0 if idx is None else len(idx), 0 if caps is None else len(caps))
        # painting strokes are at the front of the list: their share of indices and ends (own pass)
        lead = []
        for s in ents:
            if len(s) > 5 and s[5] is not None:
                if len(s[0]) >= 2:
                    lead.append(len(s[0]))
            else:
                break
        self._paint_counts = (sum(6 * (n - 1) for n in lead), 2 * len(lead))
        # remember state (holds the arrays of the entries - comparison by identity stays valid)
        self._stroke_state = {"ents": ents, "verts": verts, "caps": caps}
        if verts is None:
            self._stroke_counts = (0, 0)
            return
        self._ribbon, self._caps = self._fill_stroke_buffers(verts, idx, caps, self._ribbon, self._caps)

    VERIFY_STROKES = False  # tests: after every partial upload check against the full processing

    def _patch_strokes(self, state, ents, changed):
        """Reprocess only the strokes changed (indices in ents): write their vertices and ends into the remembered arrays
        and - in contiguous ranges - into the GPU buffers. The layout is the same as at the last full
        upload (_stroke_diff), so indices and all positions remain correct."""
        verts, caps = state["verts"], state["caps"]
        if "at" not in state:  # position of each stroke: first vertex (2 per point), first end (2 per stroke with >= 2 points)
            n = np.array([len(e[0]) if len(e[0]) >= 2 else 0 for e in ents], np.int64)
            state["at"] = np.concatenate([[0], np.cumsum(2 * n)])
            state["cap_at"] = np.concatenate([[0], np.cumsum(2 * (n > 0))])
        at, cap_at = state["at"], state["cap_at"]
        state["ents"] = ents
        todo = [k for k in changed if len(ents[k][0]) >= 2]
        if not todo:
            return
        part = [ents[k] for k in todo]
        new_v, _, new_c = stroke_buffers(part)
        v_at = c_at = 0
        spans = []  # (first vertex, after the last) of the changed ranges
        for k in todo:
            a, b = int(at[k]), int(at[k + 1])
            verts[a:b] = new_v[v_at:v_at + (b - a)]
            v_at += b - a
            ca = int(cap_at[k])
            caps[ca:ca + 2] = new_c[c_at:c_at + 2]
            c_at += 2
            if spans and a - spans[-1][1] <= 4096:  # small gap: upload along with it instead of another write
                spans[-1][1] = b
            else:
                spans.append([a, b])
        row = verts.shape[1] * 4
        if sum(b - a for a, b in spans) * 2 > len(verts):
            self._ribbon[0].write(verts.tobytes())
        else:
            for a, b in spans:
                self._ribbon[0].write(verts[a:b].tobytes(), offset=a * row)
        self._caps[0].write(caps.tobytes())

    def _verify_strokes(self, state):
        verts, _ = ribbon_vertices(state["ents"])
        caps = cap_vertices(state["ents"])
        same = lambda x, y: x.shape == y.shape and np.allclose(x, y, rtol=1e-5, atol=1e-5)  # arc length: rounding
        assert same(verts, state["verts"]), "Strich-Teil-Upload weicht ab"
        assert same(caps, state["caps"]), "Strich-Enden im Teil-Upload weichen ab"
        gpu = np.frombuffer(self._ribbon[0].read(size=verts.nbytes), "f4").reshape(verts.shape)
        assert np.array_equal(gpu, state["verts"]), "GPU-Puffer der Striche weicht ab"
        gpu = np.frombuffer(self._caps[0].read(size=caps.nbytes), "f4").reshape(caps.shape)
        assert np.array_equal(gpu, state["caps"]), "GPU-Puffer der Strich-Enden weicht ab"

    def _fill_stroke_buffers(self, verts, idx, caps, ribbon, capbuf):
        """Write ribbon and end-point data into (growing) GPU buffers -> (ribbon, caps)."""
        ctx = self.ctx
        if ribbon is None or verts.nbytes > ribbon[3] or idx.nbytes > ribbon[4]:
            if ribbon is not None:
                for res in ribbon[:3]:
                    res.release()
            vcap, icap = max(verts.nbytes * 2, 1 << 16), max(idx.nbytes * 2, 1 << 15)
            vbo = ctx.buffer(reserve=vcap, dynamic=True)
            ibo = ctx.buffer(reserve=icap, dynamic=True)
            vao = ctx.vertex_array(self.ribbon_prog, [
                (vbo, "3f 3f 3f 1f 1f 1f 4f 4f 3f 1f", "in_pos", "in_prev", "in_next", "in_width", "in_side", "in_arc",
                 "in_color", "in_owner", "in_normal", "in_layer")],
                index_buffer=ibo, index_element_size=4)
            ribbon = (vbo, ibo, vao, vcap, icap)
        ribbon[0].write(verts.tobytes())
        ribbon[1].write(idx.tobytes())
        if capbuf is None or caps.nbytes > capbuf[2]:
            if capbuf is not None:
                capbuf[1].release()
                capbuf[0].release()
            cap = max(caps.nbytes * 2, 1 << 14)
            vbo = ctx.buffer(reserve=cap, dynamic=True)
            vao = ctx.vertex_array(self.cap_prog, [(vbo, "3f 1f 4f 4f 1f 3f 1f", "in_pos", "in_width", "in_color",
                                                    "in_owner", "in_style", "in_normal", "in_layer")])
            capbuf = (vbo, vao, cap)
        capbuf[0].write(caps.tobytes())
        return ribbon, capbuf

    def _upload_live(self, live):
        """Live strokes (running stroke, previews) into their own small buffer - new every frame, they are short."""
        ribbon, capbuf, _ = self._live
        live = [s for s in live if len(s[0])]
        verts, idx = ribbon_vertices(live) if live else (None, None)
        if verts is None:
            self._live = (ribbon, capbuf, (0, 0))
            return
        caps = cap_vertices(live)
        ribbon, capbuf = self._fill_stroke_buffers(verts, idx, caps, ribbon, capbuf)
        self._live = (ribbon, capbuf, (len(idx), len(caps)))

    def _upload_flip(self, flip):
        """Flipbook buffer: reprocessed only when the fingerprint of the drawings changes (it holds the arrays
        via the entries - ids stay valid). Per frame only the ranges of the named groups."""
        if not flip:
            self._flip_jobs = []
            return
        entries, key, groups, jobs = flip
        if key != self._flip_key or self._flip_buf[0] is None:
            verts, idx = ribbon_vertices(entries)
            if verts is None:
                self._flip_jobs, self._flip_key = [], key
                return
            caps = cap_vertices(entries)
            self._flip_buf = self._fill_stroke_buffers(verts, idx, caps, *self._flip_buf)
            # per entry (all with >= 2 points): 6 (n-1) indices and 2 ends
            n_idx = np.array([6 * (len(e[0]) - 1) for e in entries], np.int64)
            start = np.concatenate([[0], np.cumsum(n_idx)])
            self._flip_ranges = {g: (int(start[i0]), int(start[i0 + n] - start[i0]), 2 * i0, 2 * n)
                                 for g, (i0, n) in groups.items()}
            self._flip_key, self._flip_keep = key, entries
        self._flip_jobs = [(self._flip_ranges[g], fade) for g, fade in jobs if g in self._flip_ranges]

    @staticmethod
    def _plane_under(highlighted):
        """Glaze of a plane over a surface it lies on. Every visible plane glazes (artist 12.11.: an
        uninvolved plane was invisible over the geometry and was overlooked). The difference lies IN FRONT of a
        surface: drawing plane (2) and selected plane (1) cover there with their full fill, an uninvolved one (0)
        also there only with the glaze (soft / plane_s)."""
        return theme.ACTIVE_GLAZE

    def _plane_glaze_uniforms(self, prog):
        """Visible helper planes (render: planes) for plane_glaze in the stroke shader: center, half edges, fill color."""
        if "plane_n" not in prog:
            return
        planes = getattr(self, "_glaze_planes", [])[:16]
        prog["plane_n"].value = len(planes)
        if not planes:
            return
        pad = lambda rows, k: np.asarray(list(rows) + [rows[-1]] * (16 - len(rows)), "f4").reshape(16, k)
        for name, k, idx in (("plane_o", 3, 0), ("plane_u", 3, 1), ("plane_v", 3, 2), ("plane_c", 4, 3),
                             ("plane_k", 1, 4), ("plane_s", 1, 5)):
            if name in prog:
                prog[name].write(pad([p[idx] for p in planes], k).tobytes())

    def _draw_strokes(self, vp, size, focal, min_px, fade=1.0, part="lines", only=None):
        """Strokes as camera ribbons plus round ends (point sprites). Where the ribbon already lies,
        the end point loses the depth test - so nothing is blended twice.
        part: "paint" = only the painting strokes (at the front of the buffer), "lines" = the rest. only: exactly these ranges
        [(ribbon, caps, first index, indices, first end, ends)] (flipbook)."""
        if only is not None:
            jobs = [j for j in only if j[0] is not None and j[3]]
        else:
            n_all, n_all_caps = getattr(self, "_stroke_counts", (0, 0))
            p_idx, p_caps = getattr(self, "_paint_counts", (0, 0))
            if part == "paint":
                first_idx, n_idx, first_cap, n_caps = 0, p_idx, 0, p_caps
            else:
                first_idx, n_idx, first_cap, n_caps = p_idx, n_all - p_idx, p_caps, n_all_caps - p_caps
            jobs = [(self._ribbon, self._caps, first_idx, n_idx, first_cap, n_caps)] if n_idx and self._ribbon else []
            if part == "lines" and self._live[2][0]:  # the running stroke: on top, from its own buffer
                jobs.append((self._live[0], self._live[1], 0, self._live[2][0], 0, self._live[2][1]))
        if not jobs:
            return
        self._light_uniforms(self.ribbon_prog)
        self._light_uniforms(self.cap_prog)  # ends: same shadow as the adjoining line piece
        for prog in (self.ribbon_prog, self.cap_prog):
            self._occl_uniforms(prog)
            prog["vp"].write(_mat_bytes(vp))
            prog["half_vp"].value = (size[0] / 2, size[1] / 2)
            prog["focal"].value = focal
            prog["min_px"].value = min_px
            prog["bias"].value = STROKE_BIAS
            prog["grain"].value = PENCIL_GRAIN * theme.STROKE_GRAIN
            prog["fade"].value = fade
            self._plane_glaze_uniforms(prog)
        for ribbon, capbuf, f_idx, c_idx, f_cap, c_cap in jobs:
            ribbon[2].render(moderngl.TRIANGLES, vertices=c_idx, first=f_idx)
            self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
            # Qt gives a compatibility context: there point sprites (gl_PointCoord) need this switch, otherwise
            # the shader discards everything and the strokes end square
            self._gl.glEnable(GL_POINT_SPRITE)
            capbuf[1].render(moderngl.POINTS, vertices=c_cap, first=f_cap)
            self.ctx.disable(moderngl.PROGRAM_POINT_SIZE)

    def _light_uniforms(self, prog, surface=False):
        """Pass light mode and view direction to a program (lines, stroke ends or surfaces) - only what
        the program also uses."""
        def put(name, value):
            if name in prog:
                prog[name].value = value
        eye, back, ortho = self._view
        put("eye", tuple(float(x) for x in eye))
        put("view_back", tuple(float(x) for x in back))
        put("ortho", 1.0 if ortho else 0.0)
        light = self.light
        put("light_on", 1.0 if light else 0.0)
        put("sun_dir", tuple(float(x) for x in (light["dir"] if light else (0.0, 1.0, 0.0))))
        put("sun_col", tuple(float(x) for x in (light["col"] if light else (1.0, 1.0, 1.0))))
        put("sky_col", tuple(float(x) for x in (light["sky"] if light else (1.0, 1.0, 1.0))))
        if surface:
            put("away_dark", float(light["away"]) if light else 0.0)
        shadow = bool(light and light.get("shadow") and self._shadow is not None)
        put("shadow_on", 1.0 if shadow else 0.0)
        put("shadow_dark", float(light["shadow"]) if shadow else 0.0)
        if "shadow_vp" in prog:
            prog["shadow_vp"].write(_mat_bytes(self._shadow_vp))
        put("shadow_bias", self._shadow_bias)
        put("dome", float(light.get("dome", 0.0)) if light else 0.0)
        put("bands", float(light.get("bands", 0)) if light else 0.0)
        put("edge_gain", LIGHT_EDGE_GAIN)
        put("shadow_lift", getattr(self, "_shadow_lift", 0.02))
        if shadow and "shadow_map" in prog:
            self._shadow[1].use(location=SHADOW_UNIT)
            prog["shadow_map"].value = SHADOW_UNIT

    def _blockify(self, meshes, build=True):
        """Mesh list [(mesh, tint)] -> the same list with one entry (block, None) instead of the imported meshes
        that sit unchanged in the block (tint and visibility into its table). New or moved meshes
        stay individual until there are BLOCK_REBUILD of them (then rebuild, except build=False: gizmo drag)."""
        memo = self._block_memo
        if memo is not None and memo[0] is meshes and memo[2] is self._block:
            return memo[1]
        from .scene import MeshObject
        eligible = [(m, t) for m, t in meshes if type(m) is MeshObject and not m.missing and m.geo.triangle_count]
        block = self._block
        if len(eligible) < BLOCK_MIN:
            if block is not None:
                block.release()
                self._block = None
            self._block_memo = (meshes, meshes, None)
            return meshes
        if build:
            outside = sum(1 for m, _ in eligible if block is None or block.current(m) is None)
            stale = block is not None and len(block.meshes) - (len(eligible) - outside) > max(len(block.meshes) // 2, BLOCK_REBUILD)
            if block is None or outside >= BLOCK_REBUILD or stale:
                if block is not None:
                    block.release()
                t0 = time.perf_counter()
                block = self._block = _MeshBlock(self.ctx, [m for m, _ in eligible], self.block_progs)
                counters.C["block_neu"] += 1
                self.block_seconds = time.perf_counter() - t0
        if block is None:
            self._block_memo = (meshes, meshes, None)
            return meshes
        rows = block.rows()
        shown_before = rows[:, 1, 1].copy()
        rows[:, 1, 1] = 0.0
        out = [(block, None)]
        for m, t in meshes:
            k = block.current(m) if type(m) is MeshObject else None
            if k is None:
                out.append((m, t))
            else:
                rows[k, 0] = t
                rows[k, 1, 1] = 1.0
        if not np.array_equal(shown_before, rows[:, 1, 1]):
            block.vis_rev += 1
        self._block_memo = (meshes, out, block)
        return out

    def _in_view(self, vp, meshes, size=None):
        """Only the meshes whose bounding box touches the field of view and is at least CULL_PX large on screen
        (large USD hierarchies: thousands of meshes, per frame several passes with one draw call per mesh). The corners in world coordinates stay remembered as long as
        the same list comes (rotating, zooming: the viewport lists are not rebuilt)."""
        if len(meshes) < 64:
            return meshes
        memo = getattr(self, "_cull_memo", None)
        if memo is None or memo[0] is not meshes:
            corners = np.empty((len(meshes), 8, 4))
            for k, (m, _) in enumerate(meshes):
                lo, hi = (m.lo, m.hi) if isinstance(m, _MeshBlock) else m.geo.bbox
                c = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                corners[k] = c @ np.asarray(m.xform, float).T
            memo = self._cull_memo = (meshes, corners)
        clip = memo[1] @ np.asarray(vp, float).T  # (N, 8, 4)
        w = clip[..., 3]
        out = np.zeros(len(meshes), bool)
        for axis in range(3):
            out |= np.all(clip[..., axis] > w, axis=1) | np.all(clip[..., axis] < -w, axis=1)
        if size is not None:  # tiny: entirely in front of the camera and smaller than CULL_PX (extent of the bounding box)
            front = np.all(w > 1e-9, axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                ndc = clip[..., :2] / np.where(front[:, None], w, 1.0)[..., None]
            ext = (ndc.max(axis=1) - ndc.min(axis=1)) * (np.array(size, float) / 2)
            out |= front & (ext.max(axis=1) < CULL_PX)
        out &= np.array([not isinstance(m, _MeshBlock) for m, _ in meshes])  # the block: the GPU discards by itself
        if not out.any():
            return meshes
        return [e for e, o in zip(meshes, out) if not o]

    def _update_occlusion(self, vp, size, meshes=(), focal=1.0, surfaces=()):
        """Coverage map: per pixel the frontmost covering layer - surfaces and meshes - with distance to the camera
        (world units), |cos| between view and normal, radius (tolerance) and surface id. Surfaces, drawing aids
        and strokes compare themselves against it (cover() in OCCL_LIB): what belongs to the frontmost surface or lies in front of it
        is drawn, everything clearly behind it is not (X-Ray: softly) - independent of order and zoom level."""
        self._occl_on = False
        meshes = [(m, t) for m, t in meshes if m.geo.triangle_count]
        surfaces = [s for s in surfaces if s["count"] and s.get("occlude", True)]  # helper surfaces hide nothing
        if not meshes and not surfaces:
            return
        ctx = self.ctx
        if self._occl is None or self._occl[2] != size:
            if self._occl is not None:
                for res in self._occl[:2] + self._occl[3:]:
                    res.release()
            tex = ctx.texture(size, 4, dtype="f4")
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            depth = ctx.depth_renderbuffer(size)
            acc = ctx.texture(size, 1, dtype="f4")
            acc.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._occl = (ctx.framebuffer(color_attachments=[tex], depth_attachment=depth), tex, size, depth, acc,
                          ctx.framebuffer(color_attachments=[acc]))
        fbo = self._occl[0]
        fbo.use()
        ctx.viewport = (0, 0, size[0], size[1])
        fbo.clear(1e30, 1.0, 0.0, -1.0, depth=1.0)
        ctx.enable_only(moderngl.DEPTH_TEST)
        self._depth_mask(True)
        ctx.depth_func = "<"
        eye, back, ortho = self._view
        view = (tuple(float(x) for x in eye), tuple(float(x) for x in back), 1.0 if ortho else 0.0)
        if meshes:
            prog = self.occl_mesh_prog
            prog["eye"].value, prog["view_back"].value, prog["ortho"].value = view
            for mesh, _ in meshes:
                if isinstance(mesh, _MeshBlock):
                    self._draw_block(mesh, "occl", vp)
                    continue
                prog["mvp"].write(_mat_bytes(vp @ mesh.xform))
                prog["model"].write(_mat_bytes(mesh.xform))
                # tolerance only in pixels (OCCL_MIN_PX in the shader), not by mesh size: otherwise with a
                # large mesh (a whole airplane) a small sketch behind it would shine through far
                prog["radius"].value = MESH_OCCL_RADIUS
                prog["mesh_id"].value = float(mesh.id)
                self._mesh_buffers(mesh.geo).occl.render(moderngl.TRIANGLES)
        if surfaces:  # surfaces cover like meshes (lines on them belong to them: tolerance via their id)
            prog = self.occl_surf_prog
            prog["vp"].write(_mat_bytes(vp))
            prog["bias"].value = 0.0
            prog["eye"].value, prog["view_back"].value, prog["ortho"].value = view
            vao = self._surface_vao(prog)
            prog["occluders_only"].value = 1  # (helper surfaces drop out in the shader; radius and id from the table)
            vao.render(moderngl.TRIANGLES, vertices=sum(s["count"] for s in self._surfaces))
            counters.C["zeichenaufrufe"] += 1
        self._occl_on = True
        # opacity of the frontmost layer per pixel: many thin surfels on top of each other cover together
        acc_fbo = self._occl[5]
        acc_fbo.use()
        acc_fbo.clear(0.0, 0.0, 0.0, 0.0)
        ctx.enable_only(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        self._occl_dense_on = False
        if meshes:
            prog = self.occl_acc_mesh_prog
            self._occl_uniforms(prog)  # once per pass, per mesh only its id (hundreds with USD hierarchies)
            prog["acc_value"].value = 20.0
            for mesh, _ in meshes:
                if isinstance(mesh, _MeshBlock):
                    self._draw_block(mesh, "occl_acc", vp)
                    continue
                self._occl_owner(prog, owner=mesh.id)
                prog["mvp"].write(_mat_bytes(vp @ mesh.xform))
                prog["model"].write(_mat_bytes(mesh.xform))
                self._mesh_buffers(mesh.geo).occl_acc.render(moderngl.TRIANGLES)
        if surfaces:
            prog = self.occl_acc_surf_prog
            prog["vp"].write(_mat_bytes(vp))
            prog["bias"].value = 0.0
            vao = self._surface_vao(prog)
            self._occl_uniforms(prog)
            prog["occluders_only"].value = 1
            vao.render(moderngl.TRIANGLES, vertices=sum(s["count"] for s in self._surfaces))
            counters.C["zeichenaufrufe"] += 1
        self._occl_dense_on = True

    def _update_shadow(self, strokes, meshes):
        """Re-render the sun's shadow map if sun, strokes, surfaces or meshes have changed:
        depth from the sun's view (orthographic over the whole scene)."""
        light = self.light
        if not light or not light.get("shadow"):
            return
        if self.shadow_hold and self._shadow is not None:
            return  # in a gizmo drag: the shadows from the start of the drag stay, exact again after release
        mesh_key = tuple((m.geo, m.xform.tobytes(), getattr(m, "vis_rev", 0)) for m, _ in meshes)  # identity (update_pick)
        key = (tuple(np.round(light["dir"], 5)), self._stroke_geo_rev, mesh_key, self._surface_key)
        if key == self._shadow_key and self._shadow is not None:
            return
        self._shadow_key = key
        ctx = self.ctx
        # extent of the scene
        parts = [np.asarray(s[0], float) for s in strokes if len(s[0])]
        for m, _ in meshes:
            lo, hi = m.world_bounds()
            parts.append(np.array([lo, hi]))
        for s in self._surfaces:
            parts.append(np.array([s["lo"], s["hi"]]))
        if not parts:
            return
        allp = np.vstack(parts)
        lo, hi = allp.min(axis=0), allp.max(axis=0)
        center, radius = (lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) / 2, 1e-3) * 1.05
        d = np.asarray(light["dir"], float)
        d /= np.linalg.norm(d)
        eye = center + d * radius * 2
        up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.95 else np.array([0.0, 0.0, 1.0])
        f = -d
        r = np.cross(f, up)
        r /= np.linalg.norm(r)
        u = np.cross(r, f)
        view = np.eye(4)
        view[0, :3], view[1, :3], view[2, :3] = r, u, -f
        view[:3, 3] = -view[:3, :3] @ eye
        near, far = radius * 0.5, radius * 3.5
        proj = np.eye(4)
        proj[0, 0] = proj[1, 1] = 1.0 / radius
        proj[2, 2] = -2.0 / (far - near)
        proj[2, 3] = -(far + near) / (far - near)
        self._shadow_vp = proj @ view
        self._shadow_bias = SHADOW_BIAS
        self._shadow_lift = radius * 0.004  # lines: check this far toward the sun
        self._shadow_texel = 2.0 * radius / SHADOW_SIZE  # world size of a texel of the shadow map
        if self._shadow is None:
            tex = ctx.depth_texture((SHADOW_SIZE, SHADOW_SIZE))
            tex.compare_func = ""
            tex.repeat_x = tex.repeat_y = False
            self._shadow = (ctx.framebuffer(depth_attachment=tex), tex, SHADOW_SIZE)
        fbo = self._shadow[0]
        fbo.use()
        ctx.viewport = (0, 0, SHADOW_SIZE, SHADOW_SIZE)
        fbo.clear(depth=1.0)
        ctx.enable_only(moderngl.DEPTH_TEST)
        svp = _mat_bytes(self._shadow_vp)
        # lines as ribbons at their stroke width (across the sun), at least SHADOW_LINE_PX texels wide
        lines = [(np.asarray(s[0], float), s[1]) for s in strokes
                 if len(s[0]) >= 2 and not (len(s) > 5 and s[5] is not None)]
        if lines:
            data = shadow_ribbons(lines, d, self._shadow_texel * SHADOW_LINE_PX, r)
            if self._shadow_lines is None or data.nbytes > self._shadow_lines[0].size:
                if self._shadow_lines is not None:
                    self._shadow_lines[1].release()
                    self._shadow_lines[0].release()
                vbo = ctx.buffer(reserve=max(data.nbytes * 2, 1 << 14), dynamic=True)
                self._shadow_lines = (vbo, ctx.vertex_array(self.shadow_line_prog, [(vbo, "3f", "in_pos")]))
            self._shadow_lines[0].write(data.tobytes())
            self.shadow_line_prog["svp"].write(svp)
            self._shadow_lines[1].render(moderngl.TRIANGLES, vertices=len(data))
        # surfaces
        if self._surfaces:
            prog = self.shadow_surf_prog
            prog["vp"].write(svp)
            prog["bias"].value = 0.0
            vao = self._surface_vao(prog)
            vao.render(moderngl.TRIANGLES, vertices=sum(s["count"] for s in self._surfaces))
            counters.C["zeichenaufrufe"] += 1
        # Meshes
        prog = self.pick_prog
        for i, (mesh, _) in enumerate(meshes):
            if isinstance(mesh, _MeshBlock):
                self._draw_block(mesh, "pick", self._shadow_vp)
                continue
            if mesh.geo.triangle_count == 0:
                continue
            prog["mvp"].write(_mat_bytes(self._shadow_vp @ mesh.xform))
            prog["model"].write(_mat_bytes(mesh.xform))
            prog["mesh_index"].value = float(i + 1)
            self._mesh_buffers(mesh.geo).pick.render(moderngl.TRIANGLES)

    def _msaa_target(self, size):
        if self._msaa_size != size:
            if self._msaa_fbo is not None:
                for att in self._msaa_fbo.color_attachments:
                    att.release()
                self._msaa_fbo.depth_attachment.release()
                self._msaa_fbo.release()
            samples = min(self.MSAA_SAMPLES, self.ctx.max_samples)
            self._msaa_fbo = self.ctx.framebuffer(
                [self.ctx.renderbuffer(size, 4, samples=samples)],
                self.ctx.depth_renderbuffer(size, samples=samples))
            self._msaa_size = size
        return self._msaa_fbo

    def _draw_meshes(self, vp, light_eye, meshes, alpha):
        prog = self.mesh_prog
        self._light_uniforms(prog, surface=True)  # light mode: sun and shadow like with the surfaces
        prog["eye"].value = tuple(float(x) for x in light_eye)
        prog["alpha"].value = alpha
        if "lift" in prog:
            # check point a few texels of the shadow map away from the mesh: otherwise it shadows itself
            prog["lift"].value = max(getattr(self, "_shadow_lift", 0.02), 3.0 * getattr(self, "_shadow_texel", 0.0))
        for mesh, tint in meshes:
            if isinstance(mesh, _MeshBlock):
                self._draw_block(mesh, "shade", vp, light_eye=light_eye, alpha=alpha)
                continue
            if mesh.geo.triangle_count == 0:
                continue
            prog["mvp"].write(_mat_bytes(vp @ mesh.xform))
            prog["model"].write(_mat_bytes(mesh.xform))
            prog["tint"].value = tint
            self._mesh_buffers(mesh.geo).shade.render(moderngl.TRIANGLES)

    @staticmethod
    def _unblock(meshes):
        """Mesh list with the drawn parts of the block individually (wireframe)."""
        out = []
        for m, t in meshes:
            if isinstance(m, _MeshBlock):
                rows = m.rows()
                out += [(mm, tuple(rows[k, 0])) for k, mm in enumerate(m.meshes) if rows[k, 1, 1] > 0.5]
            else:
                out.append((m, t))
        return out

    def _draw_block(self, block, name, vp, vis_col=1, light_eye=None, alpha=1.0):
        """Draw the block in one pass (program like the one per mesh, per-part values from the table)."""
        prog = self.block_progs[name]
        prog["mvp"].write(_mat_bytes(vp))
        if name == "shade":
            self._light_uniforms(prog, surface=True)
            prog["eye"].value = tuple(float(x) for x in light_eye)
            prog["alpha"].value = alpha
            if "lift" in prog:
                prog["lift"].value = max(getattr(self, "_shadow_lift", 0.02), 3.0 * getattr(self, "_shadow_texel", 0.0))
        elif name == "occl":
            eye, back, ortho = self._view
            prog["eye"].value = tuple(float(x) for x in eye)
            prog["view_back"].value = tuple(float(x) for x in back)
            prog["ortho"].value = 1.0 if ortho else 0.0
            prog["radius"].value = MESH_OCCL_RADIUS
        elif name == "occl_acc":
            self._occl_uniforms(prog)
            prog["acc_value"].value = 20.0
        block.bind(prog, vis_col)
        block.vaos[name].render(moderngl.TRIANGLES)
        counters.C["zeichenaufrufe"] += 1

    def _draw_wires(self, vp, meshes, alpha, bias=0.0):
        """Wireframe: edges of the meshes in the stroke color (selected ones tinted like when shading); bias: shifted
        toward the camera (depth) so edges on their own surface do not flicker."""
        prog = self.wire_prog
        prog["bias"].value = float(bias)
        ink = theme.rgb(theme.STROKE_COLOR)
        for mesh, tint in self._unblock(meshes):
            if mesh.geo.triangle_count == 0:
                continue
            prog["mvp"].write(_mat_bytes(vp @ mesh.xform))
            if "model" in prog:
                prog["model"].write(_mat_bytes(mesh.xform))
            t = float(tint[3])
            prog["color"].value = (*(a + (b - a) * t for a, b in zip(ink, tint[:3])), float(alpha))
            self._mesh_buffers(mesh.geo).wire(prog, mesh.geo).render(moderngl.LINES)

    def _infinite_quad(self):
        """Per infinite plane a large quad around the point under the camera."""
        if not self._infinite:
            return None
        eye, _, ortho = self._view
        quads = []
        for layer in self._infinite:
            o, u, v, reach = layer["origin"], layer["u"], layer["v"], layer["reach"]
            n = np.cross(u, v)
            n /= max(np.linalg.norm(n), 1e-12)
            center = o if ortho else eye - n * float((eye - o) @ n)
            du, dv = u * reach, v * reach
            c = [center - du - dv, center + du - dv, center + du + dv, center - du + dv]
            quads.append(np.array([c[0], c[1], c[2], c[0], c[2], c[3]]))
        return np.vstack(quads)

    def _draw_infinite(self, vp, alpha_scale=1.0):
        if not self._infinite:
            return
        prog = self.inf_prog
        prog["vp"].write(_mat_bytes(vp))
        prog["bias"].value = 0.0
        eye, back, ortho = self._view
        prog["eye"].value = tuple(float(x) for x in eye)
        prog["view_back"].value = tuple(float(x) for x in back)
        prog["ortho"].value = 1.0 if ortho else 0.0
        self._occl_uniforms(prog)
        for k, layer in enumerate(self._infinite):
            self._occl_owner(prog, owner=layer.get("id", -1))
            a = layer["strength"] * alpha_scale
            core, tile = layer["core"], layer["tile"]
            prog["origin"].value = tuple(float(x) for x in layer["origin"])
            prog["axis_u"].value = tuple(float(x) for x in layer["u"])
            prog["axis_v"].value = tuple(float(x) for x in layer["v"])
            prog["has_core"].value = 1.0 if core is not None else 0.0
            prog["half_size"].value = core if core is not None else (0.0, 0.0)
            prog["tile_size"].value = tile
            prog["tile_offset"].value = core if core is not None else (0.0, 0.0)
            prog["grid_step"].value = (tile[0] / 10, tile[1] / 10)
            prog["fill"].value = (*layer["fill"][:3], theme.INFINITE_FILL_ALPHA * a)
            prog["line"].value = tuple(float(x) for x in layer["line"][:3])
            prog["grid_alpha"].value = theme.INFINITE_GRID_ALPHA * a
            prog["tile_alpha"].value = theme.INFINITE_TILE_ALPHA * a
            prog["reach"].value = float(layer["reach"])
            self._inf_vao.render(moderngl.TRIANGLES, vertices=6, first=self._inf_first + 6 * k)

    def _picture_texture(self, asset, data):
        tex = self._picture_textures.get(asset)
        if tex is None:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage
            from .pictures import MAX_TEXTURE
            image = QImage.fromData(data)
            if image.isNull():
                return None
            if max(image.width(), image.height()) > MAX_TEXTURE:
                image = image.scaled(MAX_TEXTURE, MAX_TEXTURE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image = image.convertToFormat(QImage.Format_RGBA8888).flipped(Qt.Vertical)
            tex = self.ctx.texture((image.width(), image.height()), 4,
                                   bytes(image.constBits())[:image.width() * image.height() * 4])
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            self._picture_textures[asset] = tex
        return tex

    def _draw_pictures(self, vp):
        """Projected images on helper planes and helper surfaces (pictures.py)."""
        if not self.pictures:
            return
        prog = self.picture_prog
        prog["vp"].write(_mat_bytes(vp))
        prog["bias"].value = 0.0
        self._occl_uniforms(prog)
        for asset, data, matrix, verts, owner in self.pictures:
            tex = self._picture_texture(asset, data)
            if tex is None:
                continue
            tex.use(location=PICTURE_UNIT)
            prog["picture"].value = PICTURE_UNIT
            prog["picture_m"].write(_mat_bytes(matrix))
            self._occl_owner(prog, owner=owner, under=0.0)
            buf = self.ctx.buffer(np.asarray(verts, "f4").tobytes())
            vao = self.ctx.simple_vertex_array(prog, buf, "in_pos")
            vao.render(moderngl.TRIANGLES)
            vao.release()
            buf.release()

    def _draw_planes(self, vp, planes, alpha_scale=1.0):
        if not planes and not self._infinite:
            return
        chunks = []
        for plane, *_ in planes:
            o, u, v = plane.origin, plane.axis_u, plane.axis_v
            hu, hv = u * plane.size_u / 2, v * plane.size_v / 2
            c = [o - hu - hv, o + hu - hv, o + hu + hv, o - hu + hv]
            fill = [c[0], c[1], c[2], c[0], c[2], c[3]]
            grid = []
            for i in range(1, 10):
                s = -1 + 2 * i / 10
                grid += [o + hu * s - hv, o + hu * s + hv, o + hv * s - hu, o + hv * s + hu]
            border = [c[0], c[1], c[1], c[2], c[2], c[3], c[3], c[0]]
            chunks.append(np.array(fill + grid + border))
        inf = self._infinite_quad()
        self._inf_first = sum(len(c) for c in chunks)
        self._flat_vertices(np.vstack(chunks + ([inf] if inf is not None else [])))

        prog = self.flat_prog
        prog["vp"].write(_mat_bytes(vp))
        prog["bias"].value = 0.0
        eye, back, ortho = self._view
        prog["eye"].value = tuple(float(x) for x in eye)
        prog["view_back"].value = tuple(float(x) for x in back)
        prog["ortho"].value = 1.0 if ortho else 0.0
        prog["milk"].value = theme.TRACING_VIEW_MILK
        self._occl_uniforms(prog)
        n_fill, n_grid, n_border = 6, 36, 8
        stride = n_fill + n_grid + n_border
        for k, (plane, fill, line, highlighted) in enumerate(planes):
            first = k * stride
            self._occl_owner(prog, owner=plane.id, under=self._plane_under(highlighted))
            prog["soft"].value = 0.0 if int(highlighted) else 1.0
            prog["color"].value = (*fill[:3], fill[3] * alpha_scale)
            prog["grain"].value = 1.0  # fibers only in the paper surface
            self._flat_vao.render(moderngl.TRIANGLES, vertices=n_fill, first=first)
            prog["grain"].value = 0.0
            grid_a, border_a, width = theme.PLANE_EMPHASIS[int(highlighted)]
            prog["under"].value = 0.0  # grid not over a surface
            prog["color"].value = (*line[:3], grid_a * alpha_scale)  # grid: hinted, active clearly
            self._flat_vao.render(moderngl.LINES, vertices=n_grid, first=first + n_fill)
            prog["under"].value = -1.0  # border stays
            prog["color"].value = (*line[:3], border_a * alpha_scale)
            self.ctx.line_width = width
            self._flat_vao.render(moderngl.LINES, vertices=n_border, first=first + n_fill + n_grid)
        self.ctx.line_width = 1.0
        self._draw_infinite(vp, alpha_scale)

    # --- Picking ---
    def update_pick(self, size, cam, proj, meshes):
        """Re-render the position buffer if camera, size or meshes have changed."""
        # the geometries themselves (comparison by identity), not their id: a freed id can get a new shape
        key = (size, cam.eye.tobytes(), cam.rot.tobytes(), np.asarray(proj).tobytes(),
               tuple((m.geo, m.xform.tobytes()) for m in meshes))
        if key == self._pick_key:
            return
        ctx = self.ctx
        if self._pick_size != size:
            if self._pick_fbo is not None:
                for att in self._pick_fbo.color_attachments:
                    att.release()
                self._pick_fbo.depth_attachment.release()
                self._pick_fbo.release()
            color = ctx.texture(size, 4, dtype="f4")
            prim = ctx.texture(size, 1, dtype="f4")  # triangle number per pixel
            self._pick_fbo = ctx.framebuffer([color, prim], ctx.depth_renderbuffer(size))
            self._pick_size = size
        self._pick_fbo.use()
        ctx.viewport = (0, 0, *size)
        ctx.scissor = None
        self._pick_fbo.clear(0, 0, 0, 0, depth=1.0)
        ctx.enable_only(moderngl.DEPTH_TEST)
        vp = proj @ view_matrix(cam)
        prog = self.pick_prog
        block, in_block = self._block, set()
        if block is not None and len(meshes) >= BLOCK_MIN:  # meshes in the block: one pass, number from the table
            from .scene import MeshObject
            rows = block.rows()
            rows[:, 2, 0] = 0.0
            for i, mesh in enumerate(meshes):
                k = block.current(mesh) if type(mesh) is MeshObject else None
                if k is not None:
                    rows[k, 2, 0] = float(i + 1)
                    in_block.add(i)
            if in_block:
                self._draw_block(block, "pick", vp, vis_col=2)
        for i, mesh in enumerate(meshes):
            if i in in_block or mesh.geo.triangle_count == 0:
                continue
            prog["mvp"].write(_mat_bytes(vp @ mesh.xform))
            prog["model"].write(_mat_bytes(mesh.xform))
            prog["mesh_index"].value = float(i + 1)
            self._mesh_buffers(mesh.geo).pick.render(moderngl.TRIANGLES)
        ctx.enable_only(moderngl.NOTHING)
        self._pick_meshes = list(meshes)
        self._pick_key = key

    def read_pick(self, x, y, w=1, h=1):
        """Rectangle from (x, y) bottom left in physical pixels -> (array (h, w, 4), x0, y0).
        Per pixel xyz of the surface and mesh number (0 = nothing hit). Clipped at the border."""
        if self._pick_fbo is None:
            return np.zeros((1, 1, 4), dtype="f4"), x, y
        pw, ph = self._pick_size
        x0, y0 = max(0, min(pw - 1, x)), max(0, min(ph - 1, y))
        w, h = max(1, min(w, pw - x0)), max(1, min(h, ph - y0))
        data = self._pick_fbo.read(viewport=(x0, y0, w, h), components=4, dtype="f4")
        return np.frombuffer(data, dtype="f4").reshape(h, w, 4), x0, y0

    def read_pick_points(self, coords):
        """Individual pixels (physical, bottom left) of the position buffer -> (array (N, 4), triangle numbers (N,)).
        The GPU collects them into one row, only that is read - instead of the whole rectangle around all points."""
        coords = np.ascontiguousarray(coords, dtype="f4").reshape(-1, 2)
        n = len(coords)
        if self._pick_fbo is None or not n:
            return np.zeros((n, 4), dtype="f4"), np.zeros(n, dtype=np.int64)
        ctx = self.ctx
        if getattr(self, "_gather", None) is None:
            prog = ctx.program(vertex_shader=PICK_GATHER_VS, fragment_shader=PICK_GATHER_FS)
            self._gather = [prog, None, None, None, 0]  # prog, vbo, vao, fbo, capacity
        g = self._gather
        if n > g[4]:
            for res in g[1:4]:
                if res is not None:
                    res.release()
            cap = max(n, 512) * 2
            g[1] = ctx.buffer(reserve=cap * 8, dynamic=True)
            g[2] = ctx.vertex_array(g[0], [(g[1], "2f", "in_xy")])
            g[3] = ctx.framebuffer([ctx.texture((cap, 1), 4, dtype="f4"), ctx.texture((cap, 1), 1, dtype="f4")])
            g[4] = cap
        g[1].write(coords.tobytes())
        g[3].use()
        ctx.viewport = (0, 0, n, 1)
        ctx.enable_only(moderngl.PROGRAM_POINT_SIZE)
        self._pick_fbo.color_attachments[0].use(location=0)
        self._pick_fbo.color_attachments[1].use(location=1)
        g[0]["pick_tex"].value = 0
        g[0]["prim_tex"].value = 1
        g[0]["count"].value = float(n)
        g[2].render(moderngl.POINTS, vertices=n)
        ctx.enable_only(moderngl.NOTHING)
        data = g[3].read(viewport=(0, 0, n, 1), components=4, dtype="f4")
        prim = g[3].read(viewport=(0, 0, n, 1), components=1, dtype="f4", attachment=1)
        return (np.frombuffer(data, dtype="f4").reshape(n, 4),
                np.round(np.frombuffer(prim, dtype="f4")).astype(np.int64))

    def points_visible(self, points):
        """(N,) bool: which points in the last frame are not hidden by a surface (coverage map, like with the
        strokes). Call right after render() (same context); binds its own target - afterwards bind the image again.
        Without a coverage map: all visible."""
        pts = np.ascontiguousarray(points, dtype="f4").reshape(-1, 3)
        n = len(pts)
        if not n or not getattr(self, "_occl_on", False):
            return np.ones(n, bool)
        ctx = self.ctx
        if getattr(self, "_vis", None) is None:
            self._vis = [ctx.program(vertex_shader=POINT_VIS_VS, fragment_shader=POINT_VIS_FS), None, None, None, 0]
        g = self._vis
        if n > g[4]:
            for res in g[1:4]:
                if res is not None:
                    res.release()
            cap = max(n, 512) * 2
            g[1] = ctx.buffer(reserve=cap * 12, dynamic=True)
            g[2] = ctx.vertex_array(g[0], [(g[1], "3f", "in_pos")])
            g[3] = ctx.framebuffer([ctx.texture((cap, 1), 1, dtype="f4")])
            g[4] = cap
        g[1].write(pts)
        g[3].use()
        ctx.viewport = (0, 0, n, 1)
        ctx.enable_only(moderngl.PROGRAM_POINT_SIZE)
        prog = g[0]
        prog["count"].value = float(n)
        prog["vp"].write(_mat_bytes(self._frame_vp))
        prog["size"].value = tuple(float(x) for x in self._frame_size)
        self._occl_uniforms(prog)
        g[2].render(moderngl.POINTS, vertices=n)
        ctx.enable_only(moderngl.NOTHING)
        vals = np.frombuffer(g[3].read(viewport=(0, 0, n, 1), components=1, dtype="f4"), dtype="f4")
        return vals > 0.5

    def id_map(self):
        """(h, w) float: per pixel of the last frame the id of the frontmost mesh or surface (copies under
        generators: their display id), -1 = nothing - color ID of the brief. All meshes cover, also semi-transparent ones;
        helper surfaces do not. Row 0 = bottom. Call right after render() (same context); rebuilds the coverage map
        - afterwards bind the image again."""
        w, h = self._frame_size
        self._update_occlusion(self._frame_vp, (w, h), getattr(self, "_frame_meshes", ()), 1.0, self._surfaces)
        if not self._occl_on:
            return np.full((h, w), -1.0, dtype="f4")
        return np.frombuffer(self._occl[1].read(), dtype="f4").reshape(h, w, 4)[..., 3].copy()

    def pick_mesh(self, index):
        return self._pick_meshes[index - 1] if 0 < index <= len(self._pick_meshes) else None
