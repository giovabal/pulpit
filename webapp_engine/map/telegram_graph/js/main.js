sigma.classes.graph.addMethod('neighbors', function(nodeId) {
    var k,
	    neighbors = {},
	    index = this.allNeighborsIndex[nodeId] || {};

    for (k in index)
	    neighbors[k] = this.nodesIndex[k];

    return neighbors;
});

sigma.classes.graph.addMethod('structured_neighbors', function(nodeId) {
    var k,
	    in_neighbors = [],
	    out_neighbors = [],
	    mutual_neighbors = [],
	    index = this.allNeighborsIndex[nodeId] || {},
	    in_index = this.inNeighborsIndex[nodeId] || {},
	    out_index = this.outNeighborsIndex[nodeId] || {};

    for (k in index) {
	    if (k in in_index && k in out_index) mutual_neighbors[k] = this.nodesIndex[k];
	    else if (k in in_index) in_neighbors[k] = this.nodesIndex[k];
	    else if (k in out_index) out_neighbors[k] = this.nodesIndex[k];
    }

    return {
	    mutual_neighbors: mutual_neighbors,
	    in_neighbors: in_neighbors,
	    out_neighbors: out_neighbors
    };
});

sigma.classes.graph.addMethod('out_neighbors', function(nodeId) {
    var k,
	    neighbors = {},
	    index = this.outNeighborsIndex[nodeId] || {};

    for (k in index)
	    neighbors[k] = this.nodesIndex[k];

    return neighbors;
});

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------

var accessory_data  = null;
var active_strategy = null;
var community_color_maps = {};   // { strategyKey: { communityLabel: hexColor } }
var is_graph_completely_rendered = false;
var graph_loaded     = false;
var accessory_loaded = false;

var settings = {
    container: 'sigma-canvas',
    container_background_color: "rgba(17, 34, 51, 1)",
    fade_color: "rgba(27, 44, 61, .75)"
};

$('#' + settings.container).css('background-color', settings.container_background_color);

var sigma_instance = new sigma({
    renderer: {
	    container: settings.container,
	    type: 'canvas'  // Modernizr.webgl ? 'webgl' : 'canvas'
    },
    settings: {
	    autoRescale: true,
	    mouseEnabled: true,
	    touchEnabled: true,
	    nodesPowRatio: 1,
	    edgesPowRatio: 1,
	    defaultEdgeColor: '#484848',
	    defaultNodeColor: '#333',
	    defaultEdgeType: 'curve',
	    edgeColor: 'default',
	    minNodeSize: 1,
	    maxNodeSize: 10,
	    minEdgeSize: 0.2,
	    maxEdgeSize: 0.5,
	    defaultLabelSize: 12,
	    defaultLabelColor: '#FFFFFF',
	    activeFontStyle: "bold",
	    font: "sans-serif",
	    defaultLabelBGColor: "#ddd",
	    zoomMin: 0.03125,
	    batchEdgesDrawing: true,
	    hideEdgesOnMove: true,
	    labelThreshold: 15,
	    hoverFontStyle: "bold",
	    drawEdgeLabels: false
    }
});

// ---------------------------------------------------------------------------
// Infobar node-click (registered early, fires on every click)
// ---------------------------------------------------------------------------

sigma_instance.bind("clickNode", function (x) {
    var node;
    if (x.data.node !== undefined) node = x.data.node;
    else node = x.data;
    var key = node.url ? node.url.replace("https://t.me/", "") : "";
    $('#node_label').html(node.label);
    $('#node_url').html("@" + key);
    $('#node_url').attr('href', node.url);
    if (node.pic) $('#node_picture').html("<img src='" + node.pic + "' style='max-width: 60px;' />");
    else $('#node_picture').html("");
    $('#node_group').html(get_group(node));
    $('#node_in_deg').html(node.in_deg);
    $('#node_out_deg').html(node.out_deg);
    $('#node_followers_count').html(node.fans);
    $('#node_pagerank').html(node.pagerank ? node.pagerank.toFixed(4) : 'N/A');
    $('#node_messages_count').html(node.messages_count);
    $('#node_activity_period').html(node.activity_period);
    if (node.is_lost) $('#node_is_lost').show(); else $('#node_is_lost').hide();
    $('#node_details').hide();
    $('#node_disclaimer').hide();
    $('#node_disclaimer_wiki').hide();
    $('#node_details').show();

    var neighbors = sigma_instance.graph.structured_neighbors(node.id);
    var mutual_nodes = get_neighbors_list(neighbors.mutual_neighbors);
    $('#node_mutual_count').html(mutual_nodes.length);
    $('#node_mutual_list').html(mutual_nodes.join(''));
    var in_nodes = get_neighbors_list(neighbors.in_neighbors);
    $('#node_in_count').html(in_nodes.length);
    $('#node_in_list').html(in_nodes.join(''));
    var out_nodes = get_neighbors_list(neighbors.out_neighbors);
    $('#node_out_count').html(out_nodes.length);
    $('#node_out_list').html(out_nodes.join(''));
    $('#infobar').show();
});

