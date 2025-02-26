sigma.classes.graph.addMethod('neighbors', function(nodeId) {
    var k,
	neighbors = {},
	index = this.allNeighborsIndex[nodeId] || {};
    
    for (k in index)
	neighbors[k] = this.nodesIndex[k];

    return neighbors;
});

sigma.classes.graph.addMethod('structured_sharings', function(nodeId) {
    var k,
	in_sharing = {},
	out_sharing = {},
	self_sharing = 0,
	index = this.allNeighborsIndex[nodeId] || {},
	in_index = this.inNeighborsIndex[nodeId] || {},
	out_index = this.outNeighborsIndex[nodeId] || {};
    
    for (k in index) {
	if (k == nodeId) self_sharing = get_first_edge(in_index[k]).size;
	else if (k in in_index) in_sharing[k] = get_first_edge(in_index[k]).size;
	else if (k in out_index) out_sharing[k] = get_first_edge(out_index[k]).size;
    }
    
    return {
	self_sharing: self_sharing,
	in_sharing: in_sharing,
	out_sharing: out_sharing
    };
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
	minNodeSize: 0.5,
	maxNodeSize: 30,
	minEdgeSize: 0.1,
	maxEdgeSize: 25,
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
    $('#node_label').html(node.label);
    $('#node_url').html(node.url.replace('https://www.facebook.com', ''));
    if (node.url.startsWith('https://') || node.url.startsWith('http://')) {
	$('#node_url').attr('href', node.url);
    } else {
	$('#node_url').attr('href', "https://www.facebook.com" + node.url);
    }
    if (node.pic) $('#node_picture').html("<img src='" + node.pic + "' />");
    else $('#node_picture').html("");
    $('#node_group').html(get_group(node));
    $('#node_fans_count').html(node.fans);
    $('#node_posts_count').html(node.posts);
    if (node.lost) $('#node_is_lost').show();
    else $('#node_is_lost').hide();
    $('#node_details').hide();
    $('#node_disclaimer').hide();
    $('#node_disclaimer_wiki').hide();
    if (node.group == '-') {
	$('#node_disclaimer').show();
    } else if (node.group == 'wiki') {
	$('#node_disclaimer_wiki').show();
    } else {
	$('#node_details').show();
    }

    let sharings = sigma_instance.graph.structured_sharings(node.id);
    $('#node_mutual_count').html(sharings.self_sharing);
    let in_nodes = get_sharings_list(sharings.in_sharing, 'in');
    $('#node_in_count').html(in_nodes.length);
    $('#node_in_list').html(in_nodes.html);
    let out_nodes = get_sharings_list(sharings.out_sharing, 'out');
    $('#node_out_count').html(out_nodes.length);
    $('#node_out_list').html(out_nodes.html);
    $('#infobar').show();
});

function get_first_edge(d) {
    return d[Object.keys(d)[0]];
}

function get_sharings_list(obj_list, prefix) {
    var neighbors = [];
    var nodes = {};
    var count = {};
    for(var key in obj_list) {
	let n = sigma_instance.graph.nodes(key);
	let c = obj_list[key];
	if (nodes[n.group] == undefined) nodes[n.group] = [];
	nodes[n.group].push({link: '<li>' + get_anchor(n) + ' (' + c + ')</li>', count: c});
	if (count[n.group] == undefined) count[n.group] = 0;
	count[n.group] += c;
    };
    var new_count = [];
    for (var c in count) {
	new_count.push({key: c, val: count[c]});
    }
    new_count.sort(function(a, b) {
	return b.val - a.val;
    });
    let t = 0;
    let html = '';
    for (var c in new_count) {
	let x = new_count[c].key;
	t += new_count[c].val;
	html += '<div class="sharings-separator"><a role="button" data-toggle="collapse" href="#' + prefix + '_sharing_list_' + x + '" aria-expanded="false" aria-controls="' + prefix + '_sharing_list_' + x + '"><strong>' + accessory_data.main_groups[x] + ' (' + count[x] + ')</strong></a></div><ul style="list-style-type: none" class="collapse" id="' + prefix + '_sharing_list_' + x + '">';
	nodes[x].sort(function(a, b) {
	    return b.count - a.count;
	});
	let l = [];
	for (var n in nodes[x]) {
	    l.push(nodes[x][n].link);
	}
	html += l.join('');
	html += '</ul></div>';
    }
    return {length: t, html: html};
}

