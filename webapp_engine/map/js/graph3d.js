import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// =============================================================================
// Constants
// =============================================================================

var BG_COLOR           = 0x112233;
var FADE_COLOR_HEX     = 0x1b2c3d;
var EDGE_OPACITY       = 0.30;
var EDGE_DARKEN        = 0.75;   // factor applied to averaged endpoint color
var CURVE_SEGMENTS     = 10;     // line segments per curved edge
var CURVATURE          = 0.15;   // control-point offset as fraction of edge length
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

        var sp = new THREE.Vector3(src.x, src.y, src.z);
        var tp = new THREE.Vector3(tgt.x, tgt.y, tgt.z);
        var cp = curve_control(sp, tp);
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
    return '<i class="bi bi-circle-fill" style="color:' + color + '" title="' + label + '"></i>'
         + ' <a href="#" class="node-link" data="' + id + '">' + (node.label || id) + '</a>';
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
        parts.push('<i class="bi bi-circle-fill" style="color:' + color + '"></i> <b>' + name + ':</b> ' + lbl);
    }
    return parts.join('<br>');
}

function show_node_info(id) {
    var node = nodes_index[id];
    if (!node) return;
    var key = node.url ? node.url.replace('https://t.me/', '') : '';
    el('node_label').innerHTML           = node.label || id;
    el('node_url').innerHTML             = '@' + key;
    el('node_url').href                  = node.url || '#';
    el('node_picture').innerHTML         = node.pic ? "<img src='" + node.pic + "' style='max-width:60px'>" : '';
    el('node_group').innerHTML           = get_group_html(id);
    el('node_followers_count').innerHTML = node.fans || '';
    el('node_messages_count').innerHTML  = node.messages_count || '';
    el('node_activity_period').innerHTML = node.activity_period || '';
    el('node_is_lost').style.display     = node.is_lost ? '' : 'none';
    el('node_details').style.display     = '';

    var mhtml = '';
    if (accessory_data) {
        accessory_data.measures.forEach(function(m) {
            if (BASE_MEASURE_KEYS[m[0]]) return;
            var val = node[m[0]];
            mhtml += '<br><abbr>' + m[1] + '</abbr>: ' + (val != null ? val.toFixed(4) : 'N/A');
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
        return '<option value="' + s + '">' + s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() + '</option>';
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
    Promise.all([
        fetch((window.DATA_DIR||'data/')+'channel_position_3d.json').then(function(r) { return r.json(); }),
        fetch((window.DATA_DIR||'data/')+'channels.json').then(function(r) { return r.json(); }),
        fetch((window.DATA_DIR||'data/')+'communities.json').then(function(r) { return r.json(); }),
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
        el('loading_message').innerHTML = 'Done!';
        bootstrap.Modal.getInstance(el('loading_modal')).hide();
        reset_camera();
    }).catch(function(err) {
        el('loading_message').innerHTML = 'Error: ' + err.message;
        console.error(err);
    });
}

// =============================================================================
// DOMContentLoaded
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    init_three();

    var loading_el       = el('loading_modal');
    var loading_modal_bs = new bootstrap.Modal(loading_el, { backdrop: 'static', keyboard: false });
    loading_el.addEventListener('shown.bs.modal', function() { get_data(); }, { once: true });
    loading_modal_bs.show();
    el('loading_message').innerHTML = 'Loading…<br>Please wait.';

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
