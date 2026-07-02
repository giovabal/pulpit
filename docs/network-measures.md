# Network measures

A network measure assigns a numerical score to each channel based on its position in the directed citation graph. Pulpit constructs edges from forwards and `t.me/` references: a directed edge from channel A to channel B means A regularly amplifies B's content, weighted by frequency relative to A's total output.

All measures can be used to size nodes in the graph viewer, making the most significant channels visually prominent.

<figure>
<img src="../webapp_engine/static/screenshot_01.jpg" alt="Channel table with network measures">
<figcaption><em>Channel table: every computed measure as a sortable column. Click any header to rank channels by that measure.</em></figcaption>
</figure>
<br>

---

## What this catalogue covers

Pulpit's edges record **one-degree** amplification: Telegram attributes every forward to the original author, so a citation points straight at the source and the graph is a *citation* network, not a transmission network — its multi-hop paths carry no flow. This is borne out empirically on Telegram, where forwarding cascades form depth-1 stars with no onward propagation, unlike the multi-hop retweet trees of other platforms (Kuznetsov *et al.* 2026). The claim has a precise shape: multi-hop *relaying* certainly happens behaviourally — a channel often discovers content through an intermediary it follows — but the record of that journey jumps straight to the origin, so mediation is *unobservable in the data*, not absent from the platform. The one trace relay dynamics do leave is **timing**, which is why the battery includes a timing measure ([Diffusion lag](#diffusion-lag)) rather than a path measure.

