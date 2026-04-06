import { Sigma } from 'sigma';
import Graph from 'graphology';
import EdgeCurveProgram from '@sigma/edge-curve';
import { drawDiscNodeLabel } from 'sigma/rendering';

// =============================================================================
// Measure and strategy tooltips
// =============================================================================

var BASE_MEASURE_KEYS = { 'in_deg': true, 'out_deg': true, 'fans': true, 'messages_count': true };

// Shorthand for document.getElementById
function el(id) { return document.getElementById(id); }

// =============================================================================
// State
// =============================================================================

var loading_modal_bs       = null;
var accessory_data         = null;
var active_strategy        = null;
var community_color_maps    = {};      // { strategyKey: { communityLabel: hexColor } }
var community_strategy_data = {};     // { strategyKey: { groups: [...] } }
var graph_loaded           = false;
var accessory_loaded       = false;
var is_graph_completely_rendered = false;

// =============================================================================
// Sigma and graph instances
// sigma 3.x: Sigma.Sigma is the main class (UMD global is `Sigma` namespace)
// graphology: graphology.Graph is the main class (UMD global is `graphology` namespace)
// =============================================================================

var app_settings = {
    container:                  'sigma-canvas',
    container_background_color: 'rgba(17, 34, 51, 1)',
    fade_color:                 'rgba(27, 44, 61, .75)'
};

el(app_settings.container).style.backgroundColor = app_settings.container_background_color;

// drawDiscNodeHover hardcodes a white (#FFF) label background, clashing with our
// white label text. This override uses a dark background instead.
function drawDarkNodeHover(context, data, settings) {
    var size = settings.labelSize, font = settings.labelFont, weight = settings.labelWeight;
    context.font = weight + ' ' + size + 'px ' + font;
    context.fillStyle = '#111';
    context.shadowOffsetX = 0; context.shadowOffsetY = 0;
    context.shadowBlur = 8; context.shadowColor = '#000';
    var PADDING = 2;
    if (typeof data.label === 'string') {
        var textWidth = context.measureText(data.label).width,
            boxWidth  = Math.round(textWidth + 5),
            boxHeight = Math.round(size + 2 * PADDING),
            radius    = Math.max(data.size, size / 2) + PADDING;
        var angleRadian  = Math.asin(boxHeight / 2 / radius);
        var xDeltaCoord  = Math.sqrt(Math.abs(Math.pow(radius, 2) - Math.pow(boxHeight / 2, 2)));
        context.beginPath();
        context.moveTo(data.x + xDeltaCoord, data.y + boxHeight / 2);
        context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
        context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
        context.lineTo(data.x + xDeltaCoord, data.y - boxHeight / 2);
        context.arc(data.x, data.y, radius, angleRadian, -angleRadian);
        context.closePath();
        context.fill();
    } else {
        context.beginPath();
        context.arc(data.x, data.y, data.size + PADDING, 0, Math.PI * 2);
        context.closePath();
        context.fill();
    }
    context.shadowOffsetX = 0; context.shadowOffsetY = 0; context.shadowBlur = 0;
    drawDiscNodeLabel(context, data, settings);
}

var graph = new Graph({ type: 'directed', multi: false });
var sigma_instance = new Sigma(graph, el(app_settings.container), {
    defaultEdgeColor:           '#484848',
    defaultNodeColor:           '#333',
    labelColor:                 { color: '#FFFFFF' },
    labelSize:                  12,
    labelFont:                  'sans-serif',
    labelWeight:                'bold',
    labelRenderedSizeThreshold: 8,
    renderEdgeLabels:           false,
    hideEdgesOnMove:            true,
    minCameraRatio:             0.03125,
    maxCameraRatio:             20,
    defaultEdgeType:            'curved',
    edgeProgramClasses:         { curved: EdgeCurveProgram },
    defaultDrawNodeHover:       drawDarkNodeHover
});

// Sigma enables gl.BLEND but leaves the blend function at the WebGL default
// (ONE, ZERO), which ignores alpha. Override it on the edge context so
// overlapping semi-transparent edges composite correctly.
sigma_instance.on('beforeRender', function() {
    var gl = sigma_instance.webGLContexts && sigma_instance.webGLContexts.edges;
    if (gl) gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
});

// =============================================================================
// Color helpers
// =============================================================================

