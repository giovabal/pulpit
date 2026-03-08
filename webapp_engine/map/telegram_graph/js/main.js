// =============================================================================
// Sigma graph extensions
// =============================================================================

sigma.classes.graph.addMethod('neighbors', function(nodeId) {
    var k, neighbors = {}, index = this.allNeighborsIndex[nodeId] || {};
    for (k in index) neighbors[k] = this.nodesIndex[k];
    return neighbors;
});

sigma.classes.graph.addMethod('structured_neighbors', function(nodeId) {
    var k,
        mutual_neighbors = [],
        in_neighbors     = [],
        out_neighbors    = [],
        index    = this.allNeighborsIndex[nodeId] || {},
        in_index  = this.inNeighborsIndex[nodeId]  || {},
        out_index = this.outNeighborsIndex[nodeId] || {};

    for (k in index) {
        if      (k in in_index && k in out_index) mutual_neighbors[k] = this.nodesIndex[k];
        else if (k in in_index)                   in_neighbors[k]     = this.nodesIndex[k];
        else if (k in out_index)                  out_neighbors[k]    = this.nodesIndex[k];
    }
    return { mutual_neighbors: mutual_neighbors, in_neighbors: in_neighbors, out_neighbors: out_neighbors };
});

// =============================================================================
// Measure and strategy tooltips
// =============================================================================

var MEASURE_TITLES = {
    'in_deg':               'Total weighted inbound connections from other channels in the network.',
    'out_deg':              'Total weighted outbound connections to other channels in the network.',
    'fans':                 'Number of subscribers as reported by Telegram.',
    'messages_count':       'Total number of messages collected from this channel.',
    'pagerank':             'Measures global influence based on how many other influential channels forward or reference this one. Channels cited by important channels score higher.',
    'hits_hub':             'Identifies channels that actively amplify content from authoritative sources. High-scoring hubs are aggregators and megaphones spreading information across political communities.',
    'hits_authority':       'Identifies channels widely cited by important hubs. High-scoring authorities are trusted sources whose content is frequently forwarded or referenced by other channels.',
    'betweenness':          'How often this channel lies on the shortest path between other channels. High betweenness indicates a broker connecting otherwise separate political communities or movements.',
    'in_degree_centrality': 'Normalized share of all channels in the network that reference or forward this channel. Reflects how widely cited it is across the entire network, regardless of the citing channels\' importance.'
};

var STRATEGY_TITLES = {
    'ORGANIZATION': 'Channels are grouped by their manually assigned organization. Reflects real-world political affiliation as defined by the analyst.',
    'LOUVAIN':      'Automatic clustering based on connection density. Groups channels that heavily forward or reference each other, revealing emergent coordination clusters within or across movements.',
    'KCORE':        'Groups channels by their k-shell decomposition level. The innermost core contains the most densely interconnected channels, forming the structural backbone of the network.',
    'INFOMAP':      'Detects communities by simulating information flow through the network. Groups channels through which the same content tends to circulate, revealing functional echo chambers.'
};

// =============================================================================
// State
// =============================================================================

var loading_modal_bs     = null;
var accessory_data       = null;
var active_strategy      = null;
var community_color_maps = {};      // { strategyKey: { communityLabel: hexColor } }
var graph_loaded         = false;
var accessory_loaded     = false;
var is_graph_completely_rendered = false;

// =============================================================================
// Sigma instance
// =============================================================================

var settings = {
    container:                'sigma-canvas',
    container_background_color: 'rgba(17, 34, 51, 1)',
    fade_color:               'rgba(27, 44, 61, .75)'
};

$('#' + settings.container).css('background-color', settings.container_background_color);