// ---------------------------------------------------------------------------
// Neighbor list helpers
// ---------------------------------------------------------------------------

function get_neighbors_list(obj_list) {
    var neighbors = [];
    var nodes = [];
    for (var n in obj_list) neighbors.push(obj_list[n]);
    neighbors = neighbors.sort(node_sort);
    for (var i = 0; i < neighbors.length; i++) nodes.push('<li>' + get_anchor(neighbors[i]) + '</li>');
    return nodes;
}

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
        var label = node.communities[strategy] || '';
        var colorMap = community_color_maps[strategy] || {};
        var color = (label && colorMap[label]) ? colorMap[label] : '#ccc';
        var strategyName = strategy.charAt(0).toUpperCase() + strategy.slice(1);
        parts.push('<i class="fa fa-circle" aria-hidden="true" style="color: ' + color + '"></i> <b>' + strategyName + ':</b> ' + label);
    }
    return parts.join('<br>');
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Community coloring
// ---------------------------------------------------------------------------

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
        var rgb = (label && colorMap[label]) ? hex_to_rgb_parts(colorMap[label]) : [204, 204, 204];
        n.originalColor = 'rgb(' + rgb.join(',') + ')';
        n.color = n.originalColor;
    });
    sigma_instance.graph.edges().forEach(function(e) {
        var src = sigma_instance.graph.nodes(e.source);
        var tgt = sigma_instance.graph.nodes(e.target);
        var avg = avg_and_darken(rgb_str_to_parts(src.originalColor), rgb_str_to_parts(tgt.originalColor), 0.75);
        e.originalColor = 'rgba(' + avg.join(',') + ',0.25)';
        e.color = e.originalColor;
    });
    sigma_instance.refresh();
    is_graph_completely_rendered = true;
}

function maybe_apply_initial_colors() {
    if (graph_loaded && accessory_loaded && active_strategy) {
        apply_strategy_colors(active_strategy);
    }
}

// ---------------------------------------------------------------------------
// UI builders
// ---------------------------------------------------------------------------

function build_strategy_selector(communities) {
    var strategies = Object.keys(communities);
    if (strategies.length <= 1) {
        $('#community-strategy-group').hide();
        return;
    }
    var items = strategies.map(function(s) {
        return '<option value="' + s + '">' + s.charAt(0).toUpperCase() + s.slice(1) + '</option>';
    });
    $('#community-strategy-select').html(items.join(''));
    $('#community-strategy-group').show();
}

function build_legend(strategyData) {
    var legend_items = [];
    var group_select_items = [];
    group_select_items.push('<option value="" selected="selected">All nodes</option>');
    var groups = strategyData.groups;
    for (var i = 0; i < groups.length; i++) {
        var l = groups[i]; // [id, count, label, hexColor]
        legend_items.push('<li style="padding-bottom: .75em;">');
        legend_items.push('<i class="fa fa-circle" style="color: ' + l[3] + ';"></i> ' + l[2] + ', ' + l[1] + ' channels');
        legend_items.push('</li>');
        group_select_items.push('<option value="' + l[2] + '">' + l[2] + '</option>');
    }
    $('#legend').html(legend_items.join(''));
    $('#group-select').html(group_select_items.join(''));
}

// ---------------------------------------------------------------------------
// Node sizing
// ---------------------------------------------------------------------------

function apply_node_size(metric) {
    var nodes = sigma_instance.graph.nodes();
    if (metric === 'pagerank') {
        var vals = nodes.map(function(n) { return n.pagerank || 0; });
        var minV = Math.min.apply(null, vals);
        var maxV = Math.max.apply(null, vals);
        var range = maxV - minV || 1;
        nodes.forEach(function(n) {
            n.size = 0.1 + ((n.pagerank || 0) - minV) / range * 9.9;
        });
    } else {
        nodes.forEach(function(n) {
            n.size = (n[metric] || 0) + 1;
        });
    }
    sigma_instance.refresh();
}

// ---------------------------------------------------------------------------
// Graph loading
// ---------------------------------------------------------------------------