function hex_to_rgb_parts(hex) {
    hex = hex.replace(/^#/, '');
    if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
    return [parseInt(hex.slice(0,2),16), parseInt(hex.slice(2,4),16), parseInt(hex.slice(4,6),16)];
}

function rgb_str_to_parts(s) {
    var m = s.match(/(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    return m ? [+m[1], +m[2], +m[3]] : [128, 128, 128];
}

function avg_and_darken(c1, c2, factor) {
    return [
        Math.round((c1[0]+c2[0])/2 * factor),
        Math.round((c1[1]+c2[1])/2 * factor),
        Math.round((c1[2]+c2[2])/2 * factor)
    ];
}


// =============================================================================
// Graph helpers (replaces sigma v1 graph.addMethod extensions)
// =============================================================================

function structured_neighbors(nodeId) {
    var in_set  = new Set(graph.inNeighbors(nodeId));
    var out_set = new Set(graph.outNeighbors(nodeId));
    var mutual_neighbors = [];
    var in_neighbors     = [];
    var out_neighbors    = [];
    graph.neighbors(nodeId).forEach(function(k) {
        if      (in_set.has(k) && out_set.has(k)) mutual_neighbors.push(k);
        else if (in_set.has(k))                   in_neighbors.push(k);
        else if (out_set.has(k))                  out_neighbors.push(k);
    });
    return { mutual_neighbors: mutual_neighbors, in_neighbors: in_neighbors, out_neighbors: out_neighbors };
}

// =============================================================================
// Infobar
// =============================================================================

function node_sort(x, y) {
    return (x.label || '').localeCompare(y.label || '');
}

function get_anchor(node) {
    var color = node.originalColor || '#ccc';
    var label = (active_strategy && node.communities) ? (node.communities[active_strategy] || '') : '';
    return '<i class="bi bi-circle-fill" aria-hidden="true" style="color: ' + color + '" title="' + label + '"></i>'
         + ' <a href="#" class="node-link" data="' + node.id + '">' + (node.label || node.id) + '</a>';
}

function get_group(node) {
    if (!node.communities || !community_color_maps) return '';
    var parts = [];
    for (var strategy in node.communities) {
        var label       = node.communities[strategy] || '';
        var colorMap    = community_color_maps[strategy] || {};
        var color       = (label && colorMap[label]) ? colorMap[label] : '#ccc';
        var displayName = strategy.charAt(0).toUpperCase() + strategy.slice(1);
        parts.push('<i class="bi bi-circle-fill" aria-hidden="true" style="color: ' + color + '"></i>'
                 + ' <b>' + displayName + ':</b> ' + label);
    }
    return parts.join('<br>');
}

function get_neighbors_list(id_list) {
    var nodes = id_list.map(function(id) { return graph.getNodeAttributes(id); });
    nodes.sort(node_sort);
    return nodes.map(function(node) { return '<li>' + get_anchor(node) + '</li>'; });
}

function show_node_info(nodeId) {
    var node = graph.getNodeAttributes(nodeId);
    var key = node.url ? node.url.replace('https://t.me/', '') : '';
    el('node_label').innerHTML = node.label || node.id;
    var urlEl = el('node_url');
    urlEl.innerHTML = '@' + key;
    urlEl.href = node.url;
    el('node_picture').innerHTML = node.pic ? "<img src='" + node.pic + "' style='max-width: 60px;' />" : '';
    el('node_group').innerHTML = get_group(node);
    el('node_followers_count').innerHTML = node.fans;
    var measures_html = '';
    if (accessory_data) {
        accessory_data.measures.forEach(function(m) {
            if (BASE_MEASURE_KEYS[m[0]]) return;
            var val = node[m[0]];
            var formatted = (val !== undefined && val !== null) ? val.toFixed(4) : 'N/A';
            measures_html += '<br><abbr>' + m[1] + '</abbr>: ' + formatted;
        });
    }
    el('node_measures').innerHTML = measures_html;
    el('node_messages_count').innerHTML = node.messages_count;
    el('node_activity_period').innerHTML = node.activity_period;
    el('node_is_lost').style.display = node.is_lost ? '' : 'none';
    el('node_details').style.display = '';

    var nbrs    = structured_neighbors(nodeId);
    var mutual  = get_neighbors_list(nbrs.mutual_neighbors);
    var inbound = get_neighbors_list(nbrs.in_neighbors);
    var outbound= get_neighbors_list(nbrs.out_neighbors);
    el('node_mutual_count').innerHTML = mutual.length;  el('node_mutual_list').innerHTML = mutual.join('');
    el('node_in_count').innerHTML = inbound.length;     el('node_in_list').innerHTML = inbound.join('');
    el('node_out_count').innerHTML = outbound.length;   el('node_out_list').innerHTML = outbound.join('');
    el('infobar').style.display = 'block';
}

// =============================================================================
// Community coloring
// =============================================================================

function build_community_color_maps(communities) {
    var maps = {};
    for (var strategy in communities) {
        maps[strategy] = {};
        var groups = communities[strategy].groups;
        for (var i = 0; i < groups.length; i++) {
            // groups[i] = [id, count, label, hexColor]
            maps[strategy][groups[i][2]] = groups[i][3];
        }
    }
    return maps;
}

function apply_strategy_colors(strategy) {
    var colorMap = community_color_maps[strategy] || {};
    graph.nodes().forEach(function(id) {
        var n     = graph.getNodeAttributes(id);
        var label = n.communities && n.communities[strategy];
        var rgb   = (label && colorMap[label]) ? hex_to_rgb_parts(colorMap[label]) : [204, 204, 204];
        var color = 'rgb(' + rgb.join(',') + ')';
        graph.setNodeAttribute(id, 'color', color);
        graph.setNodeAttribute(id, 'originalColor', color);
    });
    graph.edges().forEach(function(edgeId) {
        var src = graph.getNodeAttributes(graph.source(edgeId));
        var tgt = graph.getNodeAttributes(graph.target(edgeId));
        var avg   = avg_and_darken(rgb_str_to_parts(src.originalColor), rgb_str_to_parts(tgt.originalColor), 0.75);
        var color = 'rgba(' + avg.join(',') + ',0.25)';
        graph.setEdgeAttribute(edgeId, 'color', color);
        graph.setEdgeAttribute(edgeId, 'originalColor', color);
    });
    sigma_instance.refresh();
    is_graph_completely_rendered = true;
}

function maybe_apply_initial_colors() {
    if (graph_loaded && accessory_loaded && active_strategy)
        apply_strategy_colors(active_strategy);
}

// =============================================================================
// Node sizing
// =============================================================================

function apply_node_size(metric) {
    var vals  = graph.nodes().map(function(id) { return graph.getNodeAttribute(id, metric) || 0; });
    var minV  = Math.min.apply(null, vals);
    var range = (Math.max.apply(null, vals) - minV) || 1;
    graph.nodes().forEach(function(id) {
        var val = graph.getNodeAttribute(id, metric) || 0;
        graph.setNodeAttribute(id, 'size', 1.5 + (val - minV) / range * 13.5);
    });
    sigma_instance.refresh();
}

// =============================================================================
// UI builders
// =============================================================================

function build_strategy_selector(communities) {
    var strategies = Object.keys(communities);
    if (strategies.length <= 1) { el('community-strategy-group').style.display = 'none'; return; }
    var items = strategies.map(function(s) {
        return '<option value="' + s + '">' + s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() + '</option>';
    });
    el('community-strategy-select').innerHTML = items.join('');
    el('community-strategy-group').style.display = '';
}

function build_legend(strategyData) {
    var legend_items       = [];
    var group_select_items = ['<option value="" selected="selected">All nodes</option>'];
    strategyData.groups.forEach(function(l) {
        // l = [id, count, label, hexColor]
        legend_items.push(
            '<li style="padding-bottom: .75em;">'
            + '<i class="bi bi-circle-fill" style="color: ' + l[3] + ';"></i> ' + l[2] + ', ' + l[1] + ' channels'
            + '</li>'
        );
        group_select_items.push('<option value="' + l[2] + '">' + l[2] + '</option>');
    });
    el('legend').innerHTML = legend_items.join('');
    el('group-select').innerHTML = group_select_items.join('');
}

// =============================================================================
// Search
// =============================================================================

function search(word, result_el) {
    result_el.innerHTML = '';
    if (word.length <= 2) {
        result_el.innerHTML = '<i>Search for terms of at least 3 characters.</i>';
        result_el.style.display = '';
        return;
    }
    var pattern = RegExp(word, 'i');
    var matches = [];
    graph.nodes().forEach(function(id) {
        var n = graph.getNodeAttributes(id);
        if (pattern.test(n.label)) matches.push(n);
    });
    matches.sort(node_sort);

    var html = ['<b>Results:</b> <ul class="list-unstyled">'];
    if (matches.length > 0) {
        matches.forEach(function(n) { html.push('<li>' + get_anchor(n) + '</li>'); });
        html.push('</ul><i>' + (matches.length === 1 ? '1 channel' : matches.length + ' channels') + '</i>');
    } else {
        html.push('<li><i>No results.</i></li></ul>');
    }
    result_el.innerHTML = html.join('');
    result_el.style.display = '';
}

// =============================================================================
// Node selection
// =============================================================================

function select_node(nodeId) {
    var neighbors = new Set(graph.neighbors(nodeId));
    neighbors.add(nodeId);
    show_node_info(nodeId);
    graph.nodes().forEach(function(id) {
        graph.setNodeAttribute(id, 'color',
            neighbors.has(id)
                ? graph.getNodeAttribute(id, 'originalColor')
                : app_settings.fade_color);
    });
    graph.edges().forEach(function(edgeId) {
        var src = graph.source(edgeId);
        var tgt = graph.target(edgeId);
        graph.setEdgeAttribute(edgeId, 'color',
            (neighbors.has(src) && neighbors.has(tgt))
                ? graph.getEdgeAttribute(edgeId, 'originalColor')
                : app_settings.fade_color);
    });
    sigma_instance.refresh();
    is_graph_completely_rendered = false;
}

function reset_colors() {
    graph.nodes().forEach(function(id) {
        graph.setNodeAttribute(id, 'color', graph.getNodeAttribute(id, 'originalColor'));
    });
    graph.edges().forEach(function(edgeId) {
        graph.setEdgeAttribute(edgeId, 'color', graph.getEdgeAttribute(edgeId, 'originalColor'));
    });
    sigma_instance.refresh();
    is_graph_completely_rendered = true;
}

function click_node(nodeId) {
    if (!is_graph_completely_rendered) reset_colors();
    select_node(nodeId);
}

// =============================================================================
// Graph loading
// =============================================================================

function get_data() {
    Promise.all([
        fetch((window.DATA_DIR||'data/')+'channel_position.json').then(function(r) { return r.json(); }),
        fetch((window.DATA_DIR||'data/')+'channels.json').then(function(r) { return r.json(); }),
    ]).then(function(results) {
        var pos_data = results[0];
        var ch_data  = results[1];
        el('loading_message').innerHTML = 'Building graph…';

        var measure_map = {};
        ch_data.nodes.forEach(function(n) { measure_map[n.id] = n; });

        var inDegVals  = pos_data.nodes.map(function(n) { return (measure_map[n.id] || {}).in_deg || 0; });
        var minInDeg   = Math.min.apply(null, inDegVals);
        var inDegRange = (Math.max.apply(null, inDegVals) - minInDeg) || 1;

        pos_data.nodes.forEach(function(pos) {
            var m = measure_map[pos.id] || {};
            var rgbColor = 'rgb(' + (m.color || '128,128,128') + ')';
            graph.addNode(pos.id, Object.assign({}, m, {
                id:            pos.id,
                x:             pos.x,
                y:             pos.y,
                size:          1.5 + ((m.in_deg || 0) - minInDeg) / inDegRange * 13.5,
                color:         rgbColor,
                originalColor: rgbColor
            }));
        });

        pos_data.edges.forEach(function(e) {
            var color = e.color ? 'rgba(' + e.color + ',0.25)' : 'rgba(72,72,72,0.25)';
            var attrs = Object.assign({}, e, { color: color, originalColor: color });
            delete attrs.source;
            delete attrs.target;
            delete attrs.id;
            try {
                graph.addEdge(e.source, e.target, attrs);
            } catch(err) { /* skip duplicate or invalid edges */ }
        });

        sigma_instance.refresh();
        el('loading_message').innerHTML = 'Done!';
        if (loading_modal_bs) loading_modal_bs.hide();
        el('about_graph_stats').innerHTML =
            graph.nodes().length + ' channels, ' +
            graph.edges().length + ' connections';

        graph_loaded = true;
        maybe_apply_initial_colors();

        sigma_instance.on('clickNode', function(event) {
            click_node(event.node);
        });

        sigma_instance.on('clickStage', function() {
            if (!is_graph_completely_rendered) reset_colors();
        });
    });
}

// =============================================================================
// Document ready
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    var loading_el = document.getElementById('loading_modal');
    loading_modal_bs = new bootstrap.Modal(loading_el, { backdrop: 'static', keyboard: false });
    loading_el.addEventListener('shown.bs.modal', function() { get_data(); }, { once: true });
    loading_modal_bs.show();
    el('loading_message').innerHTML = 'Loading…<br>Please wait.';

    Promise.all([
        fetch((window.DATA_DIR||'data/')+'channels.json').then(function(r) { return r.json(); }),
        fetch((window.DATA_DIR||'data/')+'communities.json').then(function(r) { return r.json(); }),
    ]).then(function(results) {
        var ch_data   = results[0];
        var comm_data = results[1];

        accessory_data = ch_data;

        community_strategy_data = comm_data.strategies;

        community_color_maps = build_community_color_maps(comm_data.strategies);
        var strategies       = Object.keys(comm_data.strategies);
        active_strategy      = strategies[0] || null;

        build_strategy_selector(comm_data.strategies);
        if (active_strategy) build_legend(comm_data.strategies[active_strategy]);

        var size_items = ch_data.measures.map(function(m) {
            return '<option value="' + m[0] + '">' + m[1] + '</option>';
        });
        el('size-select').innerHTML = size_items.join('');
        var tpc = el('total_pages_count'); if (tpc) tpc.innerHTML = ch_data.total_pages_count;

        accessory_loaded = true;
        maybe_apply_initial_colors();
    });

    el('community-strategy-select').addEventListener('change', function() {
        active_strategy = this.value;
        if (community_strategy_data) build_legend(community_strategy_data[active_strategy]);
        if (graph_loaded) {
            apply_strategy_colors(active_strategy);
            el('group-select').value = '';
        }
    });

    el('search_input').value = '';
    el('search_modal').addEventListener('shown.bs.modal', function() { el('search_input').focus(); });
    el('search').addEventListener('submit', function(e) {
        e.preventDefault();
        search(el('search_input').value, el('results'));
    });

    document.querySelectorAll('.infobar-toggle').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var infobar = el('infobar');
            infobar.style.display = infobar.style.display === 'none' ? 'block' : 'none';
            if (!is_graph_completely_rendered) reset_colors();
        });
    });

    document.addEventListener('click', function(e) {
        var link = e.target.closest('a.node-link');
        if (!link) return;
        e.preventDefault();
        click_node(link.getAttribute('data'));
    });

    el('size-select').addEventListener('change', function() { apply_node_size(this.value); });

    el('labels-select').addEventListener('change', function() {
        var thresholds = { 'always': 0, 'on_size': 8, 'never': Infinity };
        sigma_instance.setSetting('labelRenderedSizeThreshold', thresholds[this.value]);
    });

    el('group-select').addEventListener('change', function() {
        var v = this.value;
        if (v === '') {
            graph.nodes().forEach(function(id) {
                graph.setNodeAttribute(id, 'color', graph.getNodeAttribute(id, 'originalColor'));
            });
            graph.edges().forEach(function(edgeId) {
                graph.setEdgeAttribute(edgeId, 'color', graph.getEdgeAttribute(edgeId, 'originalColor'));
            });
            sigma_instance.refresh();
            is_graph_completely_rendered = true;
            return;
        }
        var toKeep = new Set();
        graph.nodes().forEach(function(id) {
            var communities = graph.getNodeAttribute(id, 'communities');
            var label = (communities && active_strategy) ? communities[active_strategy] : '';
            if (label === v) toKeep.add(id);
        });
        graph.nodes().forEach(function(id) {
            graph.setNodeAttribute(id, 'color',
                toKeep.has(id) ? graph.getNodeAttribute(id, 'originalColor') : app_settings.fade_color);
        });
        graph.edges().forEach(function(edgeId) {
            var src = graph.source(edgeId);
            var tgt = graph.target(edgeId);
            graph.setEdgeAttribute(edgeId, 'color',
                (toKeep.has(src) && toKeep.has(tgt))
                    ? graph.getEdgeAttribute(edgeId, 'originalColor')
                    : app_settings.fade_color);
        });
        sigma_instance.refresh();
        is_graph_completely_rendered = false;
    });

    el('zoom_in').addEventListener('click', function() {
        var cam = sigma_instance.getCamera();
        cam.setState(Object.assign({}, cam.getState(), { ratio: cam.getState().ratio * 0.5 }));
    });
    el('zoom_out').addEventListener('click', function() {
        var cam = sigma_instance.getCamera();
        cam.setState(Object.assign({}, cam.getState(), { ratio: cam.getState().ratio * 1.5 }));
    });
    el('zoom_reset').addEventListener('click', function() {
        sigma_instance.getCamera().setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 });
    });
});