var sigma_instance = new sigma({
    renderer: { container: settings.container, type: 'canvas' },
    settings: {
        autoRescale:         true,
        mouseEnabled:        true,
        touchEnabled:        true,
        nodesPowRatio:       1,
        edgesPowRatio:       1,
        defaultEdgeColor:    '#484848',
        defaultNodeColor:    '#333',
        defaultEdgeType:     'curve',
        edgeColor:           'default',
        minNodeSize:         1,
        maxNodeSize:         10,
        minEdgeSize:         0.2,
        maxEdgeSize:         0.5,
        defaultLabelSize:    12,
        defaultLabelColor:   '#FFFFFF',
        activeFontStyle:     'bold',
        font:                'sans-serif',
        defaultLabelBGColor: '#ddd',
        zoomMin:             0.03125,
        batchEdgesDrawing:   true,
        hideEdgesOnMove:     true,
        labelThreshold:      15,
        hoverFontStyle:      'bold',
        drawEdgeLabels:      false
    }
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
// Infobar
// =============================================================================

function node_sort(x, y) {
    return x.label.localeCompare(y.label);
}

function get_anchor(node) {
    var color = node.originalColor || '#ccc';
    var label = (active_strategy && node.communities) ? (node.communities[active_strategy] || '') : '';
    return '<i class="fa fa-circle" aria-hidden="true" style="color: ' + color + '" title="' + label + '"></i>'
         + ' <a href="#" class="node-link" data="' + node.id + '">' + node.label + '</a>';
}

function get_group(node) {
    if (!node.communities || !community_color_maps) return '';
    var parts = [];
    for (var strategy in node.communities) {
        var label       = node.communities[strategy] || '';
        var colorMap    = community_color_maps[strategy] || {};
        var color       = (label && colorMap[label]) ? colorMap[label] : '#ccc';
        var displayName = strategy.charAt(0).toUpperCase() + strategy.slice(1);
        parts.push('<i class="fa fa-circle" aria-hidden="true" style="color: ' + color + '"></i>'
                 + ' <b>' + displayName + ':</b> ' + label);
    }
    return parts.join('<br>');
}

function get_neighbors_list(obj_list) {
    var neighbors = [];
    for (var n in obj_list) neighbors.push(obj_list[n]);
    neighbors.sort(node_sort);
    return neighbors.map(function(node) { return '<li>' + get_anchor(node) + '</li>'; });
}

function show_node_info(node) {
    var key = node.url ? node.url.replace('https://t.me/', '') : '';
    $('#node_label').html(node.label);
    $('#node_url').html('@' + key).attr('href', node.url);
    $('#node_picture').html(node.pic ? "<img src='" + node.pic + "' style='max-width: 60px;' />" : '');
    $('#node_group').html(get_group(node));
    $('#node_followers_count').html(node.fans);
    $('#node_pagerank').html(node.pagerank ? node.pagerank.toFixed(4) : 'N/A');
    $('#node_hits_hub').html(node.hits_hub !== undefined ? node.hits_hub.toFixed(4) : 'N/A');
    $('#node_hits_authority').html(node.hits_authority !== undefined ? node.hits_authority.toFixed(4) : 'N/A');
    $('#node_betweenness').html(node.betweenness !== undefined ? node.betweenness.toFixed(4) : 'N/A');
    $('#node_in_degree_centrality').html(node.in_degree_centrality !== undefined ? node.in_degree_centrality.toFixed(4) : 'N/A');
    $('#node_messages_count').html(node.messages_count);
    $('#node_activity_period').html(node.activity_period);
    if (node.is_lost) $('#node_is_lost').show(); else $('#node_is_lost').hide();
    $('#node_details').show();

    var nbrs    = sigma_instance.graph.structured_neighbors(node.id);
    var mutual  = get_neighbors_list(nbrs.mutual_neighbors);
    var inbound = get_neighbors_list(nbrs.in_neighbors);
    var outbound= get_neighbors_list(nbrs.out_neighbors);
    $('#node_mutual_count').html(mutual.length);   $('#node_mutual_list').html(mutual.join(''));
    $('#node_in_count').html(inbound.length);      $('#node_in_list').html(inbound.join(''));
    $('#node_out_count').html(outbound.length);    $('#node_out_list').html(outbound.join(''));
    $('#infobar').show();
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
    sigma_instance.graph.nodes().forEach(function(n) {
        var label = n.communities && n.communities[strategy];
        var rgb   = (label && colorMap[label]) ? hex_to_rgb_parts(colorMap[label]) : [204, 204, 204];
        n.color   = n.originalColor = 'rgb(' + rgb.join(',') + ')';
    });
    sigma_instance.graph.edges().forEach(function(e) {
        var src = sigma_instance.graph.nodes(e.source);
        var tgt = sigma_instance.graph.nodes(e.target);
        var avg = avg_and_darken(rgb_str_to_parts(src.originalColor), rgb_str_to_parts(tgt.originalColor), 0.75);
        e.color = e.originalColor = 'rgba(' + avg.join(',') + ',0.25)';
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
    var nodes = sigma_instance.graph.nodes();
    var vals  = nodes.map(function(n) { return n[metric] || 0; });
    var minV  = Math.min.apply(null, vals);
    var range = (Math.max.apply(null, vals) - minV) || 1;
    nodes.forEach(function(n) { n.size = 0.1 + ((n[metric] || 0) - minV) / range * 9.9; });
    sigma_instance.refresh();
}

// =============================================================================
// UI builders
// =============================================================================

function build_strategy_selector(communities) {
    var strategies = Object.keys(communities);
    if (strategies.length <= 1) { $('#community-strategy-group').hide(); return; }
    var items = strategies.map(function(s) {
        var title = STRATEGY_TITLES[s] ? ' title="' + STRATEGY_TITLES[s] + '"' : '';
        return '<option value="' + s + '"' + title + '>' + s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() + '</option>';
    });
    $('#community-strategy-select').html(items.join(''));
    $('#community-strategy-group').show();
}

function build_legend(strategyData) {
    var legend_items       = [];
    var group_select_items = ['<option value="" selected="selected">All nodes</option>'];
    strategyData.groups.forEach(function(l) {
        // l = [id, count, label, hexColor]
        legend_items.push(
            '<li style="padding-bottom: .75em;">'
            + '<i class="fa fa-circle" style="color: ' + l[3] + ';"></i> ' + l[2] + ', ' + l[1] + ' channels'
            + '</li>'
        );
        group_select_items.push('<option value="' + l[2] + '">' + l[2] + '</option>');
    });
    $('#legend').html(legend_items.join(''));
    $('#group-select').html(group_select_items.join(''));
}

// =============================================================================
// Search
// =============================================================================

function search(word, result_element) {
    result_element.empty();
    if (word.length <= 2) {
        result_element.html('<i>Search for terms of at least 3 characters.</i>').show();
        return;
    }
    var pattern = RegExp(word, 'i');
    var matches = [];
    sigma_instance.graph.nodes().forEach(function(n) {
        if (pattern.test(n.label)) matches.push(sigma_instance.graph.nodes(n.id));
    });
    matches.sort(node_sort);

    var html = ['<b>Results:</b> <ul class="list-unstyled">'];
    if (matches.length > 0) {
        matches.forEach(function(n) { html.push('<li>' + get_anchor(n) + '</li>'); });
        html.push('</ul><i>' + (matches.length === 1 ? '1 channel' : matches.length + ' channels') + '</i>');
    } else {
        html.push('<li><i>No results.</i></li></ul>');
    }
    result_element.html(html.join('')).show();
}

function select_node(node) {
    var toKeep = sigma_instance.graph.neighbors(node.id);
    toKeep[node.id] = node;
    show_node_info(node);
    sigma_instance.graph.nodes().forEach(function(n) {
        n.color = toKeep[n.id] ? n.originalColor : settings.fade_color;
    });
    sigma_instance.graph.edges().forEach(function(e) {
        e.color = (toKeep[e.source] && toKeep[e.target]) ? e.originalColor : settings.fade_color;
    });
    sigma_instance.refresh();
    is_graph_completely_rendered = false;
}

function reset_colors() {
    sigma_instance.graph.nodes().forEach(function(n) { n.color = n.originalColor; });
    sigma_instance.graph.edges().forEach(function(e) { e.color = e.originalColor; });
    sigma_instance.refresh();
    is_graph_completely_rendered = true;
}

function click_node(nodeId) {
    if (!is_graph_completely_rendered) reset_colors();
    var n = sigma_instance.graph.nodes(nodeId);
    if (n) select_node(n);
}

// =============================================================================
// Graph loading
// =============================================================================

function get_data() {
    $.getJSON('data.json', function(data) {
        $('#loading_message').html('Building graph…');
        sigma_instance.graph.read(data);

        sigma_instance.graph.nodes().forEach(function(n) {
            n.size          = (n.in_deg || 0) + 1;
            n.color         = 'rgb(' + n.color + ')';
            n.originalColor = n.color;
        });
        sigma_instance.graph.edges().forEach(function(e) {
            e.color         = e.color ? 'rgba(' + e.color + ',0.25)' : 'rgba(72,72,72,0.25)';
            e.originalColor = e.color;
        });
        sigma_instance.refresh();
        $('#loading_message').html('Done!');
        if (loading_modal_bs) loading_modal_bs.hide();

        graph_loaded = true;
        maybe_apply_initial_colors();

        sigma_instance.bind('clickNode', function(e) {
            var node = e.data.node !== undefined ? e.data.node : e.data;
            select_node(node);
        });

        sigma_instance.bind('clickStage', function() {
            if (!is_graph_completely_rendered) reset_colors();
        });
    });
}

// =============================================================================
// Document ready
// =============================================================================

$(document).ready(function() {
    var loading_el = document.getElementById('loading_modal');
    loading_modal_bs = new bootstrap.Modal(loading_el, { backdrop: 'static', keyboard: false });
    loading_el.addEventListener('shown.bs.modal', function() { get_data(); }, { once: true });
    loading_modal_bs.show();
    $('#loading_message').html('Loading…<br>Please wait.');

    $.getJSON('data_accessory.json', function(data) {
        accessory_data       = data;
        community_color_maps = build_community_color_maps(data.communities);
        var strategies       = Object.keys(data.communities);
        active_strategy      = strategies[0] || null;

        build_strategy_selector(data.communities);
        if (active_strategy) build_legend(data.communities[active_strategy]);

        var size_items = data.measures.map(function(m) {
            var title = MEASURE_TITLES[m[0]] ? ' title="' + MEASURE_TITLES[m[0]] + '"' : '';
            return '<option value="' + m[0] + '"' + title + '>' + m[1] + '</option>';
        });
        $('#size-select').html(size_items.join(''));
        $('#total_pages_count').html(data.total_pages_count);

        accessory_loaded = true;
        maybe_apply_initial_colors();
    });

    $('#community-strategy-select').on('change', function() {
        active_strategy = $(this).val();
        if (accessory_data) build_legend(accessory_data.communities[active_strategy]);
        if (graph_loaded) {
            apply_strategy_colors(active_strategy);
            $('#group-select').val('');
        }
    });

    $('#search_input').val('');
    $('#search_modal').on('shown.bs.modal', function() { $('#search_input').focus(); });
    $('#search').submit(function() {
        search($('#search_input').val(), $('#results'));
        return false;
    });

    $('.infobar-toggle').on('click', function() {
        $('#infobar').toggle();
        sigma_instance.dispatchEvent('clickStage');
    });

    $('body').on('click', 'a.node-link', function() {
        click_node($(this).attr('data'));
        return false;
    });

    $('#size-select').on('change', function() { apply_node_size($(this).val()); });

    $('#labels-select').on('change', function() {
        var thresholds = { 'always': 0, 'on_size': 15, 'never': Infinity };
        sigma_instance.settings('labelThreshold', thresholds[$(this).val()]);
        sigma_instance.refresh();
    });

    $('#group-select').on('change', function() {
        var v = $(this).val();
        if (v === '') {
            sigma_instance.graph.nodes().forEach(function(n) { n.color = n.originalColor; });
            sigma_instance.graph.edges().forEach(function(e) { e.color = e.originalColor; });
            sigma_instance.refresh();
            is_graph_completely_rendered = true;
            return;
        }
        var toKeep = [];
        sigma_instance.graph.nodes().forEach(function(n) {
            var label = (n.communities && active_strategy) ? n.communities[active_strategy] : '';
            if (label === v) toKeep.push(n.id);
        });
        sigma_instance.graph.nodes().forEach(function(n) {
            n.color = toKeep.indexOf(n.id) >= 0 ? n.originalColor : settings.fade_color;
        });
        sigma_instance.graph.edges().forEach(function(e) {
            e.color = (toKeep.indexOf(e.source) >= 0 && toKeep.indexOf(e.target) >= 0)
                ? e.originalColor : settings.fade_color;
        });
        sigma_instance.refresh();
        is_graph_completely_rendered = false;
    });

    $('#zoom_in').click(function()    { var c = sigma_instance.camera; c.goTo({ratio: c.ratio * 0.5}); });
    $('#zoom_out').click(function()   { var c = sigma_instance.camera; c.goTo({ratio: c.ratio * 1.5}); });
    $('#zoom_reset').click(function() { sigma_instance.camera.goTo({x: 0, y: 0, ratio: 1}); });
});
