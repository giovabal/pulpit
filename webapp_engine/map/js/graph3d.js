import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { strategy_label, layout_label, layout_long_label, LABELS_MODE_LABELS, THEME_LABELS } from './labels.js';
import { escHtml, fetchJson, fetchJsonOrNull, buildCommunityColorMaps, avgColor, makeEdgeWidthScale } from './utils.js';

// =============================================================================
// Constants
// =============================================================================

var BG_COLOR           = 0x112233;
var FADE_COLOR_HEX     = 0x1b2c3d;
var EDGE_OPACITY       = 0.30;
var EDGE_DARKEN        = 0.75;   // factor applied to averaged endpoint color
// Fat-line thickness in CSS pixels for the weighted-edge view. EDGE_WEIGHT_BASE_PX
// is the uniform width when weights are hidden (or a graph has no weight spread,
// e.g. the unweighted edge-weight strategy) — kept thin to match the default look.
var EDGE_WEIGHT_MIN_PX  = 0.6;
var EDGE_WEIGHT_MAX_PX  = 5.0;
var EDGE_WEIGHT_BASE_PX = 1.0;
var CURVE_SEGMENTS     = 10;     // line segments per curved edge
var CURVATURE          = 0.15;   // control-point offset as fraction of edge length
var SELF_LOOP_ARM      = 1.0;    // self-loop arm spread as multiple of node radius
var SELF_LOOP_HEIGHT   = 3.5;    // self-loop arc peak as multiple of node radius
var ZOOM_STEP          = 0.75;
// Cone arrowheads (one instance per edge), sized relative to the target node radius.
var ARROW_LEN_FACTOR    = 2.0;   // arrowhead length ÷ target node radius
var ARROW_RADIUS_FACTOR = 0.85;  // arrowhead base radius ÷ target node radius
var ARROW_OPACITY       = 0.9;   // arrowheads sit slightly more opaque than edges so direction reads clearly
// curve_edges: bow every edge (dark/light, all-curved look — two-way pairs then
// separate); when false (minimal/print) every edge is straight and a two-way pair
// superposes.
var THEMES_3D = {
    dark:    { bg: 0x112233, fade: 0x1b2c3d, edge_opacity: 0.30, curve_edges: true },
    light:   { bg: 0xf0f4f8, fade: 0xb4c3d2, edge_opacity: 0.40, curve_edges: true },
    minimal: { bg: 0xffffff, fade: 0xd2d2d2, edge_opacity: 0.25, curve_edges: false },
    print:   { bg: 0xffffff, fade: 0xc8c8c8, edge_opacity: 0.80, curve_edges: false },
};
// Node radii as fractions of spatial network diameter
var SIZE_MIN_FRAC      = 0.00225;
var SIZE_MAX_FRAC      = 0.01350;
var LABEL_SIZE_FRAC    = 0.5;    // show label when size > SIZE_MIN + FRAC*(SIZE_MAX-SIZE_MIN)
var BASE_MEASURE_KEYS = { in_deg: true, out_deg: true, fans: true, messages_count: true };

// =============================================================================
// State
// =============================================================================

var nodes_index      = {};   // id → node record (pos + metadata + mesh ref + orig_color)
var node_meshes      = [];   // THREE.Mesh list for raycasting
var edge_segments    = null; // single THREE.LineSegments for all edges
var arrow_mesh       = null; // single THREE.InstancedMesh of cone arrowheads (one instance per edge)
var edge_list        = [];   // [{source, target, vert_start, weight}] for color/arrow rebuilds
var label_objects    = {};   // id → CSS2DObject

var adj_out          = {};   // id → Set of target ids
var adj_in           = {};   // id → Set of source ids

var active_strategy        = null;
var community_color_maps   = {};
var community_strategy_data= {};
var accessory_data         = null;

var selected_node_id  = null;
var hovered_node_id   = null;
var current_size_key  = 'in_deg';
var current_group     = '';
var labels_mode       = 'on_size';

var current_data_dir      = window.DATA_DIR || 'data/';
var active_year           = null;
var year_sequence         = [];
var _year_switcher_inited = false;
var year_cache            = {};
var year_cache_pend       = {};
var animation_frame_id_3d = null;

var active_layout   = 'fa2';
var layout_cache_3d = {};
var layout_anim_id  = null;
var _layout_bbox    = null;   // bounding box of the initial FA2 3D layout; used to rescale extra layouts
var colored_edges   = true;
var show_edge_weight = false;   // off by default; maps edge weight → line thickness
var show_edge_arrows = false;   // off by default; draws a cone arrowhead at each edge's target
var edge_opacity_3d = EDGE_OPACITY;   // live edge-line alpha; re-syncs to the style on style change, overridable by the opacity slider
var active_theme_3d = 'dark';

// Diameter-derived size bounds (set in build_graph, reused in apply_node_size)
var g_size_min       = 1;
var g_size_max       = 10;
var g_label_threshold= 5;

// =============================================================================
// Three.js objects
// =============================================================================

var scene, camera, renderer, label_renderer, controls;
var raycaster   = new THREE.Raycaster();
var pointer     = new THREE.Vector2();
var sphere_geom = new THREE.SphereGeometry(1, 32, 20);
// Unit cone pointing +Y (apex at +0.5, base at -0.5); scaled/oriented per edge.
var cone_geom   = new THREE.ConeGeometry(1, 1, 10);
var fade_color  = new THREE.Color(FADE_COLOR_HEX);

// Reused scratch objects so per-edge arrow transforms don't allocate in hot loops.
var _AR_UP   = new THREE.Vector3(0, 1, 0);
var _ar_sp   = new THREE.Vector3();
var _ar_tp   = new THREE.Vector3();
var _ar_dir  = new THREE.Vector3();
var _ar_pos  = new THREE.Vector3();
var _ar_q    = new THREE.Quaternion();
var _ar_scl  = new THREE.Vector3();
var _ar_zero = new THREE.Matrix4().makeScale(0, 0, 0);
var _GRAY3   = new THREE.Color(0.30, 0.30, 0.30);

// =============================================================================
// Helpers
// =============================================================================

function el(id) { return document.getElementById(id); }


function parse_color(css_rgb) {
    var parts = css_rgb.split(',').map(function(s) { return parseInt(s.trim(), 10); });
    return new THREE.Color(parts[0] / 255, parts[1] / 255, parts[2] / 255);
}

function avg_darken(c1, c2) {
    var a = avgColor([c1.r, c1.g, c1.b], [c2.r, c2.g, c2.b], EDGE_DARKEN);
    return new THREE.Color(a[0], a[1], a[2]);
}

// Quadratic Bézier control point: mid offset perpendicular to edge direction
var _up  = new THREE.Vector3(0, 1, 0);
var _alt = new THREE.Vector3(1, 0, 0);
function curve_control(src_pos, tgt_pos) {
    var mid = new THREE.Vector3().addVectors(src_pos, tgt_pos).multiplyScalar(0.5);
    var dir = new THREE.Vector3().subVectors(tgt_pos, src_pos);
    var len = dir.length();
    if (len < 1e-9) return mid;
    var perp = new THREE.Vector3().crossVectors(dir, _up);
    if (perp.length() < 1e-6) perp.crossVectors(dir, _alt);
    perp.normalize().multiplyScalar(len * CURVATURE);
    return mid.add(perp);
}

// Whether edges are drawn curved in the active style: the curved styles (dark/light)
// bow every edge — a two-way tie's two directions then land on opposite arcs and
// separate; the straight styles (minimal/print) draw every edge straight, so a
// two-way tie's two edges superpose, by design.
function _edge_curves() {
    return (THEMES_3D[active_theme_3d] || THEMES_3D.dark).curve_edges;
}

// Control point for an edge: a perpendicular offset (a curved arc) when curved,
// else the plain midpoint, which collapses the quadratic Bézier to a straight line.
function _control_point(src_pos, tgt_pos, curved) {
    if (curved) return curve_control(src_pos, tgt_pos);
    return new THREE.Vector3().addVectors(src_pos, tgt_pos).multiplyScalar(0.5);
}

// =============================================================================
// Scene initialisation
// =============================================================================

function init_three() {
    var container = el('canvas-container');

    scene = new THREE.Scene();
    scene.background = new THREE.Color(BG_COLOR);

    // Ambient light keeps dark sides readable; directional light follows the
    // camera so shading is consistent regardless of graph orientation.
    scene.add(new THREE.AmbientLight(0xffffff, 0.70));
    var cam_light = new THREE.DirectionalLight(0xffffff, 0.85);
    cam_light.position.set(0, 0, 1);  // local space: points straight at the scene

    camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.01, 1e8);
    camera.position.z = 2000;
    camera.add(cam_light);
    scene.add(camera);

    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    label_renderer = new CSS2DRenderer();
    label_renderer.setSize(container.clientWidth, container.clientHeight);
    label_renderer.domElement.style.position = 'absolute';
    label_renderer.domElement.style.top = '0';
    label_renderer.domElement.style.pointerEvents = 'none';
    container.appendChild(label_renderer.domElement);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping  = true;
    controls.dampingFactor  = 0.05;
    controls.screenSpacePanning = false;

    window.addEventListener('resize', on_resize);
    renderer.domElement.addEventListener('click', on_canvas_click);
    renderer.domElement.addEventListener('mousemove', on_canvas_mousemove);

    animate();
}

