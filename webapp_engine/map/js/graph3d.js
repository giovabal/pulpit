import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { strategy_label } from './labels.js';
import { escHtml } from './utils.js';

// =============================================================================
// Constants
// =============================================================================

var BG_COLOR           = 0x112233;
var FADE_COLOR_HEX     = 0x1b2c3d;
var EDGE_OPACITY       = 0.30;
var EDGE_DARKEN        = 0.75;   // factor applied to averaged endpoint color
var CURVE_SEGMENTS     = 10;     // line segments per curved edge
var CURVATURE          = 0.15;   // control-point offset as fraction of edge length
var SELF_LOOP_ARM      = 1.0;    // self-loop arm spread as multiple of node radius
var SELF_LOOP_HEIGHT   = 3.5;    // self-loop arc peak as multiple of node radius
var ZOOM_STEP          = 0.75;
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
var edge_list        = [];   // [{source, target, vert_offset}] for color rebuilds
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
var fade_color  = new THREE.Color(FADE_COLOR_HEX);

// =============================================================================
// Helpers
// =============================================================================

function el(id) { return document.getElementById(id); }


function parse_color(css_rgb) {
    var parts = css_rgb.split(',').map(function(s) { return parseInt(s.trim(), 10); });
    return new THREE.Color(parts[0] / 255, parts[1] / 255, parts[2] / 255);
}

function avg_darken(c1, c2) {
    return new THREE.Color(
        (c1.r + c2.r) / 2 * EDGE_DARKEN,
        (c1.g + c2.g) / 2 * EDGE_DARKEN,
        (c1.b + c2.b) / 2 * EDGE_DARKEN
    );
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
            cp = curve_control(sp, tp);
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

        edge_list.push({ source: e.source, target: e.target, vert_start: vert_start });

        if (adj_out[e.source]) adj_out[e.source].add(e.target);
        if (adj_in[e.target])  adj_in[e.target].add(e.source);
    });

    // Trim to actual used size (some edges may have been skipped)
    var used = vert_cursor * 3;
    var geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions.subarray(0, used), 3));
    geom.setAttribute('color',    new THREE.BufferAttribute(colors.subarray(0, used), 3));
    var mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: EDGE_OPACITY });
    edge_segments = new THREE.LineSegments(geom, mat);
    scene.add(edge_segments);
}

// =============================================================================
// Edge color rebuild (called after node color changes)
// =============================================================================

function rebuild_edge_colors() {
    if (!edge_segments || !edge_list.length) return;
    var arr = edge_segments.geometry.getAttribute('color').array;
    edge_list.forEach(function(e) {
        var src = nodes_index[e.source];
        var tgt = nodes_index[e.target];
        if (!src || !tgt) return;
        var c = avg_darken(src.orig_color, tgt.orig_color);
        var base = e.vert_start * 3;
        for (var i = 0; i < CURVE_SEGMENTS * 2; i++) {
            arr[base + i * 3]     = c.r;
            arr[base + i * 3 + 1] = c.g;
            arr[base + i * 3 + 2] = c.b;
        }
    });
    edge_segments.geometry.getAttribute('color').needsUpdate = true;
}

// =============================================================================
// Community coloring
// =============================================================================

function build_community_color_maps(communities) {
    var maps = {};
    for (var strategy in communities) {
        maps[strategy] = {};
        communities[strategy].groups.forEach(function(g) {
            maps[strategy][g[2]] = g[3];  // label → hexColor
        });
    }
    return maps;
}

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
    // Dim non-incident edges
    if (edge_segments) {
        var arr = edge_segments.geometry.getAttribute('color').array;
        edge_list.forEach(function(e) {
            var incident = ns.has(e.source) && ns.has(e.target);
            var src = nodes_index[e.source], tgt = nodes_index[e.target];
            var c = incident
                ? avg_darken(src ? src.orig_color : fade_color, tgt ? tgt.orig_color : fade_color)
                : fade_color;
            var base = e.vert_start * 3;
            for (var i = 0; i < CURVE_SEGMENTS * 2; i++) {
                arr[base + i * 3]     = c.r;
                arr[base + i * 3 + 1] = c.g;
                arr[base + i * 3 + 2] = c.b;
            }
        });
        edge_segments.geometry.getAttribute('color').needsUpdate = true;
    }
    show_node_info(id);
}

