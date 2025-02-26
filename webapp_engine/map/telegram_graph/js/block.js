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
	if (k in in_index) {
	    in_neighbors[k] = this.nodesIndex[k];
	    in_neighbors[k].edge_weight = this.nodesIndex[k];
	} else if (k in out_index) out_neighbors[k] = this.nodesIndex[k];
    }
    
    return {
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

function get_neighbors_list(x, obj_list) {
    var neighbors = [];
    var nodes = [];
    for (n in obj_list) neighbors.push(obj_list[n]);
    neighbors = neighbors.sort(node_sort);
    for (n in neighbors) {
	var e = sigma_instance.graph.edgesIndex(x.group + '-' + neighbors[n].group);
	nodes.push('<li>' + get_anchor(neighbors[n]) + ', ' + e.size + ' link</li>');
    }
    return nodes;
}

var accessory_data;
var is_graph_completely_rendered = false;
var settings = {
    container: 'sigma-canvas',
    container_background_color: "rgba(17, 34, 51, 1)",
    fade_color: "rgba(27, 44, 61, .75)"
}

$('#' + settings.container).css('background-color', settings.container_background_color)

var sigma_instance = new sigma({
    renderer: {
	container: settings.container,
	type: 'canvas'  //Modernizr.webgl ? 'webgl' : 'canvas'
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
	minNodeSize: 5,
	maxNodeSize: 50,
	minEdgeSize: 1,
	maxEdgeSize: 50,
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
	drawEdgeLabels: false,
    }
});

sigma_instance.bind("clickNode", function (x) {
    if (x.data.node !== undefined) node = x.data.node;
    else node = x.data;
    $('#node_label').html(node.label);
    if (node.pic) $('#node_picture').html("<img src='" + node.pic + "' />");
    else $('#node_picture').html("");

    neighbors = sigma_instance.graph.structured_neighbors(node.id);
    var in_nodes = get_neighbors_list(node, neighbors.in_neighbors);
    $('#node_in_count').html(in_nodes.length);
    $('#node_in_list').html(in_nodes.join(''));
    var out_nodes = get_neighbors_list(node, neighbors.out_neighbors);
    $('#node_out_count').html(out_nodes.length);
    $('#node_out_list').html(out_nodes.join(''));
    $('#infobar').show();
});

JSZipUtils.getBinaryContent('block_data.json.zip', function(err, data) {
    $('#loading_message').html('Caricamento dati');
    if(err) $('#loading_message').html('Errore: ' + err);
    var new_zip = new JSZip();
    new_zip.loadAsync(data).then(function () {
	new_zip.file("block_data.json")
	    .async("string")
	    .then(function success(content) {
		$('#loading_message').html('Analisi dati.');
		sigma_instance.graph.read($.parseJSON(content));
		$('#loading_message').html('Fatto!');
		$('#loading_modal').modal('hide');
		sigma_instance.graph.nodes().forEach(function(n) {
		    n.size = n.pages;
		});
		sigma_instance.refresh();
		sigma_instance.graph.nodes().forEach(function(n) {
		    n.originalColor = n.color;
		    n.activityTemperature = n.temp;
		});
		sigma_instance.graph.edges().forEach(function(e) {
		    e.originalColor = e.color;
		});

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
	    }, function error(err) {
		$('#loading_message').html('Errore: ' + err);
	    }
		 );
    });
});

function node_sort(x, y) { return x.label.localeCompare(y.label); }

function get_anchor(node) {
    var s = get_group_symbol_color(node);
    main_group = s[0];
    symbol = s[1];
    color = s[2];
    return '<i class="fa fa-' + symbol + '" aria-hidden="true" style="color: ' + color + '" title="' + accessory_data.main_groups[main_group] + '"></i> <a href="#" class="node-link" data="' + node.id + '">' + node.label + '</a>'
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
    main_group = node.id
    if (main_group.indexOf('-') >= 0) main_group = main_group.substring(0, main_group.indexOf('-'));
    return [main_group, symbol, color];
}

function click_node(nodeId) {
    sigma_instance.dispatchEvent('clickStage');
    n = sigma_instance.graph.nodes(nodeId);
    sigma_instance.dispatchEvent('click', n);
    sigma_instance.dispatchEvent('clickNode', n);
}

function build_legend(data) {
    var legend_items = [];
    var group_select_items = [];
    group_select_items.push('<option value="" selected="selected"><i class="fa fa-circle-o"></i> Tutta la mappa</option>');
    for ( i=0; i < data['groups'].length; i++ ) {
	var l = data['groups'][i];
	var local_legend_items = [];
	legend_items.push('<li style="padding-bottom: .75em;">');
	legend_items.push('<i class="fa fa-circle" style="color: ' + l[3][0] + ';"></i> ' + l[2][0] + ', ' + l[1] + ' pagine');
	group_select_items.push('<option value="' + l[0] + '"><i class="fa fa-circle" style="color: ' + l[3][0] + ';"></i> ' + l[2][0] + '</option>');
	if (l[2].length > 1) {
	    legend_items.push('<ul class="list-unstyled" style="padding-left: 1em;">');
	    for (j=1; j < l[2].length; j++ ) {
		legend_items.push('<li>');
		legend_items.push('<i class="fa fa-circle" style="color: ' + l[3][j] + ';"></i> ' + l[2][j]);
		legend_items.push('</li>');
	    }		
	    legend_items.push('</ul>');
	}
	legend_items.push('</li>');
    }
    $('#legend').html(legend_items.join(''));
    $('#group-select').html(group_select_items.join(''));
    $('#total_pages_count').html(data["total_pages_count"]);
    $('#total_interesting_pages_count').html(data["total_interesting_pages_count"]);
}

$( document ).ready(function() {
    $('#loading_modal').modal('show');
    $('#loading_message').html('Caricamento della pagina,<br>può prendere del tempo su connessioni lente');
    $.getJSON( "data_accessory.json", function( data ) {
	accessory_data = data; 
	build_legend(accessory_data);
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