function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
    label_renderer.render(scene, camera);
}

function on_resize() {
    var container = el('canvas-container');
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
    label_renderer.setSize(container.clientWidth, container.clientHeight);
    // Fat-line thickness is computed in the shader against the viewport size.
    if (edge_segments) edge_segments.material.resolution.set(container.clientWidth, container.clientHeight);
}

// =============================================================================
// Graph building
// =============================================================================

function node_size_from_metric(metric_val, minV, range) {
    var t = (metric_val - minV) / range;
    return g_size_min + t * (g_size_max - g_size_min);
}

function build_graph(pos_data, ch_data) {
    var measure_map = {};
    ch_data.nodes.forEach(function(n) { measure_map[n.id] = n; });

    // ── 1. Spatial bounding box → diameter → size bounds ──────────────────────
    var min_x = Infinity, max_x = -Infinity;
    var min_y = Infinity, max_y = -Infinity;
    var min_z = Infinity, max_z = -Infinity;
    pos_data.nodes.forEach(function(p) {
        if (p.x < min_x) min_x = p.x; if (p.x > max_x) max_x = p.x;
        if (p.y < min_y) min_y = p.y; if (p.y > max_y) max_y = p.y;
        if (p.z < min_z) min_z = p.z; if (p.z > max_z) max_z = p.z;
    });
    var dx = max_x - min_x, dy = max_y - min_y, dz = max_z - min_z;
    _layout_bbox = { cx: (min_x + max_x) / 2, cy: (min_y + max_y) / 2, cz: (min_z + max_z) / 2, w: dx || 1, h: dy || 1, d: dz || 1 };
    var diameter = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
    g_size_min        = diameter * SIZE_MIN_FRAC;
    g_size_max        = diameter * SIZE_MAX_FRAC;
    g_label_threshold = g_size_min + LABEL_SIZE_FRAC * (g_size_max - g_size_min);

    // ── 2. Metric range for initial size key ───────────────────────────────────
    var vals  = ch_data.nodes.map(function(n) { return n[current_size_key] || 0; });
    var minV  = Math.min.apply(null, vals);
    var range = (Math.max.apply(null, vals) - minV) || 1;

    // ── 3. Build node meshes ───────────────────────────────────────────────────
    pos_data.nodes.forEach(function(pos) {
        var m     = measure_map[pos.id] || {};
        var size  = node_size_from_metric((m[current_size_key] || 0), minV, range);
        var color = m.color ? parse_color(m.color) : new THREE.Color(0.5, 0.5, 0.5);

        var mat  = new THREE.MeshLambertMaterial({ color: color.clone() });
        var mesh = new THREE.Mesh(sphere_geom, mat);
        mesh.position.set(pos.x, pos.y, pos.z);
        mesh.scale.setScalar(size);
        mesh.userData.id = pos.id;

        nodes_index[pos.id] = Object.assign({}, m, {
            x: pos.x, y: pos.y, z: pos.z,
            size: size,
            orig_color: color.clone(),
            mesh: mesh,
        });

        scene.add(mesh);
        node_meshes.push(mesh);

        // CSS2D label
        var div = document.createElement('div');
        div.className = 'node-label';
        div.textContent = m.label || pos.id;
        var lbl = new CSS2DObject(div);
        lbl.position.set(0, 1.3, 0);   // local space: sphere radius = 1, scale handles world size
        lbl.visible = (labels_mode === 'on_size' && size >= g_label_threshold)
                   || (labels_mode === 'always');
        mesh.add(lbl);
        label_objects[pos.id] = lbl;

        adj_out[pos.id] = new Set();
        adj_in[pos.id]  = new Set();
    });

    // ── 4. Build curved edges ──────────────────────────────────────────────────
    // Each edge is a quadratic Bézier approximated with CURVE_SEGMENTS line
    // segments → CURVE_SEGMENTS+1 sample points → CURVE_SEGMENTS pairs in
    // LineSegments (2 verts per segment).
    // Verts per edge: CURVE_SEGMENTS * 2
    var VERTS_PER_EDGE = CURVE_SEGMENTS * 2;
    var n_edges = pos_data.edges.length;  // upper bound (some may be skipped)
    var positions = new Float32Array(n_edges * VERTS_PER_EDGE * 3);
    var colors    = new Float32Array(n_edges * VERTS_PER_EDGE * 3);
    var vert_cursor = 0;

    pos_data.edges.forEach(function(e) {
        var src = nodes_index[e.source];
        var tgt = nodes_index[e.target];
        if (!src || !tgt) return;

        var sp, tp, cp;
        if (e.source === e.target) {
            var arm  = src.size * SELF_LOOP_ARM;
            var peak = src.size * SELF_LOOP_HEIGHT;
            sp = new THREE.Vector3(src.x - arm, src.y, src.z);
            tp = new THREE.Vector3(src.x + arm, src.y, src.z);
            cp = new THREE.Vector3(src.x, src.y + peak, src.z);
        } else {
            sp = new THREE.Vector3(src.x, src.y, src.z);
            tp = new THREE.Vector3(tgt.x, tgt.y, tgt.z);
            cp = _control_point(sp, tp, _edge_curves());
        }
        var curve = new THREE.QuadraticBezierCurve3(sp, cp, tp);
        var pts = curve.getPoints(CURVE_SEGMENTS);   // CURVE_SEGMENTS+1 points

        var c = avg_darken(src.orig_color, tgt.orig_color);
        var vert_start = vert_cursor;

        for (var i = 0; i < CURVE_SEGMENTS; i++) {
            var p0 = pts[i], p1 = pts[i + 1];
            positions[vert_cursor * 3]     = p0.x;
            positions[vert_cursor * 3 + 1] = p0.y;
            positions[vert_cursor * 3 + 2] = p0.z;
            colors[vert_cursor * 3]        = c.r;
            colors[vert_cursor * 3 + 1]    = c.g;
            colors[vert_cursor * 3 + 2]    = c.b;
            vert_cursor++;

            positions[vert_cursor * 3]     = p1.x;
            positions[vert_cursor * 3 + 1] = p1.y;
            positions[vert_cursor * 3 + 2] = p1.z;
            colors[vert_cursor * 3]        = c.r;
            colors[vert_cursor * 3 + 1]    = c.g;
            colors[vert_cursor * 3 + 2]    = c.b;
            vert_cursor++;
        }

        edge_list.push({ source: e.source, target: e.target, vert_start: vert_start, weight: e.weight });

        if (adj_out[e.source]) adj_out[e.source].add(e.target);
        if (adj_in[e.target])  adj_in[e.target].add(e.source);
    });

    // Trim to actual used size (some edges may have been skipped)
    var used = vert_cursor * 3;
    edge_segments = _build_edge_object(positions.subarray(0, used), colors.subarray(0, used), vert_cursor / 2, edge_opacity_3d);
    scene.add(edge_segments);
    apply_edge_widths_3d();
    _build_arrow_mesh();
}

// =============================================================================
// Fat-line edges (variable thickness)
// =============================================================================
// WebGL ignores LineBasicMaterial.linewidth, so variable-width edges use the
// "fat lines" addon (LineSegments2 + LineMaterial). LineSegmentsGeometry stores
// positions/colors in interleaved instanced buffers whose flat layout matches
// the per-vertex Float32Arrays this file already builds, so every in-place
// color/position update elsewhere keeps the same indexing — it just targets
// `instanceStart.data` / `instanceColorStart.data` instead of a plain attribute.
// Per-edge width is carried by an extra `instanceWidth` instanced attribute that
// a tiny onBeforeCompile patch multiplies into the line half-width.

function _make_edge_material(opacity) {
    var mat = new LineMaterial({
        vertexColors: true,
        transparent:  true,
        opacity:      opacity,
        linewidth:    1,        // base; per-instance instanceWidth carries the actual px width
        worldUnits:   false,    // linewidth is in screen pixels (zoom-independent)
    });
    var container = el('canvas-container');
    // Fat-line width divides by resolution in the shader; fall back to the window
    // size if the container reports 0 (e.g. built while the tab is backgrounded),
    // so edges never collapse to a zero-width / NaN line. on_resize keeps it current.
    var rw = container.clientWidth || window.innerWidth || 1;
    var rh = container.clientHeight || window.innerHeight || 1;
    mat.resolution.set(rw, rh);
    mat.onBeforeCompile = function(shader) {
        shader.vertexShader = shader.vertexShader
            .replace(
                'attribute vec3 instanceStart;',
                'attribute vec3 instanceStart;\nattribute float instanceWidth;')
            .replace('offset *= linewidth;', 'offset *= linewidth * instanceWidth;')
            .replace('float hw = linewidth * 0.5;', 'float hw = linewidth * instanceWidth * 0.5;');
    };
    // All edge materials share the identical patch, so they can share one program.
    mat.customProgramCacheKey = function() { return 'pulpit-edge-width'; };
    return mat;
}

