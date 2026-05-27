// Structural equivalence heatmap. The data file is kept as structural_similarity.json
// for saved-config / URL compatibility; its contents are now true structural
// equivalence (Lorrain & White 1971), computed server-side.
import { initEquivalenceMatrix } from './equivalence_matrix.js';

initEquivalenceMatrix({
    jsonName: "structural_similarity.json",
    containerId: "structural-similarity-container",
    errorLabel: "structural_equivalence",
});
