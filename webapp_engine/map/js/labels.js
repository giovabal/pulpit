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
