var graph;
var all_groups = [];


function value_to_gradient(value, max) {
    var hue=(60*(1 - value/max)).toString(10);
    return ["hsl(",hue,",100%,50%)"].join("");
}


$(document).ready(function () {
    $.getJSON( "data.json", function( data ) {
	graph = $.parseJSON(data);
	graph['nodes'].sort(function(a,b) {
	    return (a.label > b.label) ? 1 : ((b.label > a.label) ? -1 : 0);
	});
	$.each( graph['nodes'], function( i, node ) {
	    var p = node['p'];
	    var g = node['group'];
	});
    });

    $.getJSON( "graph_data.json", function( data ) {
	var x = [];
	var y = [];
	var size = [];
	var color = [];
	var text = [];
	$.each( data['data'], function( key, val ) {
	    if (val['pages'] > 1) {
		x.push(val['avg_fans']);
		y.push(val['avg_links']);
		size.push(20);
		color.push(val['color']);
		text.push(val['label']);
	    }
	});
	
	var trace1 = {
	    x: x,
	    y: y,
	    text: text,
	    mode: 'markers',
	    marker: {
		color: color,
		size: size
	    }
	};

	var trace2 = {
	    x: [0, Math.max.apply(null, x)],
	    y: [data['regression'][1], Math.max.apply(null, x) * data['regression'][0] + data['regression'][1]],
	    mode: 'lines',
	    line: {
		color: 'rgb(55, 128, 191, .5)',
		width: 1
	    }
	};

	var data = [trace1, trace2];

	var layout = {
	    title: 'Pages & link',
	    showlegend: false,
	    xaxis: {title: 'Avg fan count'},
	    yaxis: {title: 'Avg link count'}
	};
	Plotly.plot('scatter_graph_all', data, layout, {showLink: false});
    });

    $('#group_select').on('change', function() {
	set_group_location($( this ).val());
    });

});
