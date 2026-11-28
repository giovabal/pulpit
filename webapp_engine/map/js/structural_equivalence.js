// Structural equivalence heatmap (Lorrain & White 1971), computed server-side into
// data/structural_equivalence.json.
import { initEquivalenceMatrix } from './equivalence_matrix.js';

initEquivalenceMatrix({
    jsonName: "structural_equivalence.json",
    containerId: "structural-similarity-container",
    errorLabel: "structural_equivalence",
});
