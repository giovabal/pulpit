export var STRATEGY_LABELS = {
    organization:      'Organization',
    leiden:            'Leiden',
    leiden_directed:   'Leiden directed',
    leiden_cpm_coarse: 'Leiden CPM coarse',
    leiden_cpm_fine:   'Leiden CPM fine',
    louvain:           'Louvain',
    kcore:             'K-core',
    infomap:           'Infomap',
    infomap_memory:    'Infomap memory',
    mcl:               'MCL',
    walktrap:          'Walktrap',
    weakcc:            'Weak connected components',
    strongcc:          'Strong connected components',
};

export function strategy_label(key) {
    return STRATEGY_LABELS[key.toLowerCase()] ||
        (key.charAt(0).toUpperCase() + key.slice(1).toLowerCase().replace(/_/g, ' '));
}

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

export function layout_label(key) {
    return LAYOUT_LABELS[key] ||
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
