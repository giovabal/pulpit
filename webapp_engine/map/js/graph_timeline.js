import { Sigma } from 'sigma';
import Graph from 'graphology';
import EdgeCurveProgram from '@sigma/edge-curve';
import { drawDiscNodeLabel } from 'sigma/rendering';

// =============================================================================
// Helpers
// =============================================================================

function el(id) { return document.getElementById(id); }

function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function parseColor(raw) {
    // raw may be "r,g,b" (from channels.json) or "#rrggbb" / "#rgb" (from communities.json)
    if (!raw) return [128, 128, 128];
    if (raw.startsWith('#')) {
        var h = raw.slice(1);
        if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
        return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
    }
    var m = raw.match(/(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    return m ? [+m[1], +m[2], +m[3]] : [128, 128, 128];
}

function rgbStr(arr) { return 'rgb(' + arr[0] + ',' + arr[1] + ',' + arr[2] + ')'; }

function lerpColor(colA, colB, t) {
    var a = parseColor(colA), b = parseColor(colB);
    return rgbStr([
        Math.round(a[0] + (b[0] - a[0]) * t),
        Math.round(a[1] + (b[1] - a[1]) * t),
        Math.round(a[2] + (b[2] - a[2]) * t),
    ]);
}

// =============================================================================
// Constants
// =============================================================================

var INACTIVE_COLOR = '#3a4050';
var INACTIVE_SIZE  = 1.8;
var BASE_DIR       = window.DATA_DIR || 'data/';

var SPEEDS = {
    slow:   { hold: 3000, tween: 2200 },
    normal: { hold: 1400, tween: 1100 },
    fast:   { hold: 350,  tween: 650  },
};
var currentSpeed = 'normal';

// =============================================================================
// State
// =============================================================================

var loading_modal_bs  = null;
var graph             = new Graph({ type: 'directed', multi: false });
var sigma_instance    = null;
var community_color_maps = {};
var active_strategy   = null;

var allYears      = [];
var yearFrames    = {};           // year → { positions: {id:{x,y}}, activeSet: Set<id> }
var mainPositions = {};           // id → {x, y}
var nodeBaseColor = {};           // id → rgb string
var nodeSizeRange = { min: 0, range: 1 };
var nodeDegrees   = {};           // id → in_deg

var playState    = 'stopped';
var currentIdx   = 0;
var tweenFrom    = 0;
var tweenTo      = 0;
var tweenT       = 0;
var phase        = 'hold';
var phaseElapsed = 0;
var lastTs       = null;
var rafId        = null;
var isInfobarOpen = false;

// =============================================================================
// Sigma setup (inside DOMContentLoaded to ensure canvas is ready)
// =============================================================================

function drawDarkNodeHover(context, data, settings) {
    var size = settings.labelSize, font = settings.labelFont, weight = settings.labelWeight;
    context.font = weight + ' ' + size + 'px ' + font;
    context.fillStyle = '#111';
    context.shadowOffsetX = 0; context.shadowOffsetY = 0;
    context.shadowBlur = 8; context.shadowColor = '#000';
    var PADDING = 2;
    if (typeof data.label === 'string') {
        var textWidth = context.measureText(data.label).width;
        var boxWidth  = Math.round(textWidth + 5);
        var boxHeight = Math.round(size + 2 * PADDING);
        var radius    = Math.max(data.size, size / 2) + PADDING;
        var angleRad  = Math.asin(boxHeight / 2 / radius);
        var xDelta    = Math.sqrt(Math.abs(radius * radius - (boxHeight / 2) * (boxHeight / 2)));
        context.beginPath();
        context.moveTo(data.x + xDelta, data.y + boxHeight / 2);
        context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
        context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
        context.lineTo(data.x + xDelta, data.y - boxHeight / 2);
        context.arc(data.x, data.y, radius, angleRad, -angleRad);
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

function initSigma() {
    el('sigma-canvas').style.backgroundColor = 'rgba(17, 34, 51, 1)';
    sigma_instance = new Sigma(graph, el('sigma-canvas'), {
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
        defaultDrawNodeHover:       drawDarkNodeHover,
    });
    sigma_instance.on('beforeRender', function() {
        var gl = sigma_instance.webGLContexts && sigma_instance.webGLContexts.edges;
        if (gl) gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    });
    sigma_instance.on('clickNode',  function(ev) { showNodeInfo(ev.node); });
    sigma_instance.on('clickStage', function()   { if (isInfobarOpen) closeInfobar(); });
}

// =============================================================================
// Frame helpers
// =============================================================================

function getNodePos(nodeId, yearIdx) {
    if (yearIdx >= 0 && yearIdx < allYears.length) {
        var frame = yearFrames[allYears[yearIdx]];
        if (frame && frame.positions[nodeId]) return frame.positions[nodeId];
    }
    return mainPositions[nodeId] || { x: 0, y: 0 };
}

function getNodeColor(nodeId, yearIdx) {
    if (yearIdx < 0 || yearIdx >= allYears.length) return INACTIVE_COLOR;
    var frame = yearFrames[allYears[yearIdx]];
    return (frame && frame.activeSet.has(nodeId)) ? (nodeBaseColor[nodeId] || INACTIVE_COLOR) : INACTIVE_COLOR;
}

function getNodeSize(nodeId, yearIdx) {
    if (yearIdx < 0 || yearIdx >= allYears.length) return INACTIVE_SIZE;
    var frame = yearFrames[allYears[yearIdx]];
    if (!frame || !frame.activeSet.has(nodeId)) return INACTIVE_SIZE;
    var deg = nodeDegrees[nodeId] || 0;
    return 1.5 + (deg - nodeSizeRange.min) / nodeSizeRange.range * 13.5;
}

function activeSetForIdx(yearIdx) {
    if (yearIdx < 0 || yearIdx >= allYears.length) return new Set();
    var frame = yearFrames[allYears[yearIdx]];
    return frame ? frame.activeSet : new Set();
}

function applyFrame(yearIdx) {
    var active = activeSetForIdx(yearIdx);
    graph.nodes().forEach(function(id) {
        var pos   = getNodePos(id, yearIdx);
        var color = getNodeColor(id, yearIdx);
        var size  = getNodeSize(id, yearIdx);
        graph.setNodeAttribute(id, 'x', pos.x);
        graph.setNodeAttribute(id, 'y', pos.y);
        graph.setNodeAttribute(id, 'color', color);
        graph.setNodeAttribute(id, 'originalColor', color);
        graph.setNodeAttribute(id, 'size', size);
    });
    graph.edges().forEach(function(edgeId) {
        var src = graph.source(edgeId), tgt = graph.target(edgeId);
        graph.setEdgeAttribute(edgeId, 'hidden', !(active.has(src) && active.has(tgt)));
    });
    sigma_instance.refresh();
}

function applyTween(fromIdx, toIdx, t) {
    var e = easeInOutCubic(t);
    // Show an edge during a tween only if both endpoints exist in the destination frame
    var activeTo = activeSetForIdx(toIdx);
    graph.nodes().forEach(function(id) {
        var posFrom = getNodePos(id, fromIdx);
        var posTo   = getNodePos(id, toIdx);
        var colFrom = getNodeColor(id, fromIdx);
        var colTo   = getNodeColor(id, toIdx);
        var sizeFrom = getNodeSize(id, fromIdx);
        var sizeTo   = getNodeSize(id, toIdx);
        graph.setNodeAttribute(id, 'x',     posFrom.x + (posTo.x - posFrom.x) * e);
        graph.setNodeAttribute(id, 'y',     posFrom.y + (posTo.y - posFrom.y) * e);
        graph.setNodeAttribute(id, 'color', lerpColor(colFrom, colTo, e));
        graph.setNodeAttribute(id, 'size',  sizeFrom + (sizeTo - sizeFrom) * e);
    });
    graph.edges().forEach(function(edgeId) {
        var src = graph.source(edgeId), tgt = graph.target(edgeId);
        graph.setEdgeAttribute(edgeId, 'hidden', !(activeTo.has(src) && activeTo.has(tgt)));
    });
    sigma_instance.refresh();
}

// =============================================================================
// Year label and dot updates
// =============================================================================

function setYearLabel(text) {
    el('tl-year-label').textContent = text;
    var ov = el('year-overlay');
    ov.textContent = text;
    ov.className = text ? 'year-active' : '';
}

function updateDots(idx) {
    el('tl-dots').querySelectorAll('.tl-dot').forEach(function(dot, i) {
        dot.classList.remove('dot-active', 'dot-past');
        if (i < idx)        dot.classList.add('dot-past');
        else if (i === idx) dot.classList.add('dot-active');
    });
}

function setYearIdx(idx, snap) {
    currentIdx = Math.max(0, Math.min(allYears.length - 1, idx));
    setYearLabel(String(allYears[currentIdx]));
    updateDots(currentIdx);
    if (snap !== false) applyFrame(currentIdx);
}

// =============================================================================
// Playback
// =============================================================================

function startRaf() {
    if (rafId) return;
    lastTs = null;
    rafId = requestAnimationFrame(rafTick);
}

function stopRaf() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    lastTs = null;
}

function rafTick(ts) {
    if (playState !== 'playing') { rafId = null; return; }
    var dt = lastTs ? Math.min(ts - lastTs, 100) : 0;
    lastTs = ts;
    var speed = SPEEDS[currentSpeed];
    phaseElapsed += dt;

    if (phase === 'hold') {
        if (phaseElapsed >= speed.hold) {
            if (currentIdx >= allYears.length - 1) {
                playState = 'stopped';
                setYearIdx(allYears.length - 1);
                updatePlayBtn();
                rafId = null;
                return;
            }
            tweenFrom = currentIdx;
            tweenTo   = currentIdx + 1;
            tweenT    = 0;
            phase     = 'tween';
            phaseElapsed = 0;
        }
    } else {
        tweenT = Math.min(phaseElapsed / speed.tween, 1);
        applyTween(tweenFrom, tweenTo, tweenT);
        setYearLabel(String(allYears[tweenTo]));
        updateDots(tweenTo);
        if (tweenT >= 1) {
            currentIdx   = tweenTo;
            phase        = 'hold';
            phaseElapsed = 0;
            applyFrame(currentIdx);
            setYearIdx(currentIdx, false);
        }
    }
    rafId = requestAnimationFrame(rafTick);
}

// =============================================================================
// Transport controls
// =============================================================================

function updatePlayBtn() {
    var btn  = el('tl-play');
    var icon = btn.querySelector('i');
    var playing = playState === 'playing';
    icon.className = playing ? 'bi bi-pause-fill' : 'bi bi-play-fill';
    btn.title = playing ? 'Pause' : 'Play';
    btn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
}

function doPlay() {
    if (playState === 'playing') {
        playState = 'paused';
        stopRaf();
    } else {
        if (currentIdx >= allYears.length - 1) { setYearIdx(0); }
        phase = 'hold'; phaseElapsed = 0;
        playState = 'playing';
        startRaf();
    }
    updatePlayBtn();
}

function doStop()  { stopRaf(); playState='stopped'; phase='hold'; phaseElapsed=0; updatePlayBtn(); setYearIdx(0); }
function doPrev()  { stopRaf(); playState='stopped'; updatePlayBtn(); if (currentIdx > 0) setYearIdx(currentIdx - 1); }
function doNext()  { stopRaf(); playState='stopped'; updatePlayBtn(); if (currentIdx < allYears.length - 1) setYearIdx(currentIdx + 1); }
function doFirst() { stopRaf(); playState='stopped'; updatePlayBtn(); setYearIdx(0); }
function doLast()  { stopRaf(); playState='stopped'; updatePlayBtn(); setYearIdx(allYears.length - 1); }

// =============================================================================
// Dots
// =============================================================================

function buildDots() {
    var container = el('tl-dots');
    container.innerHTML = '';
    allYears.forEach(function(year, i) {
        var dot = document.createElement('button');
        dot.className = 'tl-dot';
        dot.title = String(year);
        dot.setAttribute('aria-label', 'Jump to ' + year);
        dot.addEventListener('click', function() {
            stopRaf(); playState = 'stopped'; updatePlayBtn(); setYearIdx(i);
        });
        container.appendChild(dot);
    });
}

// =============================================================================
// Infobar
// =============================================================================

function showNodeInfo(nodeId) {
    var node = graph.getNodeAttributes(nodeId);
    el('node_label').innerHTML = node.label || node.id;
    var key = node.url ? node.url.replace('https://t.me/', '') : '';
    var urlEl = el('node_url');
    urlEl.innerHTML = '@' + key;
    urlEl.href = node.url || '#';
    el('node_picture').innerHTML = node.pic ? "<img src='" + node.pic + "' style='max-width:60px;'/>" : '';
    el('node_followers_count').innerHTML = node.fans || '—';
    el('node_messages_count').innerHTML  = node.messages_count || '—';
    el('node_activity_period').innerHTML = node.activity_period || '—';
    el('node_is_lost').style.display = node.is_lost ? '' : 'none';
    el('node_group').innerHTML = ''; el('node_measures').innerHTML = '';

    var inSet  = new Set(graph.inNeighbors(nodeId));
    var outSet = new Set(graph.outNeighbors(nodeId));
    var mutual = [], inN = [], outN = [];
    graph.neighbors(nodeId).forEach(function(k) {
        if (inSet.has(k) && outSet.has(k)) mutual.push(k);
        else if (inSet.has(k)) inN.push(k);
        else outN.push(k);
    });

    function neighborsList(ids) {
        return ids
            .map(function(id) { return graph.getNodeAttributes(id); })
            .sort(function(a, b) { return (a.label||'').localeCompare(b.label||''); })
            .map(function(n) {
                var c = nodeBaseColor[n.id] || '#ccc';
                return '<li><i class="bi bi-circle-fill" style="color:' + c + '"></i>'
                     + ' <a href="#" class="node-link" data="' + n.id + '">' + (n.label||n.id) + '</a></li>';
            }).join('');
    }

    el('node_mutual_count').innerHTML = mutual.length; el('node_mutual_list').innerHTML = neighborsList(mutual);
    el('node_in_count').innerHTML     = inN.length;    el('node_in_list').innerHTML     = neighborsList(inN);
    el('node_out_count').innerHTML    = outN.length;   el('node_out_list').innerHTML    = neighborsList(outN);
    el('infobar').style.display = 'block';
    isInfobarOpen = true;
}

function closeInfobar() { el('infobar').style.display = 'none'; isInfobarOpen = false; }

// =============================================================================
// Data loading
// =============================================================================

function loadMainGraph() {
    return Promise.all([
        fetch(BASE_DIR + 'channel_position.json').then(function(r) { if (!r.ok) throw new Error('channel_position.json ' + r.status); return r.json(); }),
        fetch(BASE_DIR + 'channels.json').then(function(r)          { if (!r.ok) throw new Error('channels.json ' + r.status);          return r.json(); }),
        fetch(BASE_DIR + 'communities.json').then(function(r)        { if (!r.ok) throw new Error('communities.json ' + r.status);        return r.json(); }),
    ]).then(function(results) {
        var posData  = results[0];
        var chData   = results[1];
        var commData = results[2];

        var strategies = Object.keys(commData.strategies);
        strategies.forEach(function(s) {
            community_color_maps[s] = {};
            (commData.strategies[s].groups || []).forEach(function(g) {
                community_color_maps[s][g[2]] = g[3];  // label → hex color
            });
        });
        active_strategy = strategies[0] || null;

        var measureMap = {};
        chData.nodes.forEach(function(n) { measureMap[n.id] = n; });

        var inDegVals = posData.nodes.map(function(n) { return (measureMap[n.id] || {}).in_deg || 0; });
        var minD = Math.min.apply(null, inDegVals);
        var maxD = Math.max.apply(null, inDegVals);
        nodeSizeRange = { min: minD, range: (maxD - minD) || 1 };

        posData.nodes.forEach(function(pos) {
            mainPositions[pos.id] = { x: pos.x, y: pos.y };
            var m = measureMap[pos.id] || {};

            // community color (hex from communities.json) takes priority; fall back to m.color ("r,g,b")
            var colorArr = [128, 128, 128];
            if (active_strategy && m.communities && m.communities[active_strategy]) {
                var hexColor = (community_color_maps[active_strategy] || {})[m.communities[active_strategy]];
                if (hexColor) colorArr = parseColor(hexColor);
            }
            if (colorArr[0] === 128 && colorArr[1] === 128 && colorArr[2] === 128 && m.color) {
                colorArr = parseColor(m.color);  // m.color is already "r,g,b"
            }
            var colorRgb = rgbStr(colorArr);
            nodeBaseColor[pos.id] = colorRgb;
            nodeDegrees[pos.id]   = m.in_deg || 0;

            var size = 1.5 + ((m.in_deg || 0) - nodeSizeRange.min) / nodeSizeRange.range * 13.5;
            graph.addNode(pos.id, Object.assign({}, m, {
                id:            pos.id,
                x:             pos.x,
                y:             pos.y,
                size:          size,
                color:         colorRgb,
                originalColor: colorRgb,
            }));
        });

        posData.edges.forEach(function(e) {
            var color = e.color ? 'rgba(' + e.color + ',0.25)' : 'rgba(72,72,72,0.25)';
            var attrs = Object.assign({}, e, { color: color, originalColor: color });
            delete attrs.source; delete attrs.target; delete attrs.id;
            try { graph.addEdge(e.source, e.target, attrs); } catch(_) {}
        });

        sigma_instance.refresh();
    });
}

function loadYearFrame(year) {
    return fetch('data_' + year + '/channel_position.json')
        .then(function(r) { if (!r.ok) throw new Error('missing'); return r.json(); })
        .then(function(posData) {
            var positions = {}, activeSet = new Set();
            posData.nodes.forEach(function(n) {
                positions[n.id] = { x: n.x, y: n.y };
                activeSet.add(n.id);
            });
            yearFrames[year] = { positions: positions, activeSet: activeSet };
        })
        .catch(function() {
            yearFrames[year] = { positions: {}, activeSet: new Set() };
        });
}

// Load year frames one at a time to avoid overwhelming the dev server
function loadYearFramesSequentially() {
    return allYears.reduce(function(chain, year, i) {
        return chain.then(function() {
            el('loading_message').innerHTML = 'Loading year data (' + (i + 1) + '/' + allYears.length + ')…';
            return loadYearFrame(year);
        });
    }, Promise.resolve());
}

// =============================================================================
// Initialise
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initSigma();

    var loadingEl = el('loading_modal');
    loading_modal_bs = new bootstrap.Modal(loadingEl, { backdrop: 'static', keyboard: false });

    el('tl-play').addEventListener('click',  doPlay);
    el('tl-stop').addEventListener('click',  doStop);
    el('tl-prev').addEventListener('click',  doPrev);
    el('tl-next').addEventListener('click',  doNext);
    el('tl-first').addEventListener('click', doFirst);
    el('tl-last').addEventListener('click',  doLast);

    document.querySelectorAll('.tl-speed-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.tl-speed-btn').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentSpeed = btn.dataset.speed;
        });
    });

    document.querySelectorAll('.infobar-toggle').forEach(function(btn) {
        btn.addEventListener('click', closeInfobar);
    });

    document.addEventListener('click', function(e) {
        var link = e.target.closest('a.node-link');
        if (!link) return;
        e.preventDefault();
        showNodeInfo(link.getAttribute('data'));
    });

    // Start loading only after the modal has fully appeared (same pattern as graph.js)
    loadingEl.addEventListener('shown.bs.modal', function() {
        el('loading_message').innerHTML = 'Loading timeline…';

        fetch(BASE_DIR + 'timeline.json')
            .then(function(r) {
                if (!r.ok) throw new Error('timeline.json ' + r.status);
                return r.json();
            })
            .then(function(tlData) {
                allYears = (tlData.years || []).map(function(e) { return e.year; }).sort(function(a,b){return a-b;});
                if (allYears.length === 0) throw new Error('no years in timeline');
                el('loading_message').innerHTML = 'Loading graph…';
                return loadMainGraph();
            })
            .then(function() {
                return loadYearFramesSequentially();
            })
            .then(function() {
                buildDots();
                setYearIdx(0);
                loading_modal_bs.hide();
            })
            .catch(function(err) {
                console.error('graph_timeline loading error:', err);
                loading_modal_bs.hide();
                el('no-timeline-msg').style.display = '';
            });
    }, { once: true });

    loading_modal_bs.show();
});