// Build the single LineSegments2 carrying every edge. `positions`/`colors` are
// the trimmed flat [x,y,z,…] / [r,g,b,…] arrays (2 vertices per segment);
// `n_instances` is the segment count (vert count / 2).
function _build_edge_object(positions, colors, n_instances, opacity) {
    var geom = new LineSegmentsGeometry();
    geom.setPositions(positions);
    geom.setColors(colors);
    // Per-segment width; filled by apply_edge_widths_3d() before first paint.
    var widths = new Float32Array(n_instances);
    widths.fill(EDGE_WEIGHT_BASE_PX);
    geom.setAttribute('instanceWidth', new THREE.InstancedBufferAttribute(widths, 1));
    var obj = new LineSegments2(geom, _make_edge_material(opacity));
    // Positions are rewritten in place during layout/year animations without
    // recomputing the bounding sphere; skip culling so edges never blink out.
    obj.frustumCulled = false;
    return obj;
}

// Set each edge's instanceWidth from its weight when the "show edge weight"
// toggle is on; otherwise a uniform thin base width. One width value per segment
// (CURVE_SEGMENTS segments per edge, contiguous from vert_start / 2).
function apply_edge_widths_3d() {
    if (!edge_segments) return;
    var wattr = edge_segments.geometry.getAttribute('instanceWidth');
    if (!wattr) return;
    var arr = wattr.array;
    if (!show_edge_weight) {
        arr.fill(EDGE_WEIGHT_BASE_PX);
    } else {
        var weights = edge_list.map(function(e) { return e.weight || 0; });
        var scale = makeEdgeWidthScale(weights, EDGE_WEIGHT_MIN_PX, EDGE_WEIGHT_MAX_PX, EDGE_WEIGHT_BASE_PX);
        edge_list.forEach(function(e) {
            var px = scale(e.weight || 0);
            var seg0 = e.vert_start / 2;
            for (var i = 0; i < CURVE_SEGMENTS; i++) arr[seg0 + i] = px;
        });
    }
    wattr.needsUpdate = true;
}

// =============================================================================
// Cone arrowheads (one InstancedMesh instance per edge)
// =============================================================================

// Compose the world matrix for an edge's arrowhead: a cone whose tip sits on the
// target node's surface and points along the curve's tangent at the target.
// Returns false for self-loops / degenerate edges (which get no arrow).
function _edge_arrow_transform(e, outMatrix) {
    var src = nodes_index[e.source], tgt = nodes_index[e.target];
    if (!src || !tgt || e.source === e.target) return false;
    _ar_sp.set(src.x, src.y, src.z || 0);
    _ar_tp.set(tgt.x, tgt.y, tgt.z || 0);
    var cp = _control_point(_ar_sp, _ar_tp, _edge_curves());
    _ar_dir.subVectors(_ar_tp, cp);                       // curve tangent at the target end
    if (_ar_dir.lengthSq() < 1e-12) _ar_dir.subVectors(_ar_tp, _ar_sp);
    if (_ar_dir.lengthSq() < 1e-12) return false;
    _ar_dir.normalize();
    var len = tgt.size * ARROW_LEN_FACTOR;
    var rad = tgt.size * ARROW_RADIUS_FACTOR;
    // Cone apex (local +len/2 after scaling) should land on the node surface, i.e.
    // at tp - dir*radius; so the cone centre sits a further len/2 back along dir.
    _ar_pos.copy(_ar_tp).addScaledVector(_ar_dir, -(tgt.size + len / 2));
    _ar_q.setFromUnitVectors(_AR_UP, _ar_dir);
    _ar_scl.set(rad, len, rad);
    outMatrix.compose(_ar_pos, _ar_q, _ar_scl);
    return true;
}

// (Re)create the arrowhead InstancedMesh for the current edge_list, disposing any
// previous one. Colours are initialised to the edges' base colours; visibility
// follows the toggle.
function _build_arrow_mesh() {
    if (arrow_mesh) {
        scene.remove(arrow_mesh);
        arrow_mesh.dispose();            // frees the per-instance matrix/color buffers
        arrow_mesh.material.dispose();   // cone_geom is shared — never disposed here
        arrow_mesh = null;
    }
    var n = edge_list.length;
    if (!n) return;
    var mat = new THREE.MeshBasicMaterial({ transparent: true, opacity: ARROW_OPACITY });
    arrow_mesh = new THREE.InstancedMesh(cone_geom, mat, n);
    arrow_mesh.frustumCulled = false;
    arrow_mesh.visible = show_edge_arrows;
    var m = new THREE.Matrix4();
    for (var i = 0; i < n; i++) {
        arrow_mesh.setMatrixAt(i, _edge_arrow_transform(edge_list[i], m) ? m : _ar_zero);
        arrow_mesh.setColorAt(i, _base_edge_color(edge_list[i]));
    }
    arrow_mesh.instanceMatrix.needsUpdate = true;
    if (arrow_mesh.instanceColor) arrow_mesh.instanceColor.needsUpdate = true;
    scene.add(arrow_mesh);
}

// Recompute every arrowhead's transform (after node positions move).
function _update_arrow_matrices() {
    if (!arrow_mesh) return;
    var m = new THREE.Matrix4();
    edge_list.forEach(function(e, i) {
        arrow_mesh.setMatrixAt(i, _edge_arrow_transform(e, m) ? m : _ar_zero);
    });
    arrow_mesh.instanceMatrix.needsUpdate = true;
}

// =============================================================================
// Edge color rebuild (called after node color changes)
// =============================================================================

// An edge's colour in the default (unselected) view.
function _base_edge_color(e) {
    var src = nodes_index[e.source], tgt = nodes_index[e.target];
    if (!src || !tgt) return _GRAY3;
    return colored_edges ? avg_darken(src.orig_color, tgt.orig_color) : _GRAY3;
}

// Paint every edge (and its arrowhead) with the colour returned by colorOf(e).
// Centralises the edge colour-buffer write so the arrowheads always match.
function _paint_edges(colorOf) {
    var arr = (edge_segments && edge_segments.geometry.attributes.instanceColorStart)
        ? edge_segments.geometry.attributes.instanceColorStart.data.array
        : null;
    edge_list.forEach(function(e, idx) {
        var c = colorOf(e);
        if (arr) {
            var base = e.vert_start * 3;
            for (var i = 0; i < CURVE_SEGMENTS * 2; i++) {
                arr[base + i * 3]     = c.r;
                arr[base + i * 3 + 1] = c.g;
                arr[base + i * 3 + 2] = c.b;
            }
        }
        if (arrow_mesh) arrow_mesh.setColorAt(idx, c);
    });
    if (arr) edge_segments.geometry.attributes.instanceColorStart.data.needsUpdate = true;
    if (arrow_mesh && arrow_mesh.instanceColor) arrow_mesh.instanceColor.needsUpdate = true;
}

function rebuild_edge_colors() {
    if (!edge_list.length) return;
    _paint_edges(_base_edge_color);
}

function _rebuild_edge_positions() {
    if (!edge_segments || !edge_list.length) return;
    var posBuf = edge_segments.geometry.attributes.instanceStart.data;
    var arr = posBuf.array;
    edge_list.forEach(function(e) {
        var src = nodes_index[e.source], tgt = nodes_index[e.target];
        if (!src || !tgt) return;
        var sp, tp, cp;
        if (e.source === e.target) {
            var arm = src.size * SELF_LOOP_ARM, peak = src.size * SELF_LOOP_HEIGHT;
            sp = new THREE.Vector3(src.x - arm, src.y, src.z);
            tp = new THREE.Vector3(src.x + arm, src.y, src.z);
            cp = new THREE.Vector3(src.x, src.y + peak, src.z);
        } else {
            sp = new THREE.Vector3(src.x, src.y, src.z);
            tp = new THREE.Vector3(tgt.x, tgt.y, tgt.z);
            cp = _control_point(sp, tp, _edge_curves());
        }
        var pts = new THREE.QuadraticBezierCurve3(sp, cp, tp).getPoints(CURVE_SEGMENTS);
        for (var i = 0; i < CURVE_SEGMENTS; i++) {
            var base = (e.vert_start + i * 2) * 3;
            arr[base]   = pts[i].x;   arr[base+1] = pts[i].y;   arr[base+2] = pts[i].z;
            arr[base+3] = pts[i+1].x; arr[base+4] = pts[i+1].y; arr[base+5] = pts[i+1].z;
        }
    });
    posBuf.needsUpdate = true;
    _update_arrow_matrices();
}

