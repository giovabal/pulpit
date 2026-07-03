// Mirrors COMMUNITY_STRATEGY_LABELS in network/community.py (keys lower-cased). LEIDEN_CPM is one
// parameterised strategy now — per-instance partitions arrive as suffixed keys (leiden_cpm_resolution_0_05).
// The dynamic metadata partitions arrive as `labelgroup<id>` keys; their human label is the
// LabelGroup name, injected at runtime via window.STRATEGY_LABELS (export/UI pass) — falling back to a
// title-cased key here.
export var STRATEGY_LABELS = {
    leiden:           'Leiden',
    leiden_directed:  'Leiden directed',
    leiden_cpm:       'Leiden CPM',
    leiden_temporal:  'Leiden temporal',
    louvain:          'Louvain',
    kcore:            'K-core',
    sbm:              'Stochastic block model',
    sbm_assortative:  'Assortative SBM',
    consensus:        'Consensus',
    // Removed in v0.27 — kept so pre-0.27 exports rebuilt with fresh map assets still label it.
    labelpropagation: 'Label propagation',
};

// LabelGroup partitions arrive as `labelgroup<id>` keys; the static map above can't know the
// analyst's group names, so the exporter injects them as `window.STRATEGY_LABELS` (a classic inline
// script that runs before these modules) — fold them in so strategy_label() and every other consumer
// shows the real group name instead of a title-cased key.
if (typeof window !== 'undefined' && window.STRATEGY_LABELS) {
    Object.keys(window.STRATEGY_LABELS).forEach(function (k) {
        STRATEGY_LABELS[String(k).toLowerCase()] = window.STRATEGY_LABELS[k];
    });
}

// Base keys of the parameterised strategies (longest first), their declared params (spec order) and
// param kinds — used to strip a parameter suffix back to the family and to reconstruct a readable
// annotation. Mirrors network.community.canonical_strategy_key / strategy_display_label.
// Ordered longest-first where one base prefixes another (sbm_assortative before sbm).
var STRATEGY_BASE_KEYS = ['leiden_temporal', 'leiden_cpm', 'sbm_assortative', 'consensus', 'sbm'];
var STRATEGY_PARAMS = {
    leiden_cpm: ['resolution'],
    leiden_temporal: ['resolution', 'interslice'],
    consensus: ['threshold'],
    sbm: ['mode', 'weights', 'refine'],
    sbm_assortative: ['refine'],
};
var STRATEGY_PARAM_KINDS = {
    resolution: 'float', interslice: 'float', threshold: 'float',
    mode: 'enum', weights: 'enum', refine: 'enum',
};

export function canonical_strategy_key(key) {
    var k = String(key).toLowerCase();
    for (var i = 0; i < STRATEGY_BASE_KEYS.length; i++) {
        var base = STRATEGY_BASE_KEYS[i];
        if (k === base || k.indexOf(base + '_') === 0) return base;
    }
    return k;
}

export function strategy_label(key) {
    var k = String(key).toLowerCase();
    var base = canonical_strategy_key(k);
    var label = STRATEGY_LABELS[base] ||
        (base.charAt(0).toUpperCase() + base.slice(1).replace(/_/g, ' '));
    // Label-group partitions read as a manual "[custom label]" wherever they appear as a strategy
    // option outside their own picker (mirrors CUSTOM_LABEL_SUFFIX in network/community.py).
    if (/^labelgroup\d+$/.test(base)) label += ' [custom label]';
    if (k === base) return label;
    var rest = k.slice(base.length + 1);          // e.g. "mode_nested_weights_poisson"
    var params = STRATEGY_PARAMS[base] || [];
    var parts = [];
    for (var i = 0; i < params.length; i++) {
        var prefix = params[i] + '_';
        if (rest.indexOf(prefix) !== 0) continue;  // omitted (empty-default) parameter
        var valuePart = rest.slice(prefix.length);
        // The value runs until the next declared parameter's "_<name>_" boundary (suffix order is
        // spec order); enum values carry no "_" and float slugs are digits and "_", so the
        // boundary is unambiguous. Mirrors strategy_display_label in network/community.py.
        var cut = valuePart.length;
        for (var j = i + 1; j < params.length; j++) {
            var pos = valuePart.indexOf('_' + params[j] + '_');
            if (pos !== -1 && pos < cut) cut = pos;
        }
        var raw = valuePart.slice(0, cut);
        rest = cut < valuePart.length ? valuePart.slice(cut + 1) : '';
        parts.push(params[i] + '=' + (STRATEGY_PARAM_KINDS[params[i]] === 'float' ? raw.replace(/_/g, '.') : raw));
    }
    return parts.length ? label + ' (' + parts.join(', ') + ')' : label;
}

// Short labels shown in info-bar chips — kept terse so chips stay compact.
export var LAYOUT_LABELS = {
    fa2:             'FA2',
    circular:        'Circular',
    kamada_kawai:    'Kamada-Kawai',
    community_shell: 'Community shells',
    tsne:            't-SNE',
    umap:            'UMAP',
    hyperbolic:      'Hyperbolic',
    spectral:        'Spectral',
    spring:          'Spring',
};

// Verbose labels shown in dropdown options. Covers both 2D and 3D layouts;
// the dropdown only renders entries listed in window.EXTRA_LAYOUTS / EXTRA_LAYOUTS_3D.
export var LAYOUT_LONG_LABELS = {
    fa2:             'Force Atlas 2',
    circular:        'Circular',
    kamada_kawai:    'Kamada-Kawai',
    community_shell: 'Community shells',
    tsne:            't-SNE',
    umap:            'UMAP',
    hyperbolic:      'Hyperbolic',
    spectral:        'Spectral',
    spring:          'Spring (Fruchterman-Reingold)',
};

export function layout_label(key) {
    return LAYOUT_LABELS[key] ||
        (key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '));
}

export function layout_long_label(key) {
    return LAYOUT_LONG_LABELS[key] ||
        (key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '));
}

export var LABELS_MODE_LABELS = {
    on_size: 'Auto labels',
    always:  'Labels on',
    never:   'Labels off',
};

export var THEME_LABELS = {
    dark:    'Dark',
    light:   'Light',
    minimal: 'Minimal',
    print:   'Print',
};
