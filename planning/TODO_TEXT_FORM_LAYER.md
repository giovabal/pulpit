# TODO — Text-form layer: channel style over time and across channels

Research pass of 2026-10-03. Nothing implemented yet. Goal: a layer that describes **how** a
channel writes (form, register, template), independent of **what** it writes about, so that
one can (a) follow a channel's evolution over time, (b) compare channels with each other, and
(c) do both on **original text only** — never on forwards or copied text.

Trigger was the SlopShape paper (Madler 2026, arXiv 2609.15369, "Identifying AI-Generated
Commercial Web Content"). Its detector does not transfer (see §0), but two ideas do: a fixed
structural schema scored per post, and a rarity/formulaicity metric in that feature space.

---

## 0. Why SlopShape is not replicated as-is

SlopShape scores 600–2,500-word English B2B blog posts against 214 LLM-rated structural
features in 11 dimensions, then trains XGBoost on paired human/AI mirrors (98 macro-F1
human-vs-AI; 79% source attribution). Reasons it does not fit Pulpit:

- Posts are short: median authored message is 11 words (§1). Features such as "thesis stated
  before first section" or "closing restates thesis" are meaningless at that length.
- Features were discovered on English commercial writing; genre-specific (commercial
  integration, CTA, actionability).
- No ground truth: Pulpit has no labels for AI-written posts; SlopShape's power comes from the
  paired mirror corpus.
- 11 LLM calls per post; Pulpit has no LLM dependency, and the paper itself reports only
  Krippendorff α = 0.89 repeatability for that step. Non-deterministic + costly.
- Single-author company paper, company-affiliated annotators, gated data → moderate caution.

Keep: (1) per-post structural schema → per-channel profile; (2) rarity (kNN distance in
z-scored feature space) → **formulaicity**: low = templated/press-office/automated,
high = heterogeneous human posting; (3) a within-channel before/after-2022 design is possible
here and *not* in SlopShape, because the corpus spans the ChatGPT boundary.

---

## 1. Corpus facts (measured 2026-10-03, alive messages, in-target via `channel_cutoff_q()`)

| Quantity | Value |
| :-- | :-- |
| In-target alive messages | 114,072 |
| Forwards (`forwarded_from` / `forwarded_from_private`) | 62,317 / 8,010 (≈ 55%) |
| No text at all (media-only) | 43,805 (38%) |
| **Authored messages with text** | **27,302 over 307 channels** |
| Authored messages per channel, quantiles 10/25/50/75/90 | 2 / 6 / 18 / 52 / 150 |
| Authored words per channel, quantiles 10/25/50/75/90 | 53 / 151 / 499 / 1,673 / 5,067 |
| Channels with ≥ 2,000 / ≥ 5,000 authored words | 68 / 33 |
| Channel-year bins (593 total) with ≥ 1,000 / 2,000 / 5,000 words | 154 / 84 / 34 |
| Authored message length, quantiles 25/50/75/90 | 4 / 11 / 30 / 76 words |
| Language of posts ≥ 12 words | ≈ 80% English, ≈ 4% Italian, rest other/mixed |
| Years with channel-year bins | 2019: 1 · 2020: 2 · 2021: 7 · 2022: 17 · 2023: 73 · 2024: 110 · 2025: 162 · 2026: 221 |

**Binding constraint.** Eder (2015) found that word-frequency stylometry needs 2,500–5,000
words per sample *regardless of method*. So full stylometric profiles are possible for a few
dozen channels and a few dozen channel-years only. Everything else must either (a) use
features that are valid at the single-message level (presence/absence coding), or (b) pool
channels by label group / period, or (c) use methods explicitly validated for micro-messages
(char n-grams, compression models).

Script used for the numbers (re-run to refresh): Django shell, `Message.objects.alive()
.filter(channel_cutoff_q(), forwarded_from=None, forwarded_from_private=None).exclude(message="")`,
word counts via `str.split()`.

---

## 2. Design guardrails

- **Original text only.** Exclude `forwarded_from` and `forwarded_from_private` messages,
  then run near-duplicate detection across *all* channels (§3) and drop copies that were pasted
  rather than forwarded. Keep the earliest poster's copy as authored.
- **Period-aware.** Only messages inside in-target label periods (`channel_cutoff_q()`),
  exactly like the graph pipeline. Per-year bins follow `--timeline-step year`.
- **Form, not content.** Prefer function words, POS, punctuation, emoji, layout, length
  features; mask content words (POSNoise, §3) for the content-free variants.
- **Word floors + explicit "insufficient data".** Never output a stylometric distance for a
  bin below its method's floor; the table/JSON must carry an explicit `insufficient` flag.
- **Node attributes / separate similarity layer, not citation edges.** Style similarity is not
  a relational fact in the one-degree model (docs/network-measures.md). Model it like the
  coordination layer (own data dir, own viewer), not as graph edges.
- **Deterministic and offline** wherever possible (no LLM scoring in v1). Seeded wherever a
  method is stochastic (bootstrap, MCA init).
- **Length confound.** Every feature must be either length-invariant by construction
  (presence/absence, MTLD, HD-D, MATTR) or reported with its sample size; never raw TTR.

---

## 3. Step 0 — isolate original text

- [x] **Near-duplicate detection exists** (2026-10-03): `network/near_copies.py` — Broder
      resemblance over word 3-shingles, exact prefix-filtering join (no MinHash), per-channel
      boilerplate removal, earliest-match orientation; shipped as the `--near-copy-edges`
      option of `structural_analysis` (copies read as forwards; audit list
      `data/near_copies.csv`). Validated on tweets by Tao, Abel, Hauff & Houben (WWW 2013).
- [ ] **Reuse it for the form layer**: run `find_near_copies` on authored text; the earliest
      copy stays "authored", later copies become `copied` and are excluded from form stats
      (the copy events themselves are identity/coordination evidence, see §7).
- [ ] **Quote/mention stripping policy.** Decide how Telegram quote blocks, `@mentions`,
      URLs and hashtags are treated: keep as *form* tokens (`<URL>`, `<MENTION>`, `<TAG>`)
      rather than deleting them; their position and density are style features (Clarke &
      Grieve 2017).
- [ ] **Topic masking variant.** POSNoise (Halvani & Graner 2021): replace content words by
      POS tags, keep function words, punctuation, emoji, numerals. Produces the content-free
      text used by families 2 and 3. Needs a POS tagger (spaCy `en_core_web_*`; add `it` /
      multilingual models as needed — corpus is ≈ 80% English, see §1).
- [ ] **Language tagging per message** (fastText `lid.176` or `langdetect`), so per-language
      models/stopword lists are used and mixed-language channels are flagged.

---

## 4. Strategy families (all peer-reviewed)

### 4.1 Short-text multidimensional register analysis (the backbone)

Biber (1988) multidimensional analysis (MDA) is the reference framework for text form.
Clarke & Grieve (2017, *Dimensions of Abusive Language on Twitter*) adapted it to tweets:
posts are too short for frequencies, so each message is coded for **presence/absence** of
grammatical + CMC features and **multiple correspondence analysis (MCA)** extracts
dimensions of variation. Clarke & Grieve (2019, PLoS ONE) applied it to **one account over
ten years** (Trump) and recovered four styles whose mix shifted systematically by campaign
phase — the closest published design to "evolution of one channel over time", valid at our
message lengths.

- Feature extractors: **BiberPlus / Neurobiber** (Alkiek, Wegmann, Zhu & Jurgens 2025; 96
  Biber features, pip-installable, replicates MDA on CORE, competitive on PAN 2020 AV);
  **Profiling-UD** (Brunato, Cimino, Dell'Orletta, Venturi & Montemagni, LREC 2020; >130
  UD-based features, multilingual — relevant for the non-English share).
- Add CMC features à la Clarke & Grieve: emoji (count, position, header/footer), hashtags,
  URLs and their position, all-caps share, letter elongation, exclamation/question density,
  line breaks / list layout, media-only post, caption-only post, first-person voice, imperative
  / call-to-action, quotation.
- Channel profile = mean feature vector + MCA coordinates (fit MCA on all messages once, seeded).
  Time = per-year (or per-N-messages rolling window) mean on each dimension with **bootstrap
  CIs** over messages. Between-channel distance = distance on the MCA dimensions.
- Formulaicity (SlopShape's rarity, inverted): mean kNN distance of a channel's posts in the
  z-scored feature space; also n-gram self-repetition / compression ratio of the channel's own
  pool (Cilibrasi & Vitányi 2005 NCD self-similarity).

### 4.2 Stylometric distance and authorship verification ("same hand?")

- **Character 3-/4-gram profiles** are the most robust representation for micro-messages
  (Rocha, Scheirer, Forstall, Cavalcante, Theophilo & Shen, IEEE TIFS 2017; Sapkota et al.
  2015, *Not all character n-grams are created equal*; Stamatatos 2009 survey; Schwartz, Tsur,
  Rappoport & Koppel, EMNLP 2013 for tweets). Aggregate many posts per channel before scoring.
- **Cosine Delta** (Burrows 2002 Delta; Evert, Proisl, Jannidis et al. 2017 show vector
  normalisation is the decisive ingredient) as the distance; **bootstrap consensus** (Eder
  2013) for stability; `faststylometry` / `pydelta` / R `stylo`.
- **Impostors method** (Koppel & Winter 2014, JASIST) for the pairwise question "channels A
  and B, same author?" with a background set of impostor channels; designed for short
  documents; shipped in `stylo::perform.impostors`.
- **Compression-based verification** (Halvani, Winter & Graner 2017, COAV; PPM/NCD):
  compressor + dissimilarity + threshold only, language-independent, competitive on short
  texts → the fallback for channels under the word floor.
- **Neural, later:** LUAR (Rivera-Soto et al., EMNLP 2021) aggregates many short posts into
  one author embedding, cross-domain validated; Wegmann, Schraagen & Nguyen (2022) show how to
  train content-controlled style embeddings. GPU-sized dependency → not v1.
- Classic rich feature set for reference: Writeprints (Abbasi & Chen 2008) — lexical,
  syntactic, structural, content-specific, idiosyncratic — validated on online messages.

### 4.3 Information-theoretic distribution comparison (drift + distance on small samples)

- **Jensen-Shannon divergence with finite-size bias correction** (Gerlach, Font-Clos &
  Altmann, PRX 2016): derives how estimator bias/fluctuations scale with N for Zipfian data
  and tracks two centuries of English with it. Our 500-word bins are exactly that regime.
  Code: `martingerlach/jensen-shannon-alpha-divergence`.
- **Cross-entropy under a per-period community language model** (Danescu-Niculescu-Mizil,
  West, Jurafsky, Leskovec & Potts, WWW 2013): each channel gets a "distance from the
  community norm" per period; separates community-level from channel-level change. Bigram LM
  with smoothing on the pooled in-target authored text per year.
- **Which features differ:** keyness with Dunning (1993) log-likelihood and the effect sizes
  reviewed by Gabrielatos (2018); Burrows (2007) Zeta as evaluated by Schöch et al. (2018) for
  contrastive "A vs B" marker words.
- **Lexical diversity:** only length-robust indices — MTLD and HD-D (McCarthy & Jarvis 2010
  validation), MATTR (Covington & McFall 2010). Python: `lexical_diversity`. Raw TTR is invalid
  at these lengths.
- **Punctuation-only sequences** (Darmon et al. 2021, *Pull out all the stops*) as a
  language-light form signal.

### 4.4 Temporal change detection (operator-change points)

- Stylochronometry (Stamou 2008 survey; Klaussner & Vogel 2018, *Temporal predictive
  regression models for linguistic style analysis*, JLM) for individual vs general change.
- **PAN Style Change Detection** (Zangerle et al., CLEF since 2016): methods that locate the
  position in a stream where the author switches → applied to a channel's chronologically
  ordered posts = operator-change detector.
- **One-class authorship verification for compromised accounts** (Barbon, Igawa & Zarpelão
  2017): earlier posts as reference, later posts scored as in/out of profile → drift score.
- Change-point detection on the per-period dimension scores from §4.1: PELT (Killick,
  Fearnhead & Eckley 2012; `ruptures`) or Bayesian online CPD (Adams & MacKay 2007).

---

## 5. Build plan (ordered; each step independently useful)

- [ ] **5.1 Step 0 pipeline** (§3): authored-text selection, near-dup removal, language tag,
      POSNoise variant. Persist per-message flags (`copied`, `lang`) — probably a small
      side table or cached columns, *not* a Message field churn; decide in design review.
- [ ] **5.2 Message-level coder** (§4.1): presence/absence + count features (Clarke & Grieve
      CMC set + Biber features via BiberPlus or spaCy). One row per authored message.
- [ ] **5.3 Channel profiles + MCA**: per-channel mean vector, MCA coordinates, formulaicity;
      per-year series with bootstrap CIs; between-channel distance matrix on MCA dims.
      Output: `data/text_form.json` (+ per-year), CSV/XLSX, a `text_form.html` viewer
      (dimension scatter, per-channel timeline, similarity heatmap).
- [ ] **5.4 Pooling by label group**: organisation/region pools to clear Eder's floor;
      per-pool register profile and per-pool drift.
- [ ] **5.5 Stylometric distances** (§4.2): char-4-gram cosine Delta + compression NCD/COAV
      between channel pools above the floor; Impostors test for *specific* pairs
      (vacancy → candidate successors). Hard floors with `insufficient` flags.
- [ ] **5.6 Drift measures** (§4.3): bias-corrected JSD year-over-year per channel; cross-
      entropy vs the yearly community LM; keyness/Zeta tables for the top contrasts.
- [ ] **5.7 Change points** (§4.4): PELT on §5.3 series; style-change score on ordered posts.
- [ ] **5.8 Optional measures into the channel battery**: `FORMULAICITY`, `STYLE_DRIFT`,
      `COMMUNITY_DISTANCE` as behavioural node measures (string/numeric columns like
      `CONTENTORIGINALITY`), flowing to channels.json / CSV / XLSX / GEXF / channel table.
- [ ] **5.9 LLM-scored structural schema** (SlopShape-style, sample of ≤ 200 authored posts
      per channel) — only after 5.1–5.7, only if a question needs it; adds an external API
      dependency, cost and non-determinism.

---

## 6. Validation

- [ ] **Known successors as ground truth.** `ChannelVacancy.successor` labels give
      same-operator pairs. Report hits@1/3/5 + MRR of each similarity (MCA distance, cosine
      Delta, NCD, Impostors) at recovering the labelled successor among candidates — the same
      scheme the vacancy analysis already uses for its scorers (docs/vacancy-analysis.md).
- [ ] **Null for similarity**: shuffle messages across channels within the same year to get
      the distribution of distances expected under "no channel-specific style"; report z/p.
- [ ] **Stability**: bootstrap over messages (Eder 2013) for every channel-level number;
      sensitivity to the word floor and to the dedup threshold.
- [ ] **Length-invariance audit**: regress every feature on message length / pool size; drop or
      normalise features that correlate.
- [ ] **Topic leakage check**: results with vs without POSNoise masking; a similarity that
      collapses under masking was topical, not stylistic.

---

## 7. Integration points in Pulpit

- **Vacancy analysis**: template identity as a sixth successor evidence (identity lineage,
  Niverthi et al. 2022 already cited there); the Impostors verdict as a column with its own
  q-value.
- **Coordination layer**: cross-channel near-duplicates (§3) are "copy" ties that the
  co-forwarding layer cannot see; consider a `copy` tie type alongside co-forward ties.
- **Timeline**: per-year bins reuse `--timeline-step year`; drift series align with the
  year switcher.
- **Label groups**: pooling unit for register profiles; a container group gives
  region/organisation-level style.
- **Dominance / measures**: `FORMULAICITY` etc. as node measures; no graph edges from style.
- **Exports**: same atomic `.tmp` export contract; `summary.json` entry; index card.

---

## 8. Open questions

- Unit of time for sparse channels: calendar year vs rolling window of N messages?
- Treatment of media captions vs text-only posts (caption-only posts are a *form* feature
  but dilute lexical statistics).
- Which POS tagger covers the non-English 20% acceptably? Profiling-UD/Stanza vs spaCy.
- Store per-message features in the DB or recompute at export time? (27k rows today; grows.)
- Should copies detected in §3 retroactively mark messages for `purge`/stats elsewhere? No by
  default — keep this layer read-only on the message store.

---

## References

- Abbasi A., Chen H. (2008). Writeprints: A stylometric approach to identity-level
  identification and similarity detection in cyberspace. *ACM TOIS* 26(2).
- Adams R. P., MacKay D. J. C. (2007). Bayesian online changepoint detection. arXiv:0710.3742.
- Alkiek K., Wegmann A., Zhu J., Jurgens D. (2025). Neurobiber: Fast and interpretable
  stylistic feature extraction. arXiv:2502.18590. https://arxiv.org/abs/2502.18590
- Barbon S., Igawa R. A., Zarpelão B. B. (2017). Authorship verification applied to detection
  of compromised accounts on online social networks. *Multimedia Tools and Applications*.
- Biber D. (1988). *Variation across Speech and Writing*. CUP.
- Broder A. (1997). On the resemblance and containment of documents. *SEQUENCES*.
- Brunato D., Cimino A., Dell'Orletta F., Venturi G., Montemagni S. (2020). Profiling-UD: a
  tool for linguistic profiling of texts. *LREC 2020*. https://aclanthology.org/2020.lrec-1.883/
- Burrows J. (2002). 'Delta': a measure of stylistic difference. *LLC* 17(3).
- Burrows J. (2007). All the way through: testing for authorship in different frequency
  strata. *LLC* 22(1). (Zeta)
- Charikar M. (2002). Similarity estimation techniques from rounding algorithms. *STOC*.
- Cilibrasi R., Vitányi P. (2005). Clustering by compression. *IEEE Trans. Inf. Theory*.
- Clarke I., Grieve J. (2017). Dimensions of abusive language on Twitter. *ALW1*.
  https://aclanthology.org/W17-3001/
- Clarke I., Grieve J. (2019). Stylistic variation on the Donald Trump Twitter account: a
  linguistic analysis of tweets posted between 2009 and 2018. *PLoS ONE* 14(9).
- Covington M., McFall J. (2010). Cutting the Gordian knot: the moving-average type–token
  ratio (MATTR). *J. Quant. Linguistics* 17(2).
- Danescu-Niculescu-Mizil C., West R., Jurafsky D., Leskovec J., Potts C. (2013). No country
  for old members: user lifecycle and linguistic change in online communities. *WWW 2013*.
  https://nlp.stanford.edu/pubs/linguistic_change_lifecycle.pdf
- Darmon A. et al. (2021). Pull out all the stops: textual analysis via punctuation
  sequences. *Eur. J. Appl. Math.*
- Dunning T. (1993). Accurate methods for the statistics of surprise and coincidence.
  *Computational Linguistics* 19(1).
- Eder M. (2013). Mind your corpus: systematic errors in authorship attribution / bootstrap
  consensus trees. *LLC*.
- Eder M. (2015). Does size matter? Authorship attribution, small samples, big problem.
  *DSH* 30(2): 167–182. doi:10.1093/llc/fqt066
- Evert S., Proisl T., Jannidis F., Reger I., Pielström S., Schöch C., Vitt T. (2017).
  Understanding and explaining Delta measures for authorship attribution. *DSH* 32(suppl 2).
  doi:10.1093/llc/fqx023
- Gabrielatos C. (2018). Keyness analysis: nature, metrics and techniques. In *Corpus
  Approaches to Discourse*. Routledge.
- Gerlach M., Font-Clos F., Altmann E. G. (2016). Similarity of symbol frequency
  distributions with heavy tails. *Phys. Rev. X* 6, 021009. https://arxiv.org/abs/1510.00277
- Halvani O., Winter C., Graner L. (2017). Authorship verification based on compression-models.
  arXiv:1706.00516.
- Halvani O., Graner L. (2021). POSNoise: an effective countermeasure against topic biases in
  authorship analysis. *ARES 2021*. https://arxiv.org/abs/2005.06605
- Killick R., Fearnhead P., Eckley I. A. (2012). Optimal detection of changepoints with a
  linear computational cost. *JASA* 107(500).
- Klaussner C., Vogel C. (2018). Temporal predictive regression models for linguistic style
  analysis. *Journal of Language Modelling* 6(1).
- Koppel M., Winter Y. (2014). Determining if two documents are written by the same author.
  *JASIST* 65(1): 178–187. doi:10.1002/asi.22954
- Madler J. (2026). SlopShape: identifying AI-generated commercial web content.
  arXiv:2609.15369. https://arxiv.org/abs/2609.15369
- Manku G. S., Jain A., Das Sarma A. (2007). Detecting near-duplicates for web crawling. *WWW*.
- McCarthy P. M., Jarvis S. (2010). MTLD, vocd-D, and HD-D: a validation study of
  sophisticated approaches to lexical diversity assessment. *Behavior Research Methods* 42:
  381–392.
- Rivera-Soto R. A., Miano O. E., Ordonez J., Chen B. Y., Khan A., Bishop M., Andrews N.
  (2021). Learning universal authorship representations. *EMNLP 2021*.
  https://aclanthology.org/2021.emnlp-main.70/
- Rocha A., Scheirer W. J., Forstall C. W., Cavalcante T., Theophilo A., Shen B., Carvalho
  A. R. B., Stamatatos E. (2017). Authorship attribution for social media forensics. *IEEE
  TIFS* 12(1).
- Sapkota U., Bethard S., Montes-y-Gómez M., Solorio T. (2015). Not all character n-grams are
  created equal: a study in authorship attribution. *NAACL 2015*.
- Schöch C., Schlör D., Zehe A., Gebhard H., Becker M., Hotho A. (2018). Burrows' Zeta:
  exploring and evaluating variants and parameters. *DH 2018*.
- Schwartz R., Tsur O., Rappoport A., Koppel M. (2013). Authorship attribution of
  micro-messages. *EMNLP 2013*.
- Stamatatos E. (2009). A survey of modern authorship attribution methods. *JASIST* 60(3).
- Stamou C. (2008). Stylochronometry: stylistic development, sequence of composition, and
  relative dating. *LLC* 23(2).
- Tao K., Abel F., Hauff C., Houben G.-J., Gadiraju U. (2013). Groundhog Day: near-duplicate
  detection on Twitter. *WWW 2013*. https://dl.acm.org/doi/10.1145/2488388.2488499
- Wegmann A., Schraagen M., Nguyen D. (2022). Same author or just same topic? Towards
  content-independent style representations. *RepL4NLP 2022*.
  https://aclanthology.org/2022.repl4nlp-1.26/
- Zangerle E., Mayerl M., Specht G., Potthast M., Stein B. (2020). Overview of the style
  change detection task at PAN 2020. *CLEF 2020*. https://ceur-ws.org/Vol-2696/paper_256.pdf