// =============================================================================
// Themes, layout switching
// =============================================================================

function apply_theme_3d(theme) {
    var t = THEMES_3D[theme] || THEMES_3D.dark;
    var prev_curve_edges = (THEMES_3D[active_theme_3d] || THEMES_3D.dark).curve_edges;
    active_theme_3d = theme;
    if (scene) scene.background.setHex(t.bg);
    fade_color.setHex(t.fade);
    // Edge opacity re-syncs to the style's tuned value; the slider re-defaults to it.
    edge_opacity_3d = t.edge_opacity;
    var op_slider = el('edge-opacity-slider');
    if (op_slider) op_slider.value = edge_opacity_3d;
    if (edge_segments) edge_segments.material.opacity = edge_opacity_3d;
    // Edges curve in dark/light but are straight in minimal/print; when that flips,
    // rebuild the edge geometry (and arrowheads) to match.
    if (t.curve_edges !== prev_curve_edges) _rebuild_edge_positions();
    document.body.setAttribute('data-theme3d', theme);
    var bgHex = '#' + t.bg.toString(16).padStart(6, '0');
    document.documentElement.style.backgroundColor = bgHex;
    // The 3D viewer's theme is a per-session display choice, deliberately not
    // persisted: it always boots dark and never reads or writes the shared
    // ``pulpit_theme`` key that the live webapp and table exports use.
}

// =============================================================================
// Info bar
// =============================================================================

function update_info_bar() {
    var chips_el = el('graph-info-chips');
    if (!chips_el) return;

    var chips = [];
    chips.push(layout_label(active_layout));
    if (active_strategy) chips.push(strategy_label(active_strategy));

    var size_sel = el('size-select');
    if (size_sel && size_sel.options.length > 0)
        chips.push(size_sel.options[size_sel.selectedIndex].text);

    chips.push(THEME_LABELS[active_theme_3d] || active_theme_3d);
    chips.push(LABELS_MODE_LABELS[labels_mode] || labels_mode);
    chips.push(colored_edges ? 'Colored edges' : 'Plain edges');
    if (show_edge_weight) chips.push('Weighted width');
    if (show_edge_arrows) chips.push('Arrows');

    var html = chips.map(function(t) { return '<span class="info-chip">' + t + '</span>'; }).join('');
    if (current_group) html += '<span class="info-chip info-chip--filter">' + current_group + '</span>';

    chips_el.innerHTML = html;
}

(function() {
    var toggle = el('graph-info-toggle');
    var bar    = el('graph-info-bar');
    if (!toggle || !bar) return;
    bar.addEventListener('click', function() {
        bar.classList.toggle('is-expanded');
        toggle.setAttribute('aria-expanded', String(bar.classList.contains('is-expanded')));
    });
})();

function build_layout_selector() {
    var layouts = window.EXTRA_LAYOUTS_3D || [];
    if (!layouts.length) return;
    var sel = el('layout-select');
    sel.innerHTML = layouts.map(function(l) {
        return '<option value="' + l + '">' + layout_long_label(l) + '</option>';
    }).join('');
    el('layout-select-group').style.display = '';
}

function _rescale_to_fa2(pos_data) {
    if (!_layout_bbox) return pos_data;
    var nodes = pos_data.nodes;
    var nx0 = Infinity, nx1 = -Infinity, ny0 = Infinity, ny1 = -Infinity, nz0 = Infinity, nz1 = -Infinity;
    nodes.forEach(function(n) {
        if (n.x < nx0) nx0 = n.x; if (n.x > nx1) nx1 = n.x;
        if (n.y < ny0) ny0 = n.y; if (n.y > ny1) ny1 = n.y;
        var z = n.z || 0;
        if (z < nz0) nz0 = z; if (z > nz1) nz1 = z;
    });
    var src_w = nx1 - nx0 || 1, src_h = ny1 - ny0 || 1, src_d = nz1 - nz0 || 1;
    var scale = Math.min(_layout_bbox.w / src_w, _layout_bbox.h / src_h, _layout_bbox.d / src_d);
    var src_cx = (nx0 + nx1) / 2, src_cy = (ny0 + ny1) / 2, src_cz = (nz0 + nz1) / 2;
    return {
        nodes: nodes.map(function(n) {
            return {
                id: n.id,
                x: _layout_bbox.cx + (n.x - src_cx) * scale,
                y: _layout_bbox.cy + (n.y - src_cy) * scale,
                z: _layout_bbox.cz + ((n.z || 0) - src_cz) * scale,
            };
        }),
    };
}

function switch_layout_3d(algo) {
    active_layout = algo;
    var filename = algo === 'fa2' ? 'channel_position_3d.json' : 'channel_position_3d_' + algo + '.json';
    var key = current_data_dir + filename;
    if (layout_cache_3d[key]) { _animate_layout_3d(layout_cache_3d[key]); return; }
    fetchJson(current_data_dir + filename)
        .then(function(data) {
            var display = algo === 'fa2' ? data : _rescale_to_fa2(data);
            layout_cache_3d[key] = display;
            _animate_layout_3d(display);
        })
        .catch(function(err) {
            console.error('Failed to load layout', algo, err);
            active_layout = 'fa2';
            if (el('layout-select')) el('layout-select').value = 'fa2';
        });
}

function _animate_layout_3d(pos_data) {
    var new_pos = {};
    pos_data.nodes.forEach(function(n) { new_pos[n.id] = n; });
    var old_pos = {};
    Object.keys(nodes_index).forEach(function(id) {
        var n = nodes_index[id];
        old_pos[id] = { x: n.x, y: n.y, z: n.z };
    });
    if (layout_anim_id !== null) { cancelAnimationFrame(layout_anim_id); layout_anim_id = null; }
    var start = performance.now(), DURATION = 600;
    function step(now) {
        var raw = Math.min((now - start) / DURATION, 1.0);
        var e = raw < 0.5 ? 2*raw*raw : -1+(4-2*raw)*raw;
        Object.keys(nodes_index).forEach(function(id) {
            var np = new_pos[id]; if (!np) return;
            var op = old_pos[id];
            var nx = op.x + (np.x - op.x) * e;
            var ny = op.y + (np.y - op.y) * e;
            var nz = op.z + ((np.z || 0) - op.z) * e;
            nodes_index[id].x = nx; nodes_index[id].y = ny; nodes_index[id].z = nz;
            nodes_index[id].mesh.position.set(nx, ny, nz);
        });
        _rebuild_edge_positions();
        layout_anim_id = raw < 1.0 ? requestAnimationFrame(step) : null;
    }
    layout_anim_id = requestAnimationFrame(step);
}

// =============================================================================
// Community coloring
// =============================================================================

function apply_strategy_colors(strategy) {
    var colorMap = community_color_maps[strategy] || {};
    Object.keys(nodes_index).forEach(function(id) {
        var node  = nodes_index[id];
        var label = node.communities && node.communities[strategy];
        var color = (label && colorMap[label])
            ? new THREE.Color(colorMap[label])
            : new THREE.Color(0.8, 0.8, 0.8);
        node.orig_color = color.clone();
        node.mesh.material.color.copy(color);
    });
    rebuild_edge_colors();
}

// =============================================================================
// Node sizing
// =============================================================================

function apply_node_size(metric) {
    current_size_key = metric;
    var vals  = Object.values(nodes_index).map(function(n) { return n[metric] || 0; });
    var minV  = Math.min.apply(null, vals);
    var range = (Math.max.apply(null, vals) - minV) || 1;
    Object.keys(nodes_index).forEach(function(id) {
        var node = nodes_index[id];
        var size = node_size_from_metric((node[metric] || 0), minV, range);
        node.size = size;
        node.mesh.scale.setScalar(size);
        var lbl = label_objects[id];
        if (lbl && labels_mode === 'on_size') lbl.visible = (size >= g_label_threshold);
    });
}

// =============================================================================
// Label visibility
// =============================================================================

function label_default_visible(id) {
    var node = nodes_index[id];
    if (labels_mode === 'always') return true;
    if (labels_mode === 'never')  return false;
    return node && node.size >= g_label_threshold;
}

function set_labels_visibility() {
    Object.keys(label_objects).forEach(function(id) {
        label_objects[id].visible = (id === hovered_node_id) || label_default_visible(id);
    });
}

// =============================================================================
// Selection / highlight
// =============================================================================

function neighbors_of(id) {
    var ns = new Set([id]);
    (adj_out[id] || new Set()).forEach(function(t) { ns.add(t); });
    (adj_in[id]  || new Set()).forEach(function(s) { ns.add(s); });
    return ns;
}