function get_data() {
    $.getJSON("data.json", function(data) {
	    $('#loading_message').html('Building graph…');
	    sigma_instance.graph.read(data);
	    sigma_instance.graph.nodes().forEach(function(n) {
	        n.size = (n.in_deg || 0) + 1;
	    });
	    sigma_instance.graph.nodes().forEach(function(n) {
	        n.color = "rgb(" + n.color + ")";
	        n.originalColor = n.color;
	    });
	    sigma_instance.graph.edges().forEach(function(e) {
	        e.color = e.color ? "rgba(" + e.color + ",0.25)" : "rgba(72,72,72,0.25)";
	        e.originalColor = e.color;
	    });
	    sigma_instance.refresh();
	    $('#loading_message').html('Done!');
	    $('#loading_modal').modal('hide');

	    graph_loaded = true;
	    maybe_apply_initial_colors();

	    sigma_instance.bind('clickNode', function(e) {
	        var node;
	        if (e.data.node !== undefined) node = e.data.node;
	        else node = e.data;
	        var nodeId = node.id,
		        toKeep = sigma_instance.graph.neighbors(nodeId);
	        toKeep[nodeId] = node;

	        sigma_instance.graph.nodes().forEach(function(n) {
		        n.color = toKeep[n.id] ? n.originalColor : settings.fade_color;
	        });

	        sigma_instance.graph.edges().forEach(function(e2) {
		        e2.color = (toKeep[e2.source] && toKeep[e2.target]) ? e2.originalColor : settings.fade_color;
	        });

	        sigma_instance.refresh();
	        is_graph_completely_rendered = false;
	    });

	    sigma_instance.bind('clickStage', function(e) {
	        if (!is_graph_completely_rendered) {
		        sigma_instance.graph.nodes().forEach(function(n) {
		            n.color = n.originalColor;
		        });
		        sigma_instance.graph.edges().forEach(function(e) {
		            e.color = e.originalColor;
		        });
		        sigma_instance.refresh();
		        is_graph_completely_rendered = true;
	        }
	    });
    });
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

function Search(word, result_element) {
    var c = [],
        g = RegExp(word, "i");
    result_element.empty();
    if (2 >= word.length) result_element.html("<i>Search for terms of at least 3 characters.</i>");
    else {
        sigma_instance.graph.nodes().forEach(function (a) {
            g.test(a.label) && c.push(sigma_instance.graph.nodes(a.id));
	    });
        var a = ["<b>Results: </b>", '<ul class="list-unstyled">'];
	    if (c.length > 0) {
	        c.sort(node_sort);
            for (var d = 0, h = c.length; d < h; d++) a.push('<li>' + get_anchor(c[d]) + '</li>');
	    } else {
            a.push("<li><i>No results.</i></li>");
	    }
	    a.push("</ul>");
	    if (c.length > 0) {
	        a.push("<i>");
	        if (c.length == 1) a.push("1 channel");
	        else a.push(c.length + " channels");
	        a.push("</i>");
	    }
        result_element.html(a.join(""));
    }
    result_element.show();
}

function click_node(nodeId) {
    sigma_instance.dispatchEvent('clickStage');
    var n = sigma_instance.graph.nodes(nodeId);
    if (n) sigma_instance.dispatchEvent('clickNode', { data: n });
}

// ---------------------------------------------------------------------------
// Document ready
// ---------------------------------------------------------------------------

$( document ).ready(function() {
    $('#loading_modal').modal('show');
    $('#loading_message').html('Loading…<br>Please wait.');

    get_data();

    $.getJSON("data_accessory.json", function(data) {
	    accessory_data       = data;
	    community_color_maps = build_community_color_maps(data.communities);
	    var strategies        = Object.keys(data.communities);
	    active_strategy       = strategies[0] || null;

	    build_strategy_selector(data.communities);
	    if (active_strategy) build_legend(data.communities[active_strategy]);

	    var size_items = data.measures.map(function(m) {
	        return '<option value="' + m[0] + '">' + m[1] + '</option>';
	    });
	    $('#size-select').html(size_items.join(''));
	    $('#total_pages_count').html(data.total_pages_count);

	    accessory_loaded = true;
	    maybe_apply_initial_colors();
    });

    // Community strategy picker
    $('#community-strategy-select').on('change', function() {
        active_strategy = $(this).val();
        if (accessory_data) build_legend(accessory_data.communities[active_strategy]);
        if (graph_loaded) {
            apply_strategy_colors(active_strategy);
            $('#group-select').val('');
        }
    });

    $('#search_input').val('');

    $('#search_modal').on("shown.bs.modal", function() {
	    $('#search_input').focus();
    });

    $('#search').submit(function() {
        Search($('#search_input').val(), $('#results'));
        return false;
    });

    $('.infobar-toggle').on('click', function () {
        $('#infobar').toggle();
        sigma_instance.dispatchEvent('clickStage');
    });

    $('body').on('click', 'a.node-link', function (n) {
        var id = $(this).attr('data');
        click_node(id);
        return false;
    });

    $('#size-select').on('change', function() {
	    apply_node_size($(this).val());
    });

    $('#group-select').on('change', function() {
	    var v = $( this ).val();
	    if (v === "") {
            sigma_instance.graph.nodes().forEach(function(n) {
		        n.color = n.originalColor;
	        });
            sigma_instance.graph.edges().forEach(function(e) {
		        e.color = e.originalColor;
            });
            sigma_instance.refresh();
            is_graph_completely_rendered = true;
	        return;
	    }
	    var toKeep = [];
        sigma_instance.graph.nodes().forEach(function(n) {
	        var label = n.communities && active_strategy ? n.communities[active_strategy] : '';
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

    $("#zoom_in").click(function () {
	    var c = sigma_instance.camera;
	    c.goTo({'ratio': c.ratio * 0.5});
    });
    $("#zoom_out").click(function () {
	    var c = sigma_instance.camera;
	    c.goTo({'ratio': c.ratio * 1.5});
    });
    $("#zoom_reset").click(function () {
	    var c = sigma_instance.camera;
	    c.goTo({'x': 0, 'y': 0, 'ratio': 1});
    });
});