function on_canvas_click(event) {
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
         + ' <a href="#" class="node-link" data="' + escHtml(id) + '">' + escHtml(node.label || id) + '</a>';
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
    var key = node.url ? node.url.replace('https://t.me/', '') : '';
    el('node_label').textContent           = node.label || id;
    el('node_url').textContent             = '@' + key;
    el('node_url').href                    = (node.url && /^https?:\/\//.test(node.url)) ? node.url : '#';
    el('node_picture').innerHTML           = node.pic ? "<img src='" + escHtml(node.pic) + "' style='max-width:60px'>" : '';
    el('node_group').innerHTML             = get_group_html(id);
    el('node_followers_count').textContent = node.fans || '';
    el('node_messages_count').textContent  = node.messages_count || '';
    el('node_activity_period').textContent = node.activity_period || '';
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
    var pattern = new RegExp(word, 'i');
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
    var dist = camera.position.distanceTo(controls.target);
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
        legend_items.push('<li style="padding-bottom:.75em"><i class="bi bi-circle-fill" style="color:' + g[3] + '"></i> ' + g[2] + ', ' + g[1] + ' channels</li>');
        group_items.push('<option value="' + g[2] + '">' + g[2] + '</option>');
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
        fetch(current_data_dir + 'channel_position_3d.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(current_data_dir + 'channels.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(current_data_dir + 'communities.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
    ]).then(function(results) {
        var pos_data  = results[0];
        var ch_data   = results[1];
        var comm_data = results[2];

        accessory_data          = ch_data;
        community_strategy_data = comm_data.strategies;
        community_color_maps    = build_community_color_maps(comm_data.strategies);

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
        fetch(data_dir + 'channel_position_3d.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(data_dir + 'channels.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
        fetch(data_dir + 'communities.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
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
    community_color_maps    = build_community_color_maps(comm_data.strategies);

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
}

function animate_year_transition_3d(new_pos_data, new_ch_data, duration_ms) {
    if (animation_frame_id_3d !== null) {
        cancelAnimationFrame(animation_frame_id_3d);
        animation_frame_id_3d = null;
        controls.enabled = true;  // restore if previous animation was interrupted
    }

    if (edge_segments) edge_segments.visible = false;

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
    new_pos_data.nodes.forEach(function(np) {
        var node = nodes_index[np.id];
        if (!node) return;
        var sz = target_sizes[np.id] !== undefined ? target_sizes[np.id] : node.size;
        node.mesh.position.set(np.x, np.y, np.z || 0);
        node.mesh.scale.setScalar(sz);
        node.x = np.x; node.y = np.y; node.z = np.z || 0; node.size = sz;
        var m = new_ch_map[np.id];
        if (m) {
            var SKIP = { x:1, y:1, z:1, size:1, mesh:1, orig_color:1 };
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
        var pts = new THREE.QuadraticBezierCurve3(sp, curve_control(sp, tp), tp).getPoints(CURVE_SEGMENTS);
        var c   = avg_darken(src.orig_color, tgt.orig_color);
        var vs  = vc;
        for (var i = 0; i < CURVE_SEGMENTS; i++) {
            var p0 = pts[i], p1 = pts[i+1];
            positions[vc*3]=p0.x; positions[vc*3+1]=p0.y; positions[vc*3+2]=p0.z;
            colors[vc*3]=c.r;    colors[vc*3+1]=c.g;    colors[vc*3+2]=c.b; vc++;
            positions[vc*3]=p1.x; positions[vc*3+1]=p1.y; positions[vc*3+2]=p1.z;
            colors[vc*3]=c.r;    colors[vc*3+1]=c.g;    colors[vc*3+2]=c.b; vc++;
        }
        edge_list.push({ source: e.source, target: e.target, vert_start: vs });
        adj_out[e.source].add(e.target);
        adj_in[e.target].add(e.source);
    });
    var used = vc * 3;
    var geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions.subarray(0, used), 3));
    geom.setAttribute('color',    new THREE.BufferAttribute(colors.subarray(0, used), 3));
    edge_segments = new THREE.LineSegments(geom, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: EDGE_OPACITY }));
    scene.add(edge_segments);

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
            fetch(data_dir + 'channel_position_3d.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
            fetch(data_dir + 'channels.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
            fetch(data_dir + 'communities.json').then(function(r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); }),
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

    var loading_el       = el('loading_modal');
    var loading_modal_bs = new bootstrap.Modal(loading_el, { backdrop: 'static', keyboard: false });

    var graph_promise = new Promise(function(resolve) {
        loading_el.addEventListener('shown.bs.modal', function() {
            get_data().then(resolve);
        }, { once: true });
    });

    loading_modal_bs.show();
    el('loading_message').innerHTML = 'Loading…<br>Please wait.';

    var years_promise = fetch('data/timeline.json')
        .then(function(r) { return r.ok ? r.json() : null; })
        .catch(function() { return null; })
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

    el('community-strategy-select').addEventListener('change', function() {
        active_strategy = this.value;
        if (community_strategy_data) build_legend(community_strategy_data[active_strategy]);
        apply_strategy_colors(active_strategy);
        el('group-select').value = '';
        current_group = '';
    });

    el('size-select').addEventListener('change', function() { apply_node_size(this.value); });

    el('labels-select').addEventListener('change', function() {
        labels_mode = this.value;
        set_labels_visibility();
    });

    el('group-select').addEventListener('change', function() { apply_group_filter(this.value); });

    el('search_input').value = '';
    el('search_modal').addEventListener('shown.bs.modal', function() { el('search_input').focus(); });
    el('search').addEventListener('submit', function(e) {
        e.preventDefault();
        search(el('search_input').value, el('results'));
    });

    document.addEventListener('click', function(e) {
        var link = e.target.closest('a.node-link');
        if (!link) return;
        e.preventDefault();
        var id = link.getAttribute('data');
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