function reset_colors() {
    Object.keys(nodes_index).forEach(function(id) {
        var node = nodes_index[id];
        node.mesh.material.color.copy(node.orig_color);
    });
    rebuild_edge_colors();
    selected_node_id = null;
    el('infobar').style.display = 'none';
}

function select_node(id) {
    selected_node_id = id;
    var ns = neighbors_of(id);
    Object.keys(nodes_index).forEach(function(nid) {
        var node = nodes_index[nid];
        var neighbor = ns.has(nid);
        node.mesh.material.color.copy(neighbor ? node.orig_color : fade_color);
    });
    // Dim non-incident edges (and their arrowheads)
    _paint_edges(function(e) {
        if (!ns.has(e.source) || !ns.has(e.target)) return fade_color;
        var src = nodes_index[e.source], tgt = nodes_index[e.target];
        return avg_darken(src ? src.orig_color : fade_color, tgt ? tgt.orig_color : fade_color);
    });
    show_node_info(id);
}

function on_canvas_click(event) {
    // Skip clicks while a year/layout transition is animating; selection mutates
    // the same mesh attributes the animation is sweeping, so a click mid-frame
    // produces inconsistent visuals.
    if (animation_frame_id_3d !== null || layout_anim_id !== null) return;
    var rect = renderer.domElement.getBoundingClientRect();
    pointer.x =  ((event.clientX - rect.left) / rect.width)  * 2 - 1;
    pointer.y = -((event.clientY - rect.top)  / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    var hits = raycaster.intersectObjects(node_meshes);
    if (hits.length > 0) {
        var hit_id = hits[0].object.userData.id;
        if (hit_id === selected_node_id) reset_colors();
        else select_node(hit_id);
    } else if (selected_node_id) {
        reset_colors();
    }
}

function on_canvas_mousemove(event) {
    var rect = renderer.domElement.getBoundingClientRect();
    pointer.x =  ((event.clientX - rect.left) / rect.width)  * 2 - 1;
    pointer.y = -((event.clientY - rect.top)  / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    var hits = raycaster.intersectObjects(node_meshes);
    var new_hover = hits.length > 0 ? hits[0].object.userData.id : null;

    if (new_hover === hovered_node_id) return;

    if (hovered_node_id !== null) {
        var old_lbl = label_objects[hovered_node_id];
        if (old_lbl) old_lbl.visible = label_default_visible(hovered_node_id);
        hovered_node_id = null;
    }
    if (new_hover !== null) {
        var lbl = label_objects[new_hover];
        if (lbl) lbl.visible = true;
        hovered_node_id = new_hover;
    }
}

// =============================================================================
// Infobar
// =============================================================================

function node_anchor(id) {
    var node = nodes_index[id];
    if (!node) return '';
    var color = '#' + node.orig_color.getHexString();
    var label = (active_strategy && node.communities) ? (node.communities[active_strategy] || '') : '';
    return '<i class="bi bi-circle-fill" style="color:' + color + '" title="' + escHtml(label) + '"></i>'
         + ' <a href="#" class="node-link" data-node-id="' + escHtml(id) + '">' + escHtml(node.label || id) + '</a>';
}

function get_group_html(id) {
    var node = nodes_index[id];
    if (!node || !node.communities) return '';
    var parts = [];
    for (var strategy in node.communities) {
        var lbl      = node.communities[strategy] || '';
        var colorMap = community_color_maps[strategy] || {};
        var color    = (lbl && colorMap[lbl]) ? colorMap[lbl] : '#ccc';
        var name     = strategy.charAt(0).toUpperCase() + strategy.slice(1);
        parts.push('<i class="bi bi-circle-fill" style="color:' + color + '"></i> <b>' + escHtml(name) + ':</b> ' + escHtml(lbl));
    }
    return parts.join('<br>');
}

function show_node_info(id) {
    var node = nodes_index[id];
    if (!node) return;
    var tg_match = node.url ? /^https?:\/\/t\.me\/(.+)$/.exec(node.url) : null;
    var key = tg_match ? tg_match[1] : '';
    el('node_label').textContent           = node.label || id;
    el('node_url').textContent             = key ? '@' + key : '';
    el('node_url').href                    = (node.url && /^https?:\/\//.test(node.url)) ? node.url : '#';
    el('node_picture').innerHTML           = node.pic ? "<img src='" + escHtml(node.pic) + "' style='max-width:60px'>" : '';
    el('node_group').innerHTML             = get_group_html(id);
    el('node_followers_count').textContent = (node.fans != null) ? Number(node.fans).toLocaleString() : '—';
    el('node_messages_count').textContent  = (node.messages_count != null) ? Number(node.messages_count).toLocaleString() : '—';
    el('node_activity_period').textContent = node.activity_period || '—';
    el('node_is_lost').style.display     = node.is_lost ? '' : 'none';
    el('node_details').style.display     = '';

    var mhtml = '';
    if (accessory_data) {
        accessory_data.measures.forEach(function(m) {
            if (BASE_MEASURE_KEYS[m[0]]) return;
            var val = node[m[0]];
            mhtml += '<br><abbr>' + escHtml(m[1]) + '</abbr>: ' + (val != null ? val.toFixed(4) : 'N/A');
        });
    }
    el('node_measures').innerHTML = mhtml;

    var out_ids = Array.from(adj_out[id] || []);
    var in_ids  = Array.from(adj_in[id]  || []);
    var mut_set = new Set();
    out_ids.forEach(function(t) { if ((adj_in[id] || new Set()).has(t)) mut_set.add(t); });
    var pure_out = out_ids.filter(function(t) { return !mut_set.has(t); });
    var pure_in  = in_ids.filter(function(t)  { return !mut_set.has(t); });

    function render_list(ids) {
        return ids.sort(function(a, b) {
            return ((nodes_index[a] || {}).label || a).localeCompare((nodes_index[b] || {}).label || b);
        }).map(function(nid) { return '<li>' + node_anchor(nid) + '</li>'; }).join('');
    }
    var mut_arr = Array.from(mut_set);
    el('node_mutual_count').innerHTML = mut_arr.length;
    el('node_mutual_list').innerHTML  = render_list(mut_arr);
    el('node_in_count').innerHTML     = pure_in.length;
    el('node_in_list').innerHTML      = render_list(pure_in);
    el('node_out_count').innerHTML    = pure_out.length;
    el('node_out_list').innerHTML     = render_list(pure_out);

    el('infobar').style.display = 'block';
}

// =============================================================================
// Search
// =============================================================================

function search(word, result_el) {
    result_el.innerHTML = '';
    if (word.length <= 2) { result_el.innerHTML = '<i>Search for terms of at least 3 characters.</i>'; return; }
    var escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var pattern = new RegExp(escaped, 'i');
    var matches = Object.values(nodes_index).filter(function(n) { return pattern.test(n.label || ''); });
    matches.sort(function(a, b) { return (a.label || '').localeCompare(b.label || ''); });
    var html = ['<b>Results:</b> <ul class="list-unstyled">'];
    if (matches.length > 0) {
        matches.forEach(function(n) { html.push('<li>' + node_anchor(n.id) + '</li>'); });
        html.push('</ul><i>' + (matches.length === 1 ? '1 channel' : matches.length + ' channels') + '</i>');
    } else {
        html.push('<li><i>No results.</i></li></ul>');
    }
    result_el.innerHTML = html.join('');
}

// =============================================================================
// Camera helpers
// =============================================================================

function zoom_by(factor) {
    camera.position.lerp(controls.target, 1 - factor);
    controls.update();
}

function reset_camera() {
    if (node_meshes.length === 0) return;
    var box = new THREE.Box3();
    node_meshes.forEach(function(m) { box.expandByObject(m); });
    var center = new THREE.Vector3();
    var size   = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);
    var maxDim = Math.max(size.x, size.y, size.z);
    var dist   = maxDim / (2 * Math.tan(camera.fov * Math.PI / 360)) * 1.5;
    camera.position.set(center.x, center.y, center.z + dist);
    controls.target.copy(center);
    controls.update();
}

// =============================================================================
// UI builders
// =============================================================================


function build_strategy_selector(communities) {
    var strategies = Object.keys(communities);
    if (strategies.length <= 1) { el('community-strategy-group').style.display = 'none'; return; }
    el('community-strategy-select').innerHTML = strategies.map(function(s) {
        return '<option value="' + s + '">' + strategy_label(s) + '</option>';
    }).join('');
    el('community-strategy-group').style.display = '';
}

function build_legend(strategyData) {
    var legend_items = [], group_items = ['<option value="" selected>All nodes</option>'];
    strategyData.groups.forEach(function(g) {
        var label = escHtml(g[2]);
        var color = escHtml(g[3]);
        legend_items.push('<li style="padding-bottom:.75em"><i class="bi bi-circle-fill" style="color:' + color + '"></i> ' + label + ', ' + g[1] + ' channels</li>');
        group_items.push('<option value="' + label + '">' + label + '</option>');
    });
    el('legend').innerHTML       = legend_items.join('');
    el('group-select').innerHTML = group_items.join('');
}

// =============================================================================
// Group filter
// =============================================================================

function apply_group_filter(group) {
    current_group = group;
    if (!group) {
        Object.keys(nodes_index).forEach(function(id) {
            var node = nodes_index[id];
            node.mesh.material.color.copy(node.orig_color);
        });
        rebuild_edge_colors();
        return;
    }
    Object.keys(nodes_index).forEach(function(id) {
        var node  = nodes_index[id];
        var label = (node.communities && active_strategy) ? node.communities[active_strategy] : '';
        var match = (label === group);
        node.mesh.material.color.copy(match ? node.orig_color : fade_color);
    });
    rebuild_edge_colors();
}

// =============================================================================
// Data loading
// =============================================================================

function get_data() {
    return Promise.all([
        fetchJson(current_data_dir + 'channel_position_3d.json'),
        fetchJson(current_data_dir + 'channels.json'),
        fetchJson(current_data_dir + 'communities.json'),
    ]).then(function(results) {
        var pos_data  = results[0];
        var ch_data   = results[1];
        var comm_data = results[2];

        accessory_data          = ch_data;
        community_strategy_data = comm_data.strategies;
        community_color_maps    = buildCommunityColorMaps(comm_data.strategies);

        var strategies  = Object.keys(comm_data.strategies);
        active_strategy = strategies[0] || null;

        build_strategy_selector(comm_data.strategies);
        if (active_strategy) build_legend(comm_data.strategies[active_strategy]);

        el('size-select').innerHTML = ch_data.measures.map(function(m) {
            return '<option value="' + m[0] + '">' + m[1] + '</option>';
        }).join('');

        el('loading_message').innerHTML = 'Building 3D graph…';
        build_graph(pos_data, ch_data);
        if (active_strategy) apply_strategy_colors(active_strategy);

        el('about_graph_stats').innerHTML =
            node_meshes.length + ' channels, ' + edge_list.length + ' connections';
        reset_camera();
        update_info_bar();
    }).catch(function(err) {
        el('loading_message').innerHTML = 'Error: ' + err.message;
        console.error(err);
    });
}

// =============================================================================
// Year switching
// =============================================================================

function preload_year_3d(data_dir) {
    if (year_cache[data_dir] || year_cache_pend[data_dir]) return Promise.resolve();
    year_cache_pend[data_dir] = true;
    return Promise.all([
        fetchJson(data_dir + 'channel_position_3d.json'),
        fetchJson(data_dir + 'channels.json'),
        fetchJson(data_dir + 'communities.json'),
    ]).then(function(results) {
        delete year_cache_pend[data_dir];
        year_cache[data_dir] = { pos: results[0], ch: results[1], comm: results[2] };
    }).catch(function(err) { delete year_cache_pend[data_dir]; console.warn('preload_year_3d failed for', data_dir, err); });
}

function _apply_accessory_3d(ch_data, comm_data) {
    var prev_strategy = active_strategy;
    var prev_size     = el('size-select') ? el('size-select').value : current_size_key;

    accessory_data          = ch_data;
    community_strategy_data = comm_data.strategies;
    community_color_maps    = buildCommunityColorMaps(comm_data.strategies);

    var strategies  = Object.keys(comm_data.strategies);
    active_strategy = (prev_strategy && strategies.indexOf(prev_strategy) !== -1)
        ? prev_strategy : (strategies[0] || null);

    build_strategy_selector(comm_data.strategies);
    if (active_strategy) {
        var sel = el('community-strategy-select');
        if (sel) sel.value = active_strategy;
        build_legend(comm_data.strategies[active_strategy]);
    }

    el('size-select').innerHTML = ch_data.measures.map(function(m) {
        return '<option value="' + m[0] + '">' + m[1] + '</option>';
    }).join('');
    var found = false;
    if (prev_size) {
        var opts = el('size-select').options;
        for (var i = 0; i < opts.length; i++) {
            if (opts[i].value === prev_size) {
                el('size-select').value = prev_size;
                current_size_key = prev_size;
                found = true;
                break;
            }
        }
    }
    if (!found && el('size-select').options.length > 0) current_size_key = el('size-select').value;

    // Group filter is per-year; reset so a stale label from the previous year
    // does not silently fade every node.
    var group_sel = el('group-select');
    if (group_sel) group_sel.value = '';
    current_group = '';

    update_info_bar();
}

function animate_year_transition_3d(new_pos_data, new_ch_data, duration_ms) {
    if (animation_frame_id_3d !== null) {
        cancelAnimationFrame(animation_frame_id_3d);
        animation_frame_id_3d = null;
        controls.enabled = true;  // restore if previous animation was interrupted
    }

    if (edge_segments) edge_segments.visible = false;
    if (arrow_mesh) arrow_mesh.visible = false;

    var new_pos_map = {}, new_ch_map = {};
    new_pos_data.nodes.forEach(function(n) { new_pos_map[n.id] = n; });
    new_ch_data.nodes.forEach(function(n) { new_ch_map[n.id] = n; });

    var old_ids  = Object.keys(nodes_index);
    var old_only = old_ids.filter(function(id) { return !new_pos_map[id]; });
    var both     = old_ids.filter(function(id) { return !!new_pos_map[id]; });
    var new_only = new_pos_data.nodes.map(function(n) { return n.id; })
                      .filter(function(id) { return !nodes_index[id]; });

    var cx = 0, cy = 0, cz = 0;
    if (old_ids.length) {
        old_ids.forEach(function(id) { var n = nodes_index[id]; cx += n.x; cy += n.y; cz += (n.z || 0); });
        cx /= old_ids.length; cy /= old_ids.length; cz /= old_ids.length;
    }

    if (selected_node_id && old_only.indexOf(selected_node_id) >= 0) {
        selected_node_id = null;
        el('infobar').style.display      = 'none';
        el('node_details').style.display = 'none';
    }
    // Hover label survived: clear it so the next mousemove starts from a
    // clean state instead of a now-deleted node id.
    if (hovered_node_id && old_only.indexOf(hovered_node_id) >= 0) {
        hovered_node_id = null;
    }

    // Remove departing nodes immediately (edges hidden).
    // Also explicitly remove the CSS2DObject DOM element — scene.remove(mesh)
    // alone is not guaranteed to purge it from the label_renderer container
    // before the next render, leaving ghost labels visible for one or more frames.
    old_only.forEach(function(id) {
        var node = nodes_index[id];
        if (!node) return;
        var lbl = label_objects[id];
        if (lbl) {
            node.mesh.remove(lbl);
            if (lbl.element && lbl.element.parentNode) lbl.element.parentNode.removeChild(lbl.element);
        }
        scene.remove(node.mesh);
        node.mesh.material.dispose();
        var mi = node_meshes.indexOf(node.mesh);
        if (mi >= 0) node_meshes.splice(mi, 1);
        delete label_objects[id];
        delete nodes_index[id];
        delete adj_out[id];
        delete adj_in[id];
    });

    var snap = {};
    both.forEach(function(id) {
        var n = nodes_index[id];
        snap[id] = { x: n.x, y: n.y, z: n.z || 0, size: n.size };
    });

    // New size bounds
    var bx0 = Infinity, bx1 = -Infinity, by0 = Infinity, by1 = -Infinity, bz0 = Infinity, bz1 = -Infinity;
    new_pos_data.nodes.forEach(function(p) {
        if (p.x < bx0) bx0 = p.x; if (p.x > bx1) bx1 = p.x;
        if (p.y < by0) by0 = p.y; if (p.y > by1) by1 = p.y;
        var pz = p.z || 0;
        if (pz < bz0) bz0 = pz; if (pz > bz1) bz1 = pz;
    });
    if (!isFinite(bx0)) { bx0 = 0; bx1 = 1; by0 = 0; by1 = 1; bz0 = 0; bz1 = 1; }
    var new_diam     = Math.sqrt(Math.pow(bx1-bx0,2)+Math.pow(by1-by0,2)+Math.pow(bz1-bz0,2)) || 1;
    var new_size_min = new_diam * SIZE_MIN_FRAC;
    var new_size_max = new_diam * SIZE_MAX_FRAC;

    var sv = new_pos_data.nodes.map(function(n) { return (new_ch_map[n.id] || {})[current_size_key] || 0; });
    var sv_min = sv.length ? Math.min.apply(null, sv) : 0;
    var sv_rng = ((sv.length ? Math.max.apply(null, sv) : 0) - sv_min) || 1;
    var target_sizes = {};
    new_pos_data.nodes.forEach(function(n) {
        var v = (new_ch_map[n.id] || {})[current_size_key] || 0;
        target_sizes[n.id] = new_size_min + ((v - sv_min) / sv_rng) * (new_size_max - new_size_min);
    });

    new_only.forEach(function(id) {
        var m     = new_ch_map[id] || {};
        var color = m.color ? parse_color(m.color) : new THREE.Color(0.5, 0.5, 0.5);
        var mesh  = new THREE.Mesh(sphere_geom, new THREE.MeshLambertMaterial({ color: color.clone() }));
        mesh.position.set(cx, cy, cz);
        mesh.scale.setScalar(0);
        mesh.userData.id = id;
        nodes_index[id] = Object.assign({}, m, { x: cx, y: cy, z: cz, size: 0, orig_color: color.clone(), mesh: mesh });
        scene.add(mesh);
        node_meshes.push(mesh);
        var div = document.createElement('div');
        div.className = 'node-label';
        div.textContent = m.label || id;
        var lbl = new CSS2DObject(div);
        lbl.position.set(0, 1.3, 0);
        lbl.visible = false;
        mesh.add(lbl);
        label_objects[id] = lbl;
        adj_out[id] = new Set();
        adj_in[id]  = new Set();
    });

    // Pre-compute target camera from the new year's bounding box so we can
    // animate the camera smoothly instead of letting OrbitControls hold still
    // while nodes cluster and then snapping with reset_camera() at the end.
    var new_box = new THREE.Box3();
    new_pos_data.nodes.forEach(function(p) {
        new_box.expandByPoint(new THREE.Vector3(p.x, p.y, p.z || 0));
    });
    var new_center = new THREE.Vector3(), new_size_v = new THREE.Vector3();
    new_box.getCenter(new_center);
    new_box.getSize(new_size_v);
    var new_max_dim    = Math.max(new_size_v.x, new_size_v.y, new_size_v.z) || 1;
    var new_cam_dist   = new_max_dim / (2 * Math.tan(camera.fov * Math.PI / 360)) * 1.5;
    var target_cam_pos = new THREE.Vector3(new_center.x, new_center.y, new_center.z + new_cam_dist);
    var target_cam_tgt = new_center.clone();

    var start_cam_pos = camera.position.clone();
    var start_cam_tgt = controls.target.clone();
    controls.enabled  = false;

    function _lerp(a, b, t) { return a + (b - a) * t; }
    function _ease(t) { return t < 0.5 ? 2*t*t : -1 + (4 - 2*t)*t; }
    var start_ts = null;

    function step(ts) {
        if (!start_ts) start_ts = ts;
        var raw = Math.min((ts - start_ts) / duration_ms, 1);
        var e   = _ease(raw);

        both.forEach(function(id) {
            var s = snap[id], np = new_pos_map[id], sz = target_sizes[id] !== undefined ? target_sizes[id] : s.size;
            var node = nodes_index[id];
            if (!node) return;
            var nx = _lerp(s.x, np.x, e), ny = _lerp(s.y, np.y, e), nz = _lerp(s.z, np.z || 0, e);
            node.mesh.position.set(nx, ny, nz);
            node.mesh.scale.setScalar(_lerp(s.size, sz, e));
            node.x = nx; node.y = ny; node.z = nz;
        });

        new_only.forEach(function(id) {
            var np = new_pos_map[id], sz = target_sizes[id] || 0;
            var node = nodes_index[id];
            if (!node) return;
            var nx = _lerp(cx, np.x, e), ny = _lerp(cy, np.y, e), nz = _lerp(cz, np.z || 0, e);
            node.mesh.position.set(nx, ny, nz);
            node.mesh.scale.setScalar(sz * e);
            node.x = nx; node.y = ny; node.z = nz;
        });

        camera.position.lerpVectors(start_cam_pos, target_cam_pos, e);
        controls.target.lerpVectors(start_cam_tgt, target_cam_tgt, e);
        controls.update();

        if (raw < 1) {
            animation_frame_id_3d = requestAnimationFrame(step);
        } else {
            animation_frame_id_3d = null;
            _finalize_year_3d(new_pos_data, new_ch_map, target_sizes, new_size_min, new_size_max,
                              target_cam_pos, target_cam_tgt);
        }
    }
    animation_frame_id_3d = requestAnimationFrame(step);
}

function _finalize_year_3d(new_pos_data, new_ch_map, target_sizes, new_size_min, new_size_max,
                            target_cam_pos, target_cam_tgt) {
    var SKIP = { x:1, y:1, z:1, size:1, mesh:1, orig_color:1 };
    new_pos_data.nodes.forEach(function(np) {
        var node = nodes_index[np.id];
        if (!node) return;
        var sz = target_sizes[np.id] !== undefined ? target_sizes[np.id] : node.size;
        node.mesh.position.set(np.x, np.y, np.z || 0);
        node.mesh.scale.setScalar(sz);
        node.x = np.x; node.y = np.y; node.z = np.z || 0; node.size = sz;
        var m = new_ch_map[np.id];
        if (m) {
            Object.keys(m).forEach(function(k) { if (!SKIP[k]) node[k] = m[k]; });
            var lbl = label_objects[np.id];
            if (lbl && lbl.element) lbl.element.textContent = m.label || np.id;
        }
    });

    g_size_min        = new_size_min;
    g_size_max        = new_size_max;
    g_label_threshold = g_size_min + LABEL_SIZE_FRAC * (g_size_max - g_size_min);

    if (edge_segments) {
        scene.remove(edge_segments);
        edge_segments.geometry.dispose();
        edge_segments.material.dispose();
        edge_segments = null;
    }
    edge_list = [];
    Object.keys(nodes_index).forEach(function(id) { adj_out[id] = new Set(); adj_in[id] = new Set(); });

    var VERTS_PER_EDGE = CURVE_SEGMENTS * 2;
    var positions = new Float32Array(new_pos_data.edges.length * VERTS_PER_EDGE * 3);
    var colors    = new Float32Array(new_pos_data.edges.length * VERTS_PER_EDGE * 3);
    var vc = 0;
    new_pos_data.edges.forEach(function(e) {
        var src = nodes_index[e.source], tgt = nodes_index[e.target];
        if (!src || !tgt) return;
        var sp  = new THREE.Vector3(src.x, src.y, src.z || 0);
        var tp  = new THREE.Vector3(tgt.x, tgt.y, tgt.z || 0);
        var pts = new THREE.QuadraticBezierCurve3(sp, _control_point(sp, tp, _edge_curves()), tp).getPoints(CURVE_SEGMENTS);
        var c   = avg_darken(src.orig_color, tgt.orig_color);
        var vs  = vc;
        for (var i = 0; i < CURVE_SEGMENTS; i++) {
            var p0 = pts[i], p1 = pts[i+1];
            positions[vc*3]=p0.x; positions[vc*3+1]=p0.y; positions[vc*3+2]=p0.z;
            colors[vc*3]=c.r;    colors[vc*3+1]=c.g;    colors[vc*3+2]=c.b; vc++;
            positions[vc*3]=p1.x; positions[vc*3+1]=p1.y; positions[vc*3+2]=p1.z;
            colors[vc*3]=c.r;    colors[vc*3+1]=c.g;    colors[vc*3+2]=c.b; vc++;
        }
        edge_list.push({ source: e.source, target: e.target, vert_start: vs, weight: e.weight });
        adj_out[e.source].add(e.target);
        adj_in[e.target].add(e.source);
    });
    var used = vc * 3;
    edge_segments = _build_edge_object(positions.subarray(0, used), colors.subarray(0, used), vc / 2, edge_opacity_3d);
    scene.add(edge_segments);
    apply_edge_widths_3d();
    _build_arrow_mesh();

    active_layout = 'fa2';
    if (el('layout-select')) el('layout-select').value = 'fa2';

    if (active_strategy) apply_strategy_colors(active_strategy);
    apply_node_size(current_size_key);
    set_labels_visibility();
    el('about_graph_stats').innerHTML = node_meshes.length + ' channels, ' + edge_list.length + ' connections';

    // Snap camera to the pre-computed target and restore user controls.
    camera.position.copy(target_cam_pos);
    controls.target.copy(target_cam_tgt);
    controls.update();
    controls.enabled = true;
}

function reload_graph_3d(data_dir) {
    if (animation_frame_id_3d !== null) { cancelAnimationFrame(animation_frame_id_3d); animation_frame_id_3d = null; }
    current_data_dir = data_dir;
    el('infobar').style.display      = 'none';
    el('node_details').style.display = 'none';
    selected_node_id = null;

    var c = year_cache[data_dir];
    if (c) {
        _apply_accessory_3d(c.ch, c.comm);
        animate_year_transition_3d(c.pos, c.ch, 700);
    } else {
        Promise.all([
            fetchJson(data_dir + 'channel_position_3d.json'),
            fetchJson(data_dir + 'channels.json'),
            fetchJson(data_dir + 'communities.json'),
        ]).then(function(results) {
            _apply_accessory_3d(results[1], results[2]);
            animate_year_transition_3d(results[0], results[1], 700);
        }).catch(function(err) {
            controls.enabled = true;
            console.error('reload_graph_3d fetch failed for', data_dir, err);
        });
    }
}

function update_year_buttons_active(year_str) {
    active_year = String(year_str);
    var container = el('year-switcher');
    if (!container) return;
    var all_btn = container.querySelector('.year-btn--all');
    if (all_btn) all_btn.classList.toggle('active', active_year === 'all');
    var lbl = el('year-drop-label');
    if (lbl) lbl.textContent = (active_year === 'all') ? '—' : active_year;
    container.querySelectorAll('.year-drop-item').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.year === active_year);
    });
    var idx  = year_sequence.indexOf(active_year);
    var prev = el('year-prev');
    var next = el('year-next');
    if (prev) prev.disabled = (idx <= 0);
    if (next) next.disabled = (idx < 0 || idx >= year_sequence.length - 1);
}

