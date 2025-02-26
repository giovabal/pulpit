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

var accessory_data;
var is_graph_completely_rendered = false;
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

sigma_instance.bind("clickNode", function (x) {
    if (x.data.node !== undefined) node = x.data.node;
    else node = x.data;
    var key = node.url.replace("t.me/", "");
    $('#node_label').html(node.label);
    $('#node_url').html("@" + key);
    $('#node_url').attr('href', 'https://' + node.url);
    if (node.pic) $('#node_picture').html("<img src='" + node.pic + "' style='max-width: 60px;' />");
    else $('#node_picture').html("");
    $('#node_group').html(get_group(node));
    $('#node_in_deg').html(node.in_deg);
    $('#node_out_deg').html(node.out_deg);
    $('#node_followers_count').html(node.fans);
    $('#node_messages_count').html(node.messages_count);
    $('#node_activity_period').html(node.activity_period);
    if (node.is_lost) $('#node_is_lost').show(); else $('#node_is_lost').hide();
    $('#node_details').hide();
    $('#node_disclaimer').hide();
    $('#node_disclaimer_wiki').hide();
    if (node.p) $('#node_location').html('[' + node.p + ']');
    if (node.group == '-') {
	$('#node_disclaimer').show();
    } else if (node.group == 'wiki') {
	$('#node_disclaimer_wiki').show();
    } else {
	$('#node_details').show();
    }

    neighbors = sigma_instance.graph.structured_neighbors(node.id);
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

function get_neighbors_list(obj_list) {
    var neighbors = [];
    var nodes = [];
    for (n in obj_list) neighbors.push(obj_list[n]);
    neighbors = neighbors.sort(node_sort);
    for (n in neighbors) nodes.push('<li>' + get_anchor(neighbors[n]) + '</li>');
    return nodes;
}

function get_data() {
    $('#loading_modal').modal('show');
    $('#loading_message').html('Loading...<br>Please wait.');

    $.getJSON( "data.json", function( data ) {
	$('#loading_message').html('Graph building.');
	sigma_instance.graph.read(data);
	sigma_instance.graph.nodes().forEach(function(n) {
	    n.size = n.in_deg;
	    if (n.fans == 0) n.tac_on_fans = 0;
	    else n.tac_on_fans = n.tac / n.fans;
	});
	sigma_instance.graph.nodes().forEach(function(n) {
	    n.color = "rgb(" + n.color + ")";
	    n.originalColor = n.color;
	    n.activityTemperature = n.temp;
	});
	sigma_instance.graph.edges().forEach(function(e) {
	    e.color = "rgba(" + e.color + ",0.25)";
	    e.originalColor = e.color;
	});
	sigma_instance.refresh();
	$('#loading_message').html('Done!');
	
	sigma_instance.bind('clickNode', function(e) {
	    if (e.data.node !== undefined) node = e.data.node;
	    else node = e.data;
	    var nodeId = node.id,
		toKeep = sigma_instance.graph.neighbors(nodeId);
	    toKeep[nodeId] = node;

	    sigma_instance.graph.nodes().forEach(function(n) {
		if (toKeep[n.id])
		    n.color = n.originalColor;
		else
		    n.color = settings.fade_color;
	    });

	    sigma_instance.graph.edges().forEach(function(e) {
		if (toKeep[e.source] && toKeep[e.target])
		    e.color = e.originalColor;
		else
		    e.color = settings.fade_color;
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
    $('#loading_modal').modal('hide');
};

function Search(word, result_element) {
    var c = [],
        g = RegExp(word, "i");
    result_element.empty();
    if (2 >= word.length) result_element.html("<i>Search for terms of at least 3 characters.</i>");
    else {
        sigma_instance.graph.nodes().forEach(function (a) {
            g.test(a.label) && c.push(sigma_instance.graph.nodes(a.id));
	});
        a = ["<b>Results: </b>", '<ul class="list-unstyled">'];
	if (c.length > 0) {
	    c.sort(node_sort);
            for (var d = 0, h = c.length; d < h; d++) a.push('<li>' + get_anchor(c[d]) + '</li>');
	} else {
            a.push("<li><i>No results.</i></li>");
	}
	a.push("</ul>");
	if (c.length > 0) {
	    a.push("<i>");
	    if (c.length == 1) a.push("1 canale");
	    else a.push(c.length + " canali");
	    a.push("</i>");
	}
        result_element.html(a.join(""));
    }
    result_element.show();
}

function node_sort(x, y) {
    return x.label.localeCompare(y.label);
}

function get_anchor(node) {
    var s = get_group_symbol_color(node);
    main_group = s[0];
    symbol = s[1];
    color = s[2];
    return '<i class="fa fa-' + symbol + '" aria-hidden="true" style="color: ' + color + '" title="' + accessory_data.main_groups[main_group] + '"></i> <a href="#" class="node-link" data="' + node.id + '">' + node.label + '</a>';
}

function get_group(node) {
    var s = get_group_symbol_color(node);
    main_group = s[0];
    symbol = s[1];
    color = s[2];
    return '<i class="fa fa-' + symbol + '" aria-hidden="true" style="color: ' + color + '"></i> ' + accessory_data.main_groups[main_group];
}

function get_group_symbol_color(node) {
    var symbol = "circle";
    if (['', '-', 'wiki'].indexOf(node.group) >= 0) symbol = symbol + '-o';
    var color = node.originalColor;
    if (['', '-', 'wiki'].indexOf(node.group) >= 0) color = "#ccc";
    main_group = node.group;
    if (main_group.indexOf('-') >= 0) main_group = main_group.substring(0, main_group.indexOf('-'));
    return [main_group, symbol, color];
}

function click_node(nodeId) {
    sigma_instance.dispatchEvent('clickStage');
    n = sigma_instance.graph.nodes(nodeId);
    sigma_instance.dispatchEvent('click', n);
    sigma_instance.dispatchEvent('clickNode', n);
}

function rgb_to_array(s) {
    var a = s.split("(")[1].split(")")[0];
    a = a.split(",");
    var b = a.map(function(x) {
	return parseInt(x).toString(16);
    });
    return b;
}

function rgb_to_hex(s) {
    var b = rgb_to_array(s).map(function(x) {
	return (x.length==1) ? "0" + x : x;
    });
    return "0x" + rgb_to_array(s).join("");
}

function darken_rgb(s) {
    var a = rgb_to_array(s).map(function(x) {
	return (x * 0.85) | 0;
    });
    return "rgb(" + a.join(",") + ")";
}

function build_legend(data) {
    var legend_items = [];
    var group_select_items = [];
    group_select_items.push('<option value="" selected="selected"><i class="fa fa-circle-o"></i> All the map</option>');
    for ( i=0; i < data['groups'].length; i++ ) {
	var l = data['groups'][i];
	var local_legend_items = [];
	legend_items.push('<li style="padding-bottom: .75em;">');
	legend_items.push('<i class="fa fa-circle" style="color: ' + l[3] + ';"></i> ' + l[2] + ', ' + l[1] + ' channels');
	group_select_items.push('<option value="' + l[0] + '"><i class="fa fa-circle" style="color: ' + l[3] + ';"></i> ' + l[2] + '</option>');
	legend_items.push('</li>');
    }
    $('#legend').html(legend_items.join(''));
    $('#group-select').html(group_select_items.join(''));

    var size_select_items = [];
    for ( i=0; i < data['measures'].length; i++ ) {
	var l = data['measures'][i];
	size_select_items.push('<option value="' + l[0] + '">' + l[1] + '</option>');
    }
    $('#size-select').html(size_select_items.join(''));
    $('#total_pages_count').html(data["total_pages_count"]);
    $('#total_interesting_pages_count').html(data["total_interesting_pages_count"]);
}

$( document ).ready(function() {
    get_data();
    $.getJSON( "data_accessory.json", function( data ) {
	accessory_data = data; 
	build_legend(accessory_data);
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
	v = $( this ).val();
	sigma_instance.graph.nodes().forEach(function(n) {
            n.size = n[v];
	});
	sigma_instance.refresh();
    });

    $('#group-select').on('change', function() {
	v = $( this ).val();
	if (v == "") {
            sigma_instance.graph.nodes().forEach(function(n) {
		n.color = n.originalColor;
	    });

            sigma_instance.graph.edges().forEach(function(e) {
		e.color = e.originalColor;
            });

            sigma_instance.refresh();
	    return;
	}
	var toKeep = [];
        sigma_instance.graph.nodes().forEach(function(n) {
	    if (typeof n.group !== 'undefined') {
		if(n.group == v || n.group.startsWith(v + '-')) {
		    toKeep = toKeep.concat([n.id, ]);
		    a = sigma_instance.graph.neighbors(n.id);
		    for (var i = 0; i < a.lenght; i++) {
			toKeep = toKeep.concat([a[i].id, ]);
		    }
		}
	    }
        });

        sigma_instance.graph.nodes().forEach(function(n) {
	    if (toKeep.indexOf(n.id) >= 0)
		n.color = n.originalColor;
	    else
		n.color = settings.fade_color;
        });

        sigma_instance.graph.edges().forEach(function(e) {
	    if (toKeep.indexOf(e.source.id) >= 0 && toKeep.indexOf(e.target.id) >= 0)
		e.color = e.originalColor;
	    else
		e.color = settings.fade_color;
        });

        sigma_instance.refresh();
    });

    $('#color-select').on('change', function() {
	v = $( this ).val();
	if (v == "activity_index") {
            sigma_instance.graph.nodes().forEach(function(n) {
		n.color = n.activityTemperature;
            });

            sigma_instance.graph.edges().forEach(function(e) {
		e.color = settings.fade_color;
            });
	} else {
            sigma_instance.graph.nodes().forEach(function(n) {
		n.color = n.originalColor;
	    });

            sigma_instance.graph.edges().forEach(function(e) {
		e.color = e.originalColor;
            });
	}
        sigma_instance.refresh();
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