JSZipUtils.getBinaryContent('data_posts.json.zip', function(err, data) {
    $('#loading_message').html('Caricamento dati');
    if(err) $('#loading_message').html('Errore: ' + err);
    var new_zip = new JSZip();
    new_zip.loadAsync(data).then(function () {
	new_zip.file("data_posts.json")
	    .async("string")
	    .then(function success(content) {
		$('#loading_message').html('Costruzione grafo.');
		sigma_instance.graph.read($.parseJSON(content));
		sigma_instance.graph.nodes().forEach(function(n) {
		    n.size = n.out_deg;
		});
		sigma_instance.graph.nodes().forEach(function(n) {
		    n.color = "rgb(" + n.color + ")";
		    n.originalColor = n.color;
		    n.activityTemperature = n.temp;
		});
		sigma_instance.graph.edges().forEach(function(e) {
		    e.color = sigma_instance.graph.nodes(e.source).color;
		    e.color = e.color.replace('rgb(', '').replace(')', '');
		    e.color = "rgba(" + e.color + ",0.35)";
		    e.originalColor = e.color;
		});
		sigma_instance.refresh();
		$('#loading_message').html('Fatto!');
		$('#loading_modal').modal('hide');

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

function Search(word, result_element) {
    var c = [],
        g = RegExp(word, "i");
    result_element.empty();
    if (2 >= word.length) result_element.html("<i>Cercate termini di almeno 3 lettere.</i>");
    else {
        sigma_instance.graph.nodes().forEach(function (a) {
            g.test(a.label) && c.push(sigma_instance.graph.nodes(a.id));
	});
        a = ["<b>Risultati: </b>", '<ul class="list-unstyled">'];
	if (c.length > 0) {
	    c.sort(node_sort);
            for (var d = 0, h = c.length; d < h; d++) a.push('<li>' + get_anchor(c[d]) + '</li>');
	} else {
            a.push("<li><i>Nessun risultato.</i></li>");
	}
	a.push("</ul>");
	if (c.length > 0) {
	    a.push("<i>");
	    if (c.length == 1) a.push("1 pagina");
	    else a.push(c.length + " pagine");
	    a.push("</i>");
	}
        result_element.html(a.join(""));
    }
    result_element.show();
}

function node_sort(x, y) { return x.label.localeCompare(y.label); }

function get_anchor(node) {
    let s = get_group_symbol_color(node);
    let main_group = s[0];
    let symbol = s[1];
    let color = s[2];
    return '<i class="fa fa-' + symbol + '" aria-hidden="true" style="color: ' + color + '" title="' + accessory_data.main_groups[main_group] + '"></i> <a href="#" class="node-link" data="' + node.id + '">' + node.label + '</a>';
}

function get_group(node) {
    let s = get_group_symbol_color(node);
    let main_group = s[0];
    let symbol = s[1];
    let color = s[2];
    return '<i class="fa fa-' + symbol + '" aria-hidden="true" style="color: ' + color + '"></i> ' + accessory_data.main_groups[main_group];
}

function get_group_symbol_color(node) {
    let symbol = "circle";
    if (['', '-', 'wiki'].indexOf(node.group) >= 0) symbol = symbol + '-o';
    let color = node.originalColor;
    if (['', '-', 'wiki'].indexOf(node.group) >= 0) color = "#ccc";
    return [node.group, symbol, color];
}

function click_node(nodeId) {
    sigma_instance.dispatchEvent('clickStage');
    let n = sigma_instance.graph.nodes(nodeId);
    sigma_instance.dispatchEvent('click', n);
    sigma_instance.dispatchEvent('clickNode', n);
}

function rgb_to_array(s) {
    let a = s.split("(")[1].split(")")[0];
    a = a.split(",");
    let b = a.map(function(x) {
	return parseInt(x).toString(16);
    });
    return b;
}

function rgb_to_hex(s) {
    let b = rgb_to_array(s).map(function(x) {
	return (x.length==1) ? "0" + x : x;
    });
    return "0x" + rgb_to_array(s).join("");
}

function darken_rgb(s) {
    let a = rgb_to_array(s).map(function(x) {
	return (x * 0.85) | 0;
    });
    return "rgb(" + a.join(",") + ")";
}

function build_legend(data) {
    let legend_items = [];
    let group_select_items = [];
    let other = 0;
    group_select_items.push('<option value="" selected="selected"><i class="fa fa-circle-o"></i> Tutta la mappa</option>');
    for ( i=0; i < data['groups'].length; i++ ) {
	let l = data['groups'][i];
	let local_legend_items = [];
	if (l[1] >= 10 ) {
	    legend_items.push('<li style="padding-bottom: .75em;">');
	    if (l[0] == 'xxx') {
		legend_items.push('<i class="fa fa-circle" style="color: ' + l[3][0] + ';"></i> ' + l[2][0] + ', ' + (l[1] + other) + ' pagine');
	    } else {
		legend_items.push('<i class="fa fa-circle" style="color: ' + l[3][0] + ';"></i> ' + l[2][0] + ', ' + l[1] + ' pagine');
		group_select_items.push('<option value="' + l[0] + '"><i class="fa fa-circle" style="color: ' + l[3][0] + ';"></i> ' + l[2][0] + '</option>');
	    }
	    legend_items.push('</li>');
	} else {
	    other = other + l[1];
	}
    }
    $('#legend').html(legend_items.join(''));
    $('#group-select').html(group_select_items.join(''));

    let size_select_items = [];
    for ( i=0; i < data['measures'].length; i++ ) {
	let l = data['measures'][i];
	size_select_items.push('<option value="' + l[0] + '">' + l[1] + '</option>');
    }
    $('#size-select').html(size_select_items.join(''));
    $('#total_pages_count').html(data["total_pages_count"]);
    $('#total_interesting_pages_count').html(data["total_interesting_pages_count"]);
}

$( document ).ready(function() {
    $('#loading_modal').modal('show');
    $('#loading_message').html('Caricamento della pagina.<br>Può prendere del tempo.');
    $.getJSON( "data_accessory_posts.json", function( data ) {
	accessory_data = data;
	build_legend(data);
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
	let toKeep = [];
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
