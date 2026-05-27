// Behavioural equivalence heatmap — cosine similarity of channels' behavioural-measure
// profiles (amplification, content originality, diffusion lag, spreading efficiency,
// followers, message count).
import { initEquivalenceMatrix } from './equivalence_matrix.js';

initEquivalenceMatrix({
    jsonName: "behavioural_equivalence.json",
    containerId: "behavioural-equivalence-container",
    errorLabel: "behavioural_equivalence",
});