The selection principle follows Borgatti (2005): every centrality index carries an implicit model of *what* moves across the ties and *how*, and a measure is informative exactly when the recorded ties match that model. Applied to forward-attribution data, the measures that stay well-defined are those of degree and prestige (endorsement received, one attribution at a time), local structure (the shape of a channel's immediate citation neighbourhood), community role, and behavioural ratios read from the message ledger. Those are the measures documented below.

### Measures deliberately not computed

The measures in this list are established, well-validated instruments — on data that records what they assume: conversations, collaborations, hyperlink browsing, physical proximity. Pulpit leaves them out not as a judgement on the measures, nor on the research traditions built on them, but as a matter of fit: forward attribution produces a graph whose paths are chains of *attribution*, and these instruments answer questions about chains of *transmission*. Where assumption and data part ways the number still computes — it just no longer means what its literature validated. Listing the absences, with reasons, saves every future reader the "where is betweenness?" question:

| Not computed | What it assumes about the ties | Why that does not hold here |
| :--- | :--- | :--- |
| **Betweenness centrality** (and its flow, current-flow, and load variants) | Traffic transits *through* intermediaries along paths, so standing between others confers importance | A forward is attributed to the origin, never to a relay: nothing observable transits through anyone. Borgatti (2005) names the mismatch — betweenness models flow that moves by *transfer*, while forwarding replicates by *copying*. |
| **Closeness / harmonic centrality** | Short path distance means reaching, or being reached, sooner | Multi-hop distances in an attribution graph correspond to no observed propagation: a channel two steps away never received anything *through* the channel between them. |
| **Gould–Fernandez brokerage census** | Every A→B→C two-path is a transaction that B relays | Formally a constrained 2-betweenness (Borgatti & Everett 2006), so it inherits the transfer assumption. The positional *concept* survives in the [vacancy analysis](vacancy-analysis.md)'s **brokerage overlap**, which claims position, not mediation. |
| **Eigenvector and Katz centrality** | Recursive prestige — sound for this graph, like PageRank | Excluded for redundancy and stability rather than semantics: on sparse directed graphs eigenvector centrality concentrates on the strongly connected core and zeroes much of the network, and Katz's attenuation α must be re-tuned per export (Bonacich 1987). PageRank covers the same prestige family with neither pathology. |
| **k-shell / coreness as a "super-spreader" score** | Deep-core nodes seed the largest cascades (Kitsak *et al.* 2010) | The spreader claim presupposes a transmission process — and falters even on genuine transmission networks when core-like groups are present (Liu, Tang & Zhou 2015). The decomposition itself, read as *structure*, remains available as the [K-core community strategy](community-detection.md#k-core). |
| **Spreading-model rankings** (SIR spreading efficiency, VoteRank, collective influence) | An explicit contagion process runs along the edges | No contagion process is observed; simulating one over attribution edges would rank channels by a dynamic the data cannot exhibit. |
| **Structural virality** (Goel *et al.* 2016) | Diffusion trees can be reconstructed, so deep chains can be told from broadcast bursts | Telegram cascades are depth-1 stars by construction — every forward points at the origin — so the tree the measure needs is not recoverable. |
| **Follower counts as an importance score** | Audience size proxies influence | Subscriber totals are shown as context (the *Users* column) but never enter a ranking: nominal audience and realised amplification diverge routinely — the "million-follower fallacy" (Cha *et al.* 2010; full reference under [Amplification factor](#amplification-factor)). |

One nuance keeps the boundary honest in the other direction. A few *network-level* statistics on the [whole-network page](whole-network-statistics.md) are path-based (average path length, diameter, global efficiency). They are reported as **shape descriptors** of the citation topology — how compact, how fragmented — and are meant to be read comparatively across exports; none of them credits an individual channel for sitting on a path, which is where the one-degree constraint bites.

**References:**
- Bonacich, P. (1987) "Power and centrality: A family of measures." *American Journal of Sociology* 92(5):1170–1182. [doi:10.1086/228631](https://doi.org/10.1086/228631) — the β-attenuation family containing eigenvector and Katz prestige, and its parameter dependence.
- Borgatti, S.P. (2005) "Centrality and network flow." *Social Networks* 27(1):55–71. [doi:10.1016/j.socnet.2004.11.008](https://doi.org/10.1016/j.socnet.2004.11.008) — betweenness assumes traffic that *moves/transfers* along geodesics, and is "completely inappropriate" as an index for infection or information that *diffuses by copying*.
- Borgatti, S.P. & Everett, M.G. (2006) "A graph-theoretic perspective on centrality." *Social Networks* 28(4):466–484. [doi:10.1016/j.socnet.2005.11.005](https://doi.org/10.1016/j.socnet.2005.11.005) — "Gould and Fernandez (1989) develop brokerage measures that are specific variants of 2-betweenness measures."
- Goel, S., Anderson, A., Hofman, J. & Watts, D.J. (2016) "The structural virality of online diffusion." *Management Science* 62(1):180–196. [doi:10.1287/mnsc.2015.2158](https://doi.org/10.1287/mnsc.2015.2158) — virality as depth-versus-breadth of the reconstructed diffusion tree.
- Kitsak, M. *et al.* (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6:888–893. [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746) — the core-equals-spreader claim the k-shell row refers to.
- Kuznetsov, O. *et al.* (2026) "Delay-driven information diffusion in Telegram: modeling, empirical analysis, and the limits of competition." *Big Data and Cognitive Computing* 10(1):30. [doi:10.3390/bdcc10010030](https://doi.org/10.3390/bdcc10010030) — 5,000+ Pushshift cascades form perfect depth-1 stars (zero multi-hop propagation), an API-forced property of forward attribution, vs. Twitter chains of depth 5+.
- Liu, Y., Tang, M. & Zhou, T. (2015) "Core-like groups result in invalidation of identifying super-spreader by k-shell decomposition." *Scientific Reports* 5:9602. [doi:10.1038/srep09602](https://doi.org/10.1038/srep09602) — in networks with "core-like groups", high-k-shell nodes are *not* good spreaders, breaking the Kitsak et al. (2010) core-equals-spreader claim.

---

## Quick reference

| Measure | CLI key | Question it answers |
| :------ | :------ | :------------------ |
| PageRank | `PAGERANK` | Which channels do the network's key players treat as authoritative? |
| HITS Hub | `HITSHUB` | Which channels actively amplify others — the distributors? |
| HITS Authority | `HITSAUTH` | Which channels are the original sources that distributors spread? |
| In-degree centrality | `INDEGCENTRALITY` | Which channels are cited by the largest fraction of others? |
| Out-degree centrality | `OUTDEGCENTRALITY` | Which channels cite the largest fraction of others? |
| Burt's constraint | `BURTCONSTRAINT` | Which channels bridge structural holes between otherwise separate groups? |
| Local clustering | `LOCALCLUSTERING` | Do this channel's contacts also cite each other — is its immediate neighbourhood closed in on itself? |
| Within-module role | `MODULEROLE` | Is this channel a within-community hub or a cross-community connector? |
| Amplification factor | `AMPLIFICATION` | Whose content spreads furthest relative to its output volume? |
| Content originality | `CONTENTORIGINALITY` | Which channels produce original content vs. redistribute others'? |
| Diffusion lag | `DIFFUSIONLAG` | When this channel forwards a narrative, is it an early adopter or a late amplifier? |

For the familiar measures deliberately *not* in this table — betweenness and its relatives — see [Measures deliberately not computed](#measures-deliberately-not-computed) above; for how the columns are meant to be read together, see [Reading the battery as a whole](#reading-the-battery-as-a-whole) at the end.

<figure>
<img src="../webapp_engine/static/screenshot_05.jpg" alt="Measure comparison scatter plot">
<figcaption><em>Measure comparison: drag any two measures onto the axes to compare their distributions across channels.</em></figcaption>
</figure>
<br>

---

## PageRank

*A channel scores high when other influential channels amplify it — being cited by a giant counts for more than being cited by many small accounts.*

PageRank measures prestige by propagation. Instead of simply counting citations, it asks who the citers are: a forward from a channel that is itself heavily forwarded counts for more than one from a channel nobody listens to. The score is set self-consistently across the whole network, so prestige flows from the most-cited channels back through the network's main relay layers, settling on the channels that the ecosystem's own key players treat as authoritative.

**References:**
- Brin, S. & Page, L. (1998) "The anatomy of a large-scale hypertextual web search engine." *Computer Networks and ISDN Systems* 30(1–7). [doi:10.1016/S0169-7552(98)00110-X](https://doi.org/10.1016/S0169-7552(98)00110-X)
- Pinski, G. & Narin, F. (1976) "Citation influence for journal aggregates of scientific publications: Theory, with application to the literature of physics." *Information Processing & Management* 12(5):297–312. [doi:10.1016/0306-4573(76)90048-0](https://doi.org/10.1016/0306-4573(76)90048-0) — the recursive citation-prestige fixed point that PageRank later popularised; the citation-network reading Pulpit relies on.

**In practice:** PageRank identifies the channels that *the rest of the network's leading channels* treat as authoritative — the ideological reference points of the ecosystem, even when their subscriber counts are modest. It complements raw citation counts, which can be inflated by attention from peripheral accounts that themselves carry no weight.

**Example.** In a network of nationalist Telegram channels, PageRank typically surfaces the two or three outlets whose framing and narratives are picked up and redistributed by everyone else — the ecosystem's ideological anchors. A small commentary channel with 4,000 subscribers can rank above a 50,000-subscriber party channel if it is the one the network's main aggregators forward most often. Subscriber size says little; PageRank reads who *the influential channels themselves* listen to.

**Caveats:** two reading notes. *(1)* PageRank is a **prestige** score, not a diffusion forecast. The walk it sums is a chain of attributions, so what it aggregates is recursive endorsement — who the well-cited cite — and that is the entire claim; where content will travel next is not part of it. This is the original citation-analysis reading (Pinski & Narin 1976), and it is exactly the reading that survives the one-degree model. *(2)* The ranking does not change across the three weighted `--edge-weight-strategy` options: `TOTAL`, `PARTIAL_MESSAGES` and `PARTIAL_REFERENCES` scale each amplifier's outgoing weights by a per-amplifier constant, and PageRank re-normalises every channel's outgoing weights to sum to 1 anyway, so the constants cancel. Only `NONE` (unweighted) yields a different PageRank.

---

## HITS Hub score

*A high hub score flags a channel that actively redistributes other people's content — a distributor, not a producer.*

The HITS algorithm splits influence into two roles: *hubs* (channels that distribute) and *authorities* (channels whose content gets distributed). The two are defined together: a channel scores high as a hub when the channels it forwards from are recognised authorities, and as an authority when the channels that forward it are recognised hubs. This separates the question of "who produces?" from "who spreads?", which a single prestige score cannot do.

**References:**
- Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140)

**In practice:** Hub score is Pulpit's answer to *who are the distributors?* — the relay channels that shape what the rest of the ecosystem sees. A high hub score combined with low content originality is the signature of a pure aggregator: a channel whose subscribers are exposed to a curated stream of other channels' content. Removing such a channel severs many citation relationships at once without silencing any original source.

**Example.** A daily-digest aggregator with 8,000 subscribers forwards from twenty consistently-cited commentators in a far-right Telegram ecosystem. PageRank places it mid-pack because few channels cite *it back*, and its own citation count looks unremarkable. But its hub score is the highest in the network — its outgoing forwards land precisely on the channels everyone else treats as authoritative. Read alongside PageRank, this correctly identifies the channel as the ecosystem's main redistribution layer, not just another commentator.

**Caveats:** dead-leaf channels score exactly 0 — only their *received* citations are in scope, so they have no outgoing edges by construction; a zero hub score on a dead leaf is a boundary fact, not a finding. Unlike PageRank, hub scores also respond to `--edge-weight-strategy`: under the `PARTIAL_*` strategies each amplifier's outgoing votes are scaled by its own output, which deliberately keeps hyperactive channels from dominating on volume alone.

---

## HITS Authority score

*A high authority score means this channel is one of the original sources the network's main distributors choose to spread.*

Authority is the counterpart to hub in the same Kleinberg system: a channel scores high as an authority when the channels that cite it are themselves recognised hubs. Where PageRank rewards being cited by anyone with high prestige, authority specifically rewards being cited by *good distributors*. The two need not agree — a channel can rank high on PageRank because of broad citation patterns, yet rank lower on authority because the citers, while many, are not the main relays of the ecosystem.

**References:**
- Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140)
- Lempel, R. & Moran, S. (2001) "SALSA: The stochastic approach for link-structure analysis." *ACM Transactions on Information Systems* 19(2):131–160. [doi:10.1145/382979.383041](https://doi.org/10.1145/382979.383041) — identifies the tightly-knit-community effect in HITS-style mutual reinforcement (see caveats below).

**In practice:** Authority is the prestige-side answer to *who is the source?* The most informative use is together with Hub: the pair gives a two-axis snapshot of the network's producer/distributor structure. A channel high on authority but middling on PageRank is a niche source the broader network reaches only through the distribution layer — the kind of source moderation rules typically target.

**Example.** A political strategist's channel with 5,000 subscribers ranks as the top authority in a network because fifteen high-traffic aggregator channels — themselves top-ten hubs — forward its posts daily. Subscriber count would lead an analyst to ignore it; PageRank ranks it high but not first; authority puts it at the top because the channels citing it are precisely those with the highest hub scores. Together with the daily-digest aggregator from the Hub example, this is the canonical producer/distributor pair: one is mostly cited, the other mostly cites.

**Caveats:** HITS concentrates. The hub and authority scores form the leading eigenvector of a mutual-reinforcement system, and on graphs with pronounced community structure that eigenvector can localise in the densest cluster — the *tightly-knit community* effect (Lempel & Moran 2001) — leaving well-cited channels in other clusters with scores near zero. Rankings *within* one community are trustworthy; small differences *across* communities are not. Corroborate any cross-community comparison with PageRank and in-degree, which do not localise this way.

---

## In-degree centrality

*The simplest prestige measure: what fraction of the network's other channels cite this one?*

In-degree centrality counts how many distinct channels cite or forward from a given channel, divided by the maximum possible (the number of other channels in the network). It is the most direct prestige measure available: no random walks, no iteration, just a count of citers normalised for network size. The score ignores how often each citer cites — a channel cited once by ten others has the same in-degree as one cited a hundred times by the same ten.

**References:**
- Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7)
- Costenbader, E. & Valente, T.W. (2003) "The stability of centrality measures when networks are sampled." *Social Networks* 25(4):283–307. [doi:10.1016/S0378-8733(03)00012-1](https://doi.org/10.1016/S0378-8733(03)00012-1) — degree-type measures are the most stable under sampling.
- Borgatti, S.P., Carley, K.M. & Krackhardt, D. (2006) "On the robustness of centrality measures under conditions of imperfect data." *Social Networks* 28(2):124–136. [doi:10.1016/j.socnet.2005.05.001](https://doi.org/10.1016/j.socnet.2005.05.001) — degree degrades most gracefully as nodes and edges go missing.

**In practice:** In-degree answers the most direct prestige question Pulpit can ask: *which channels are the most-cited sources?* The informative use is together with PageRank or HITS Authority — a channel high on in-degree but middling on PageRank is *broadly* cited, often by peripheral accounts, whereas a channel high on PageRank but middling on in-degree is cited *selectively* by the network's main hubs. The two together separate "popular" from "prestigious".

**Example.** The official channel of a political party often tops the in-degree ranking — it is a routine reference point for many small accounts across the network. Its PageRank may be only middling, however, because most citations come from peripheral channels that themselves carry little prestige. A second channel — say, a strategist's commentary feed with much lower in-degree — may sit higher on PageRank because the few channels that cite it are precisely the network's main hubs. In-degree identifies the most-named channel; PageRank reveals which of the two is *strategically* central.

**Caveats:** mostly the reassuring kind. Degree-type scores are consistently the most stable centralities when network data is incomplete or sampled (Costenbader & Valente 2003; Borgatti, Carley & Krackhardt 2006) — and crawled Telegram data is always somewhat incomplete: deleted messages and channels take their citations with them, and forwards whose origin cannot be resolved (hidden or vanished senders) are lost. When coverage is in doubt, in-degree is the score to trust first; the subtler measures refine its picture and should not overturn it without a reason you can articulate.

---

## Out-degree centrality

*The simplest expansiveness measure: what fraction of the network's other channels does this one cite?*

Out-degree centrality is the mirror image of in-degree: it counts how many distinct channels a given channel forwards from or references, divided by the maximum possible. It measures *expansiveness* — how widely a channel casts its citation net — independent of how often it cites each source. A channel forwarding from ten sources once each has the same out-degree as one forwarding from those same ten sources a hundred times each.

**References:**
- Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7)

**In practice:** Out-degree answers the dual question to in-degree: *which channels cast the widest net?* Paired with in-degree, it gives the classical role classification: pure producers (high in, low out), pure distributors (high out, low in), true hubs (high on both), and peripheral leaves (low on both). It is the simplest way Pulpit can sort channels into roles from raw citation counts alone.

**Example.** A daily-digest aggregator that links to thirty distinct sources each day routinely tops the out-degree ranking — its outgoing references fan across a large fraction of the network. Its in-degree is often low (few channels cite a curator back), so the pair clearly labels it as a distributor. A second channel — an opinion writer with much lower out-degree — forwards from only five sources, but those five are the network's most-cited authorities. Out-degree identifies the digest as the broadest amplifier; the comparison with HITS Hub reveals that the opinion writer's narrower citation pattern is the more strategically targeted one.

**Caveats:** out-degree is under the channel's own control. It records chosen behaviour — how widely a channel decides to cite — not recognition conferred by others, so read it as a role descriptor rather than a standing: a channel can raise its own out-degree at will, which is precisely what no channel can do to its in-degree. The same asymmetry applies to out-strength and, inversely, to content originality.

---

## Burt's constraint

*A low Burt's constraint score means this channel sits at a structural hole — its contacts cluster into groups that do not interact, so it is the only bridge between them.*

Burt's constraint quantifies how much of a channel's interaction is invested in contacts that already interact with each other — a measure of *ego-network redundancy*. A channel whose contacts all cite each other has high constraint: its information environment is closed in on itself. A channel whose contacts are mutually disconnected has low constraint: it sits at a *structural hole*, the only direct path between otherwise-separated groups. The framework is Burt's; its transposition to citation data deserves one precision. In Burt's original interpersonal setting, structural holes confer information and control advantages — the broker decides what crosses the gap. A citation graph records no flow for anyone to gate, so Pulpit's reading is strictly **positional**: a low-constraint channel maintains a *non-redundant citation portfolio* — its contacts sit in parts of the ecosystem that do not otherwise cite each other. The score certifies that position; what the channel does with it is the analyst's question.

**References:**
- Burt, R.S. (1992) *Structural Holes: The Social Structure of Competition*. Harvard University Press. [doi:10.4159/9780674038714](https://doi.org/10.4159/9780674038714)

**In practice:** Burt's constraint catches brokers that prestige measures can miss. A small channel connecting two otherwise-disconnected, low-traffic clusters can have an unremarkable in-degree yet very low constraint — its handful of contacts simply do not talk to each other. Paired with local clustering, it gives the canonical structural-holes-vs-echo-chamber decomposition.

**Example.** In a mapped Italian political network, a channel with modest PageRank and a few thousand subscribers has a Burt's constraint of 0.08 — the lowest in the network. Investigation reveals it is run by a political operative who curates content from both far-right and religious-nationalist ecosystems, forwarding selectively to each. Its in-degree is unremarkable, but its contacts on each side do not cite each other. Burt's constraint flags this channel as a structural broker while every prestige column reads unremarkable; when the two ecosystems fall into different communities under the chosen partition, the [within-module role](#within-module-role) will usually corroborate with a *Connector* label.

**Caveats:** three reading notes. *(1)* Low-degree egos are degenerate: with a single contact, constraint is maximal by construction, and with two or three contacts the score is coarse — the measure is most informative for channels with several contacts, so keep the degree columns in view when sorting by it. *(2)* Boundary bias: dead-leaf contacts never show ties among themselves (their own messages are out of scope), so a channel whose contacts are mostly out-of-target can appear to span holes that the wider Telegram graph might close. Constraint is most trustworthy for channels whose neighbourhood lies inside the target. *(3)* The score responds to `--edge-weight-strategy`, since the proportional investments *p* are computed from edge weights.

---

## Local clustering

*A high local clustering score means this channel's immediate neighbourhood is closed in on itself — its contacts also cite each other, forming tight mutual-amplification triangles.*

Local clustering measures the density of citations *among a channel's contacts*: how many of the channel's neighbours also cite each other directly. A score of 1 means every pair of the channel's contacts is connected; a score of 0 means none are. It captures the difference between a channel sitting inside a tight echo chamber (where all contacts mutually amplify each other) and one drawing from a diverse, unconnected set of sources.

**References:**
- Fagiolo, G. (2007) "Clustering in complex directed networks." *Physical Review E* 76(2), 026107. [doi:10.1103/PhysRevE.76.026107](https://doi.org/10.1103/PhysRevE.76.026107)
- Watts, D.J. & Strogatz, S.H. (1998) "Collective dynamics of 'small-world' networks." *Nature* 393(6684). [doi:10.1038/30918](https://doi.org/10.1038/30918)

**In practice:** Local clustering pinpoints channels embedded in mutual-amplification triangles — the footprint a tight cell leaves in the citation graph. No other Pulpit measure singles out this pattern: a five-channel cell can look unremarkable on every prestige column yet have local clustering near 1.0 across all five members. One caution on the word *cell*: closed triangles establish cohesion, not intent. Ideologically aligned channels produce the same shape organically, and a static citation graph records no timing — so whether the cohesion is spontaneous affinity or deliberate arrangement has to be settled at the message level (synchrony, ordering, who consistently boosts whom), not from this score alone — that follow-up is exactly what the [coordination analysis](coordination-analysis.md) operationalises. Clustering's job is to hand the analyst the right candidates. Paired with Burt's constraint, it gives the canonical structural-holes-vs-echo-chamber decomposition.

**Example.** In a mapped extremist-channel ecosystem, five channels all cross-forwarding each other show up with local clustering between 0.6 and 0.8 per member — even though three of them have low PageRank and unremarkable citation counts, so none of the global-prestige measures flag them. By contrast, a mainstream news aggregator drawing from twelve unrelated sources (a national newswire, an academic blog, a sports outlet, a foreign-policy magazine, and so on) scores near 0 on clustering: its sources do not cite each other.

**Caveats:** clustering falls mechanically with degree — a hub with two hundred contacts almost cannot score high, while a three-contact channel easily does — so compare channels of similar degree rather than ranking the raw column network-wide. The dead-leaf boundary bias applies here as the mirror image of Burt's constraint: ties among out-of-target contacts are out of scope, so neighbourhoods at the target boundary read as more open (lower clustering) than they may really be.

---

## Within-module role

*Is this channel a hub inside its own community, a bridge between communities, or a peripheral member? The within-module role names the position directly, on top of any community partition.*

The within-module role characterises every channel by two scores measured *against its own community*: one for internal embeddedness (how unusually well-connected the channel is *within* its community), and one for cross-community reach (how broadly the channel's contacts spread *across* communities). These two scores are collapsed into seven canonical labels — from *ultra-peripheral* (a channel that barely interacts outside its own community) to *connector hub* (a channel that is both internally central and spans communities widely).

**References:**
- Guimerà, R. & Amaral, L.A.N. (2005) "Functional cartography of complex metabolic networks." *Nature* 433(7028). [doi:10.1038/nature03288](https://doi.org/10.1038/nature03288)

**In practice:** The role labels turn a coloured-blob community map into a concrete job description: a *provincial hub* is a kingpin of one community that rarely speaks outside it; a *connector hub* is both central within and spanning out, the most strategically significant broker; a non-hub *connector* is a low-profile bridge with modest internal weight but ties that systematically cross community boundaries. The label pairs naturally with global prestige measures: a top-decile PageRank channel can be either a *provincial hub* (locally dominant but not network-spanning) or a *connector hub* (both), and the label tells you which.

**Example.** In a 400-channel political ecosystem, two channels look nearly identical on the static prestige columns — comparable PageRank, similar citation strength. The role taxonomy separates them. The first lands as a *connector hub* — both internally central in its community *and* with ties that span multiple distinct communities. The second is a *provincial hub* — the kingpin of its own community, but with ties that do not systematically cross out. Reading PageRank alone, the two look like equivalent leaders; reading the role labels, they are different jobs. Removing the first severs both internal cohesion and the cross-community ties it carried; removing the second only fragments one community.

**Caveats:** the seven labels are conventions, not measurements. The z/P thresholds behind them come from the original study's calibration on metabolic networks (Guimerà & Amaral 2005) and have travelled to social networks as *useful bins* rather than validated cut-points — so sort and reason with the continuous `within_module_z` column, read the labels as a legend, and treat a channel near a threshold as near it. Roles are also relative to the chosen basis partition: a different community strategy can assign different roles (strategies are seeded, so identical re-runs agree). And in very small or degree-uniform communities the z-score degenerates to 0 — a five-channel community cannot produce a meaningful within-module hub.

---

## Amplification factor

*How many times each of this channel's messages is re-broadcast, on average, by other channels in the network — a per-post measure of intra-network virality.*

Amplification factor is the ratio of *forwarding events received* to *messages produced*: if a channel publishes 200 messages and other channels in the network forward those messages a combined 800 times, the score is 4.0. A value of 1.0 means each post is, on average, re-broadcast once somewhere in the network; values above 1 mean the network forwards the channel's output faster than the channel produces it. The measure reads off raw forwarding activity, so it captures behavioural reach rather than structural position.

**References:**
- Bakshy, E., Hofman, J.M., Mason, W.A. & Watts, D.J. (2011) "Everyone's an influencer: quantifying influence on Twitter." *WSDM '11*. [doi:10.1145/1935826.1935845](https://doi.org/10.1145/1935826.1935845)
- Cha, M., Haddadi, H., Benevenuto, F. & Gummadi, K.P. (2010) "Measuring user influence in Twitter: the million follower fallacy." *ICWSM 2010*. [link](https://ojs.aaai.org/index.php/ICWSM/article/view/14033)

**In practice:** Amplification factor is the most direct Pulpit measure of *whose voice carries the furthest, post for post*. Paired with content originality, it sorts channels into four roles: high amplification + high originality = a primary source whose content travels (usually the most consequential channel for an analyst); high originality + low amplification = an original niche nobody re-broadcasts; low originality + high amplification = an aggregator whose curated forwards are themselves re-amplified; low on both = a passive consumer.

**Example.** In an analyst's target ecosystem, a commentary channel with 3,000 subscribers publishes 200 detailed messages; ten mainstream aggregators forward it regularly, producing 850 forwarding events. Its amplification factor is 4.25 — each post is, on average, re-broadcast more than four times. A political party's official channel with 50,000 subscribers publishes 1,200 messages, but only a handful of small accounts forward them, totalling 220 events — score 0.18, so most party messages never leave their own audience. Subscriber count would rank the party channel first; amplification factor reverses the ordering and correctly identifies the commentator as the network's most-amplified voice on a per-post basis.

**Caveats:** a ratio with a small denominator is volatile — a channel that posted a handful of messages and landed one viral hit can top this column. Read it alongside *Messages* and *In-strength*: high amplification on a large output is the strong signal; high amplification on ten posts is an anecdote. Channels with no in-window messages of their own (dead leaves in particular) show 0.0, which means "no measurable output", not "ignored".

---

## Content originality

*The share of a channel's posts that are not forwards from someone else — a simple producer-vs-redistributor measure.*

Content originality is the fraction of a channel's own messages that are not native Telegram forwards. A score of 1.0 means everything the channel publishes is original; 0.0 means everything is a forward; intermediate values give the production-to-redistribution mix. The score reads off the channel's own publishing ledger — not the citation network around it — so it is independent of structural choices that change other measures, and it can be read on its own.

**References:**
- Boyd, D., Golder, S. & Lotan, G. (2010) "Tweet, Tweet, Retweet: Conversational Aspects of Retweeting on Twitter." *HICSS-43*. [doi:10.1109/HICSS.2010.412](https://doi.org/10.1109/HICSS.2010.412)
- Kwak, H., Lee, C., Park, H. & Moon, S. (2010) "What is Twitter, a Social Network or a News Media?" *WWW 2010*. [doi:10.1145/1772690.1772751](https://doi.org/10.1145/1772690.1772751)

**In practice:** Content originality is Pulpit's most direct answer to *whose voice is genuinely original, post-for-post, and whose is curatorial?* It is the behavioural counterpart to the structural measures. Paired with amplification factor it spans four roles — primary source whose content travels (high on both), original niche (high originality, low amplification), curated aggregator (low originality, high amplification), and passive consumer (low on both).

**Example.** A commentary outlet that publishes its own analyses emits 600 messages over the analysis window, 30 of which are forwards from peer channels — originality score 0.95: almost every post is original, with a thin layer of curated forwards. A content aggregator on the same topics emits 800 messages, 720 of which are forwards from a handful of sources — originality 0.10: by volume, almost all content is other people's. Subscriber count might rank the aggregator first, but originality flips the framing: the first channel is the local *producer*, the second the local *amplifier*.

**Caveats:** the score counts native Telegram forwards only, so it is an *upper bound* on originality: text copied without the forward header, screenshots of other channels' posts, and re-uploads all read as original content, and a `t.me` reference does not lower the score either (a post that links another channel is still an original post). Republication that bypasses the forward mechanic is invisible to this measure — as it is to the citation graph itself.

---

## Diffusion lag

*The median time a channel waits before re-broadcasting someone else's content — a timing signature that separates early adopters from late amplifiers.*

Diffusion lag is the median number of hours between when a piece of content is first published and when a given channel forwards it. Channels with low lag are *early adopters* — fast-reacting in the network's content cycle; channels with high lag are *late amplifiers* — picking up content well after it has circulated. The median is used instead of the mean because waiting times follow a heavy-tailed distribution where a few extremely delayed forwards would otherwise dominate the average.

**References:**
- Vosoughi, S., Roy, D. & Aral, S. (2018) "The spread of true and false news online." *Science* 359(6380). [doi:10.1126/science.aap9559](https://doi.org/10.1126/science.aap9559)
- Iribarren, J.L. & Moro, E. (2009) "Impact of human activity patterns on the dynamics of information diffusion." *Physical Review Letters* 103(3), 038702. [doi:10.1103/PhysRevLett.103.038702](https://doi.org/10.1103/PhysRevLett.103.038702)

**In practice:** Diffusion lag answers a question no structural measure can: *when* does a channel typically react? It is the temporal companion of the volume and position measures. Paired with amplification factor, it splits forwarders into agenda-setters (low lag, high amplification — fast and well-amplified), consolidators (high lag, high amplification — slow takes that still travel), followers (low lag, low amplification — quick but unheard), and peripheral re-broadcasters (high lag, low amplification). The dimension is invisible to any static-graph measure.

**Example.** Two channels in a nationalist commentator network each forward roughly 60% of a primary broadcaster's posts, with comparable in-degree. One has a diffusion lag of 1.8 hours, the other 17. On every static and behavioural-volume measure they look interchangeable; temporally they are not. The first is part of the broadcaster's same-day distribution chain — an agenda-setter that extends the broadcaster's news window. The second re-broadcasts after the news cycle has moved on — a consolidator whose role is reinforcing narratives rather than seeding them.

**Caveats:** the references above validate *timing* as an analytical dimension; the per-channel median lag is Pulpit's own operationalisation of it, so read it as a role descriptor rather than a ranking of importance. The lag also conflates two things the data cannot separate — how fast a channel reacts to content it has seen, and how late it discovered that content. And the reaction window (default 30 days) deliberately right-censors archival re-shares: a channel that mostly resurfaces old material contributes few qualifying forwards rather than a huge median.

---

## Reading the battery as a whole

### Five dimensions, not eleven columns

The prestige columns — in-degree, in-strength, PageRank, HITS authority, amplification factor — all draw on the same underlying fact (*being cited*) and will usually correlate strongly. That is expected, not redundant: each refines the fact differently (breadth, intensity, endorser quality, distributor quality, per-post rate), and the **disagreements** between them are where a reading starts — broadly cited but not prestigious, prestigious but narrow, amplified beyond its size. Taken together the battery spans roughly five distinct dimensions:

1. **Conferred prestige** — in-degree, in-strength, PageRank, HITS authority, amplification factor
2. **Curatorial activity** — out-degree, out-strength, HITS hub, (low) content originality
3. **Portfolio structure** — Burt's constraint, local clustering
4. **Community role** — within-module z, module role
5. **Temporal signature** — diffusion lag

Treat the columns as five questions, not eleven independent verdicts. The measure-comparison scatter (drag two measures onto the axes) is the built-in tool for finding the informative disagreements.

### Which columns respond to `--edge-weight-strategy`

| Measure | Responds? | Why |
| :--- | :--- | :--- |
| PageRank | Only to `NONE` | The weighted strategies differ per amplifier by a constant factor, which PageRank's own out-weight normalisation removes |
| HITS hub & authority | Yes | Computed from raw weights, with no per-amplifier normalisation |
| In/out-degree centrality | No | Unweighted by definition: distinct partners |
| In/out-strength | Yes | Sums of raw weights |
| Burt's constraint | Yes | Proportional investments *p* come from weights |
| Local clustering | No | Unweighted triangle census |
| Within-module z / role | z: no; label: mildly | z counts distinct neighbours; the role's participation axis is weight-based |
| Amplification, originality, lag | No | Computed from the message ledger, not the graph |

### Coverage is a floor, not a census

Crawled Telegram data understates citation. Forwards whose sender hides its identity cannot be resolved to a source channel; deleted messages and deleted channels take their citations with them; private channels never enter. These losses are not uniform — a channel configured for stricter privacy sheds in-citations — so prestige scores are best read as **lower bounds**, and a difference between two channels' scores should be larger than the plausible coverage gap before it is treated as a finding. This is also why in-degree, the most missing-data-robust column (see its caveats), anchors the reading.

### Every score is boundary-relative

All measures are computed inside the analyst-defined in-target universe, plus its dead-leaf fringe. A channel's rank therefore answers "how important within *this* milieu, in *this* window" — never "how important on Telegram". Redrawing the boundary (label periods, date window, in-target flags) legitimately changes every score: the boundary is part of the research design, not a nuisance parameter (Laumann, Marsden & Prensky 1983).

**References:**
- Laumann, E.O., Marsden, P.V. & Prensky, D. (1983) "The boundary specification problem in network analysis." In Burt, R.S. & Minor, M.J. (eds) *Applied Network Analysis: A Methodological Introduction*. Sage.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">
