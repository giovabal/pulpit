var graph;
var provinces;
var locations = {'all': {'max': 0, 'data': {}, 'sum_data': {}, 'color_data': {}}};
var all_groups = [];


function value_to_gradient(value, max) {
    var hue=(60*(1 - value/max)).toString(10);
    return ["hsl(",hue,",100%,50%)"].join("");
}


function set_group_location(group) {
    $('#svg > path').each(function() {
	if ($(this).attr('prov')) {
	    var p = $(this).attr('prov').toUpperCase();
	    var g = group;
	    if (locations[g]['color_data'][p] != undefined) $(this).attr('style', 'fill:' + locations[g]['color_data'][p]);
	    else $(this).attr('style', 'fill:#ddd');
	}
    });
}

function list_location_group(loc) {
    var items = [];
    var old_group = '';
    items.push( "<ul>" );
    $.each( locations, function( group, val ) {
	if (group != 'all' && val['data'][loc]) {
	    if (group != old_group) {
		old_group = group;
		items.push( "</ul>" );
		items.push( "<h4 style='border-top: 2px solid #ddd'; padding-top: .7em; margin-top: 1em;>" + all_groups[group] + " <small>" + val['sum_data'][loc] + "</small></h4>" );
		items.push( "<ul class='list-unstyled'>" );
	    }
	    $.each( val['data'][loc], function( l, v ) {
		items.push( "<li style='margin-bottom: .5em'><a href='" + v['url'] + "'><img src='" + v['pic'] + "' /></a> " + v['label'] + "</li>" );
	    });
	}
    });
    items.push( "</ul>" );
    $("#local_groups").html(items.join(''));
}


$(document).ready(function () {
    JSZipUtils.getBinaryContent('data.json.zip', function(err, data) {
	var new_zip = new JSZip();
	new_zip.loadAsync(data).then(function () {
	    new_zip.file("data.json")
		.async("string")
		.then(function success(content) {
		    graph = $.parseJSON(content);
		    graph['nodes'].sort(function(a,b) {return (a.label > b.label) ? 1 : ((b.label > a.label) ? -1 : 0);} );
		    var exc = ['', '-', 'xfor', 'wiki'];
		    $.each( graph['nodes'], function( i, node ) {
			var p = node['p'];
			var g = node['group'];
			if (p && exc.indexOf(g) < 0) {
			    if (locations['all']['data'][p] == undefined) locations['all']['data'][p] = [];
			    locations['all']['data'][p].push({'url': 'https://facebook.com' + node['url'], 'label': node['label'], 'pic': node['pic']});
			    if (locations[g] == undefined) locations[g] = {'max': 0, 'data': {}, 'sum_data': {}, 'color_data': {}};
			    if (locations[g]['data'][p] == undefined) locations[g]['data'][p] = [];
			    locations[g]['data'][p].push({'url': 'https://facebook.com' + node['url'], 'label': node['label'], 'pic': node['pic']});
			}
		    });
		    
		    $.each( locations, function( key, val ) {
			$.each( val['data'], function( k, v ) {
			    locations[key]['sum_data'][k] = locations[key]['data'][k].length;
			});
			$.each( val['sum_data'], function( k, v ) {
			    locations[key]['max'] = Math.max(locations[key]['max'], v);
			});
			$.each( val['sum_data'], function( k, v ) {
			    locations[key]['color_data'][k] = value_to_gradient(v, locations[key]['max']);
			});
		    });
		    jQuery('#locations_all').load('it_2016.svg', null, function() {
			set_group_location('all');
		    });
		}, function error(err) {
		    alert('Errore: ' + err);
		});
	});
    });
    
	
    $.getJSON( "data_article_accessory.json", function( data ) {
	provinces = data["provinces"];
	var sorted_provinces = [];
	$.each( provinces, function( key, val ) {
	    sorted_provinces[sorted_provinces.length] = {'key': key, 'label': val};
	});
	sorted_provinces.sort(function(a,b) {return (a.label > b.label) ? 1 : ((b.label > a.label) ? -1 : 0);} );

	var items = [];
	items.push( "<option value='all'>---</option>" );
	$.each( sorted_provinces, function( i, p ) {
	    items.push( "<option value='" + p.key + "'>" + p.label + "</option>" );
	});
	$("#location_select").html(items.join(''));
	
	$.each( data["all_groups"], function( key, val ) {
	    all_groups[val[0]] = val[1];
	});

	var items = [];
	items.push( "<option value='all'>Tutti i gruppi</option>" );
	$.each( data["all_groups"], function( key, val ) {
	    items.push( "<option value='" + val[0] + "'>" + val[1] + "</option>" );
	});
	$("#group_select").html(items.join(''));
    });

    $('#location_select').on('change', function() {
	list_location_group($( this ).val());
    });

    $('#group_select').on('change', function() {
	set_group_location($( this ).val());
    });

});
