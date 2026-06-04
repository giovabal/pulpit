// Mirrors COMMUNITY_STRATEGY_LABELS in network/community.py (keys lower-cased). LEIDEN_CPM is one
// parameterised strategy now — per-instance partitions arrive as suffixed keys (leiden_cpm_resolution_0_05).
export var STRATEGY_LABELS = {
    organization:     'Organization',
    leiden:           'Leiden',
    leiden_directed:  'Leiden directed',
    leiden_cpm:       'Leiden CPM',
    labelpropagation: 'Label propagation',
    kcore:            'K-core',
    sbm:              'Stochastic block model',
};

// Base keys of the parameterised strategies (longest first), and their param kinds — used to strip a
// parameter suffix back to the family and to reconstruct a readable annotation. Mirrors
// network.community.canonical_strategy_key / strategy_display_label.
var STRATEGY_BASE_KEYS = ['leiden_cpm', 'sbm'];
var STRATEGY_PARAM_KINDS = { resolution: 'float', mode: 'enum' };

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
    if (k === base) return label;
    var rest = k.slice(base.length + 1);          // e.g. "resolution_0_05"
    var us = rest.indexOf('_');
    if (us === -1) return label;
    var pname = rest.slice(0, us);
    var raw = rest.slice(us + 1);
    var val = STRATEGY_PARAM_KINDS[pname] === 'float' ? raw.replace(/_/g, '.') : raw;
    return label + ' (' + pname + '=' + val + ')';
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