function _go_year_3d(year) {
    if (year === active_year) return;
    update_year_buttons_active(year);
    reload_graph_3d(year === 'all' ? 'data/' : 'data_' + year + '/');
}

function _year_drop_close() {
    var menu = el('year-drop-menu');
    var btn  = el('year-drop-btn');
    if (menu) menu.classList.remove('open');
    if (btn)  btn.setAttribute('aria-expanded', 'false');
}

function init_year_switcher(timeline) {
    var years_with_graph = (timeline.years || []).filter(function(y) { return y.has_graph; });
    if (!years_with_graph.length) return;
    var container = el('year-switcher');
    if (!container) return;

    year_sequence = ['all'].concat(years_with_graph.map(function(y) { return String(y.year); }));

    if (!_year_switcher_inited) {
        _year_switcher_inited = true;

        var drop_items = years_with_graph.map(function(entry) {
            return '<button class="year-btn year-drop-item" data-year="' + entry.year + '">' + entry.year + '</button>';
        }).join('');

        container.innerHTML = [
            '<button class="year-btn year-btn--nav" id="year-prev" aria-label="Previous year" disabled>',
            '<i class="bi bi-chevron-left" aria-hidden="true"></i></button>',
            '<button class="year-btn year-btn--all" data-year="all">All</button>',
            '<span class="year-sep" aria-hidden="true"></span>',
            '<div class="year-drop-wrap">',
            '<button class="year-btn year-drop-toggle" id="year-drop-btn" aria-haspopup="listbox" aria-expanded="false">',
            '<span id="year-drop-label">—</span>',
            '<i class="bi bi-chevron-up year-chevron" aria-hidden="true"></i></button>',
            '<div class="year-drop-menu" id="year-drop-menu" role="listbox">' + drop_items + '</div>',
            '</div>',
            '<button class="year-btn year-btn--nav" id="year-next" aria-label="Next year">',
            '<i class="bi bi-chevron-right" aria-hidden="true"></i></button>',
        ].join('');

        container.style.display = 'flex';

        container.querySelector('.year-btn--all').addEventListener('click', function() {
            _go_year_3d('all'); _year_drop_close();
        });
        el('year-prev').addEventListener('click', function() {
            var idx = year_sequence.indexOf(active_year);
            if (idx > 0) { _go_year_3d(year_sequence[idx - 1]); _year_drop_close(); }
        });
        el('year-next').addEventListener('click', function() {
            var idx = year_sequence.indexOf(active_year);
            if (idx >= 0 && idx < year_sequence.length - 1) { _go_year_3d(year_sequence[idx + 1]); _year_drop_close(); }
        });
        el('year-drop-btn').addEventListener('click', function(e) {
            e.stopPropagation();
            var menu = el('year-drop-menu');
            var open = menu.classList.toggle('open');
            this.setAttribute('aria-expanded', String(open));
        });
        el('year-drop-menu').addEventListener('click', function(e) {
            e.stopPropagation();
            var btn = e.target.closest('.year-drop-item');
            if (!btn) return;
            _go_year_3d(btn.dataset.year);
        });
        document.addEventListener('click', function() { _year_drop_close(); });
    }

    var init_year = 'all';
    if (window.DATA_DIR) {
        var m = window.DATA_DIR.match(/data_(\d+)\//);
        if (m) init_year = m[1];
    }
    update_year_buttons_active(init_year);
}

// =============================================================================
// DOMContentLoaded
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    if (!window.VERTICAL_LAYOUT) el('menu_container').classList.add('menu--lateral');

    init_three();

    // The graph always boots dark, independent of the shared pulpit_theme key:
    // theme here is a display layout the user flips at will, not a remembered
    // preference. The live webapp and table exports keep their own
    // pulpit_theme-backed light/dark setting.
    el('theme-select').value = 'dark';
    apply_theme_3d('dark');

    build_layout_selector();

    var loading_el       = el('loading_modal');
    var loading_modal_bs = new bootstrap.Modal(loading_el, { backdrop: 'static', keyboard: false });

    var graph_promise = new Promise(function(resolve) {
        loading_el.addEventListener('shown.bs.modal', function() {
            get_data().then(resolve);
        }, { once: true });
    });

    loading_modal_bs.show();
    el('loading_message').innerHTML = 'Loading…<br>Please wait.';

    var years_promise = fetchJsonOrNull('data/timeline.json')
        .then(function(timeline) {
            if (!timeline) return;
            init_year_switcher(timeline);
            var years = (timeline.years || []).filter(function(y) { return y.has_graph; });
            var dirs  = ['data/'].concat(years.map(function(y) { return 'data_' + y.year + '/'; }));
            var total = dirs.length, done = 0;
            return Promise.all(dirs.map(function(dir) {
                return preload_year_3d(dir).then(function() {
                    done++;
                    var m = dir.match(/data_(\d+)\//);
                    el('loading_message').innerHTML =
                        (m ? m[1] : 'All') + ' (' + done + ' / ' + total + ')';
                });
            }));
        });

    Promise.all([graph_promise, years_promise])
        .then(function() { loading_modal_bs.hide(); });

    el('layout-select').addEventListener('change', function() {
        switch_layout_3d(this.value);
        update_info_bar();
    });

    el('theme-select').addEventListener('change', function() {
        apply_theme_3d(this.value);
        update_info_bar();
    });

    el('colored-edges-toggle').addEventListener('change', function() {
        colored_edges = this.checked;
        rebuild_edge_colors();
        update_info_bar();
    });

    el('edge-weight-toggle').addEventListener('change', function() {
        show_edge_weight = this.checked;
        apply_edge_widths_3d();
        update_info_bar();
    });

    el('edge-arrows-toggle').addEventListener('change', function() {
        show_edge_arrows = this.checked;
        if (arrow_mesh) arrow_mesh.visible = show_edge_arrows;
        update_info_bar();
    });

    el('edge-opacity-slider').addEventListener('input', function() {
        edge_opacity_3d = parseFloat(this.value);
        if (edge_segments) edge_segments.material.opacity = edge_opacity_3d;
    });

    el('community-strategy-select').addEventListener('change', function() {
        active_strategy = this.value;
        if (community_strategy_data) build_legend(community_strategy_data[active_strategy]);
        apply_strategy_colors(active_strategy);
        el('group-select').value = '';
        current_group = '';
        update_info_bar();
    });

    el('size-select').addEventListener('change', function() {
        apply_node_size(this.value);
        update_info_bar();
    });

    el('labels-select').addEventListener('change', function() {
        labels_mode = this.value;
        set_labels_visibility();
        update_info_bar();
    });

    el('group-select').addEventListener('change', function() {
        apply_group_filter(this.value);
        update_info_bar();
    });

    el('search_input').value = '';
    el('search_modal').addEventListener('shown.bs.modal', function() { el('search_input').focus(); });
    el('search_modal').addEventListener('hide.bs.modal', function() {
        var r = el('results'); r.innerHTML = ''; r.style.display = 'none';
    });
    el('search').addEventListener('submit', function(e) {
        e.preventDefault();
        search(el('search_input').value, el('results'));
    });

    document.addEventListener('click', function(e) {
        var link = e.target.closest('a.node-link');
        if (!link) return;
        e.preventDefault();
        var id = link.dataset.nodeId;
        var sm = bootstrap.Modal.getInstance(el('search_modal'));
        if (sm) sm.hide();
        select_node(id);
        var node = nodes_index[id];
        if (node) { controls.target.set(node.x, node.y, node.z); controls.update(); }
    });

    document.querySelectorAll('.infobar-toggle').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var infobar = el('infobar');
            infobar.style.display = infobar.style.display === 'none' ? 'block' : 'none';
            if (selected_node_id) reset_colors();
        });
    });

    el('zoom_in').addEventListener('click',    function() { zoom_by(ZOOM_STEP); });
    el('zoom_out').addEventListener('click',   function() { zoom_by(1 / ZOOM_STEP); });
    el('zoom_reset').addEventListener('click', function() { reset_camera(); });
});
