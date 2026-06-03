# Network measures

A network measure assigns a numerical score to each channel based on its position in the directed citation graph. Pulpit constructs edges from forwards and `t.me/` references: a directed edge from channel A to channel B means A regularly amplifies B's content, weighted by frequency relative to A's total output.

All measures can be used to size nodes in the graph viewer, making the most significant channels visually prominent.

> **Read this first.** Pulpit's edges record *one-degree* amplification — every forward is attributed to the original source, so a citation always points straight at the origin. That makes several otherwise-standard path- and flow-based measures (betweenness, spreading, trophic level, brokerage, bridging, …) invalid on this graph. See [Interpretation guardrails](#interpretation-guardrails-the-one-degree-assumption) for which measures to trust and which to avoid.

<figure>
<img src="../webapp_engine/static/screenshot_01.jpg" alt="Channel table with network measures">
<figcaption><em>Channel table: every computed measure as a sortable column. Click any header to rank channels by that measure.</em></figcaption>
</figure>
<br>

---

## Quick reference

| Measure | CLI key | Question it answers |
| :------ | :------ | :------------------ |
| PageRank | `PAGERANK` | Which channels do the network's key players treat as authoritative? |
| HITS Hub | `HITSHUB` | Which channels actively amplify others — the distributors? |
| HITS Authority | `HITSAUTH` | Which channels are the original sources that distributors spread? |
| Betweenness centrality | `BETWEENNESS` | Which channels sit on the bridges between sub-networks? |
| In-degree centrality | `INDEGCENTRALITY` | Which channels are cited by the largest fraction of others? |
| Out-degree centrality | `OUTDEGCENTRALITY` | Which channels cite the largest fraction of others? |
| Harmonic centrality | `HARMONICCENTRALITY` | Which channels does the rest of the network reach in the fewest hops? |
| Burt's constraint | `BURTCONSTRAINT` | Which channels bridge structural holes between otherwise separate groups? |
| Local clustering | `LOCALCLUSTERING` | Do this channel's contacts also cite each other — is its immediate neighbourhood closed in on itself? |
| K-core coreness | `CORENESS` | Is this channel in the densely interconnected nucleus, or a peripheral amplifier? |
| Collective influence | `COLLECTIVEINFLUENCE` | Which channels are the optimal-percolation key spreaders whose removal most fragments the network? |
| Trophic level | `TROPHICLEVEL` | Where does this channel sit on the structural source→sink axis? |
| Within-module role | `MODULEROLE` | Is this channel a within-community hub or a cross-community connector? |
| Brokerage roles | `BROKERAGEROLES` | What kind of broker is this channel between groups — gatekeeper, representative, liaison? |
| Amplification factor | `AMPLIFICATION` | Whose content spreads furthest relative to its output volume? |
| Content originality | `CONTENTORIGINALITY` | Which channels produce original content vs. redistribute others'? |
| Diffusion lag | `DIFFUSIONLAG` | When this channel forwards a narrative, is it an early adopter or a late amplifier? |
| Spreading efficiency | `SPREADING` | If this channel starts spreading a message, what fraction of the network eventually receives it? |
| Bridging centrality | `BRIDGINGCENTRALITY` | Which channels are topological bridges wedged between high-degree regions? |
| Community bridging | `BRIDGING` / `BRIDGING(STRATEGY)` | Which channels bridge distinct communities AND lie on structurally important paths? |

<figure>
<img src="../webapp_engine/static/screenshot_05.jpg" alt="Measure comparison scatter plot">
<figcaption><em>Measure comparison: drag any two measures onto the axes to compare their distributions across channels.</em></figcaption>
</figure>
<br>

---

## Interpretation guardrails: the one-degree assumption

Pulpit's edges encode one narrow fact: **channel X amplified channel Y's content at least once** (a forward, or a `t.me/` reference). Telegram attributes every forward to the *original* author, not the intermediate sharer — so when content travels A → B → C in the real world (C forwards what it saw on B, which B had taken from A), Telegram stamps C's copy as originating from A. Pulpit therefore records the edges **B→A** and **C→A**, and *never* C→B. Amplification is **one degree only**: every citation points straight at the origin.

That single fact has a sharp consequence — **the graph's paths are not diffusion paths, and the two are in fact disjoint:**

- A *real* diffusion chain A → B → C collapses to a star — edges B→A and C→A, with B and C left unconnected. The multi-hop chain disappears from the topology.
- A directed 2-path that *does* appear in the graph, X→Y→Z, can only mean "X amplified Y's *own* content **and** Y amplified Z's *own* content" — two unrelated content streams. If X had received Z's content *through* Y, the edge would read X→Z. So Y relays nothing between X and Z.

In short: genuine multi-hop diffusion is **absent** from the graph (flattened into stars), while the multi-hop paths that are **present** carry no transmission meaning. This is precisely Borgatti's warning that every centrality presupposes a particular flow process and is valid only when the real process matches it (Borgatti 2005, *Centrality and network flow*; Borgatti & Everett 2006). One-degree amplification fixes that process as **single-step broadcast duplication** — and in the Borgatti–Everett typology, *volume / degree* measures survive it while *length* (closeness/harmonic) and *medial* (betweenness) measures do not.

### Verdict by measure

| Measure | Verdict | Why under one-degree |
| :------ | :------ | :------------------- |
| In-degree centrality (`INDEGCENTRALITY`) | **Valid** | One-degree attribution makes in-degree (and the `in_deg` in-strength) *the* canonical influence index — every amplifier of your content points directly at you. |
| Out-degree centrality (`OUTDEGCENTRALITY`) | **Valid** | Curatorial breadth; a direct one-step count, no path assumption. |
| Amplification factor (`AMPLIFICATION`) | **Valid** | Local content ratio (forwards received ÷ own output). |
| Content originality (`CONTENTORIGINALITY`) | **Valid** | Local content ratio. |
| Diffusion lag (`DIFFUSIONLAG`) | **Valid** | Built from forward timestamps — direct events; reads as latency relative to the origin. |
| Within-module role (`MODULEROLE`) | **Valid** | Degree distribution across communities — connection diversity, not flow mediation. |
| PageRank (`PAGERANK`) | **Structural only** | Defensible as recursive citation *prestige* ("endorsed by the much-endorsed"); do **not** read it as reach or flow. |
| HITS hub / authority (`HITSHUB` / `HITSAUTH`) | **Structural only** | Co-citation / coupling structure → curator (hub) / source (authority) roles; endorsement, not transmission. |
| Burt's constraint (`BURTCONSTRAINT`) | **Structural only** | Ego-network redundancy is real and local; the "broker controls flow across the hole" gloss is weakened. |
| Local clustering (`LOCALCLUSTERING`) | **Structural only** | Measures transitive closure — the very thing one-degree denies as flow; survives only as a local-redundancy signal. |
| Harmonic centrality (`HARMONICCENTRALITY`) | **Undermined** | Reciprocal-distance reach over multi-hop paths; the 1-hop terms are just in-degree, the rest is fictitious reach. Prefer in-degree. |
| Collective influence (`COLLECTIVEINFLUENCE`) | **Undermined** | An optimal-percolation spreader score over a 2-hop ball; with no real spreading process its justification lapses (residue: a 2-hop-degree index). |
| K-core coreness (`CORENESS`) | **Undermined** | Fine as structural nestedness, but the Kitsak (2010) "best spreaders" claim it is sold on needs a spreading process the graph does not carry. |
| Betweenness (`BETWEENNESS`) | **Invalid** | Counts geodesic traffic through a node, but a graph 2-path is never a transmission route — the "broker controls flow" reading has no referent. |
| Spreading efficiency (`SPREADING`) | **Invalid** | Simulates a multi-generation SIR cascade; generations ≥ 2 are exactly what one-degree flattens into stars, so the cascade is an artefact. |
| Trophic level (`TROPHICLEVEL`) | **Invalid** | A flow-hierarchy coordinate (level = 1 + mean upstream level); with no multi-step flow, every level ≥ 1 is built from spurious 2-paths. |
| Brokerage roles (`BROKERAGEROLES`) | **Invalid** | Classifies 2-paths i→v→j as v brokering between i and j, but a brokered forward is attributed to the origin (edge i→j) — the census counts mediations that never happened. |
| Bridging centrality (`BRIDGINGCENTRALITY`) | **Invalid** | Betweenness × a degree-based bridging coefficient; inherits betweenness's missing flow referent. |
| Community bridging (`BRIDGING`) | **Invalid** | Betweenness × neighbour-community participation coefficient; same inheritance. |

### Reading the catalogue below

The quick-reference questions above and each measure's own section describe its **textbook** interpretation — written for a generic graph where paths carry flow. Where the verdict table marks a measure *Undermined* or *Invalid*, read that section as background on what the algorithm computes, **not** as a licence to read its flow / brokerage / spreading story into a Pulpit graph. The worked examples there illustrate the measure's general behaviour; they are not claims that the corresponding inference is sound under one-degree attribution.

### References vs. forwards

The argument is cleanest for forwards, where Telegram's original-author attribution is what flattens the chain. `t.me/` **references** have no intermediate-attribution step — a mention simply points at whoever is named. But a mention is still a one-step pointer, never a conduit: a reference 2-path (X mentions Y, Y mentions Z) transmits nothing from Z to X either. So the same conclusion holds for both edge types, by slightly different routes.

### The default measure set

Because of all this, the Operations-panel default selection ships only the surviving measures — the *Valid* and *Structural-only* tiers:

`PAGERANK`, `HITSHUB`, `HITSAUTH`, `INDEGCENTRALITY`, `OUTDEGCENTRALITY`, `BURTCONSTRAINT`, `LOCALCLUSTERING`, `MODULEROLE`, `AMPLIFICATION`, `CONTENTORIGINALITY`, `DIFFUSIONLAG`.

The *Undermined* and *Invalid* measures stay fully available — select them on the measure builder, or pass them to `--measures`, whenever you want them (for comparison, or if your reading of the data justifies relaxing the one-degree assumption). This default governs the **web form only**; a bare `structural_analysis` CLI run computes nothing unless you pass `--measures` explicitly.

---

## PageRank

*A channel scores high when other influential channels amplify it — being cited by a giant counts for more than being cited by many small accounts.*

PageRank measures prestige by propagation. Instead of simply counting citations, it asks who the citers are: a forward from a channel that is itself heavily forwarded counts for more than one from a channel nobody listens to. The score is set self-consistently across the whole network, so prestige flows from the most-cited channels back through the network's main relay layers, settling on the channels that the ecosystem's own key players treat as authoritative.

**References:**
- Brin, S. & Page, L. (1998) "The anatomy of a large-scale hypertextual web search engine." *Computer Networks and ISDN Systems* 30(1–7). [doi:10.1016/S0169-7552(98)00110-X](https://doi.org/10.1016/S0169-7552(98)00110-X)

**In practice:** PageRank identifies the channels that *the rest of the network's leading channels* treat as authoritative — the ideological reference points of the ecosystem, even when their subscriber counts are modest. It complements raw citation counts, which can be inflated by attention from peripheral accounts that themselves carry no weight.

**Example.** In a network of nationalist Telegram channels, PageRank typically surfaces the two or three outlets whose framing and narratives are picked up and redistributed by everyone else — the ecosystem's ideological anchors. A small commentary channel with 4,000 subscribers can rank above a 50,000-subscriber party channel if it is the one the network's main aggregators forward most often. Subscriber size says little; PageRank reads who *the influential channels themselves* listen to.

---

## HITS Hub score

*A high hub score flags a channel that actively redistributes other people's content — a distributor, not a producer.*

The HITS algorithm splits influence into two roles: *hubs* (channels that distribute) and *authorities* (channels whose content gets distributed). The two are defined together: a channel scores high as a hub when the channels it forwards from are recognised authorities, and as an authority when the channels that forward it are recognised hubs. This separates the question of "who produces?" from "who spreads?", which a single prestige score cannot do.

**References:**
- Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140)

**In practice:** Hub score is Pulpit's answer to *who are the distributors?* — the relay channels that shape what the rest of the ecosystem sees. A high hub score combined with low content originality is the signature of a pure aggregator: a channel whose subscribers are exposed to a curated stream of other channels' content. Removing such a channel fragments information flow across the network without silencing any original source.

**Example.** A daily-digest aggregator with 8,000 subscribers forwards from twenty consistently-cited commentators in a far-right Telegram ecosystem. PageRank places it mid-pack because few channels cite *it back*, and its own citation count looks unremarkable. But its hub score is the highest in the network — its outgoing forwards land precisely on the channels everyone else treats as authoritative. Read alongside PageRank, this correctly identifies the channel as the ecosystem's main redistribution layer, not just another commentator.

---

## HITS Authority score

*A high authority score means this channel is one of the original sources the network's main distributors choose to spread.*

Authority is the counterpart to hub in the same Kleinberg system: a channel scores high as an authority when the channels that cite it are themselves recognised hubs. Where PageRank rewards being cited by anyone with high prestige, authority specifically rewards being cited by *good distributors*. The two need not agree — a channel can rank high on PageRank because of broad citation patterns, yet rank lower on authority because the citers, while many, are not the main relays of the ecosystem.

**References:**
- Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140)

**In practice:** Authority is the prestige-side answer to *who is the source?* The most informative use is together with Hub: the pair gives a two-axis snapshot of the network's producer/distributor structure. A channel high on authority but middling on PageRank is a niche source the broader network reaches only through the distribution layer — the kind of source moderation rules typically target.

**Example.** A political strategist's channel with 5,000 subscribers ranks as the top authority in a network because fifteen high-traffic aggregator channels — themselves top-ten hubs — forward its posts daily. Subscriber count would lead an analyst to ignore it; PageRank ranks it high but not first; authority puts it at the top because the channels citing it are precisely those with the highest hub scores. Together with the daily-digest aggregator from the Hub example, this is the canonical producer/distributor pair: one is mostly cited, the other mostly cites.

---

## Betweenness centrality

*A high betweenness score means this channel sits on many of the shortest paths between other channels — a broker through which information flows.*

Betweenness counts the fraction of shortest paths between all pairs of channels that pass through a given channel. A channel with high betweenness is a structural broker: information moving from one part of the network to another tends to route through it. The measure rewards lying *between* clusters rather than being prominent *within* one, so it picks out very different channels from prestige measures like PageRank.

**References:**
- Freeman, L.C. (1977) "A set of measures of centrality based on betweenness." *Sociometry* 40(1). [doi:10.2307/3033543](https://doi.org/10.2307/3033543)

**In practice:** Betweenness is Pulpit's primary measure for finding the channels that hold a network together. A bridge between two ideological camps will score high even without high prestige within either — and prestige measures routinely miss these brokers because they may be cited by few and themselves cite many. Removing high-betweenness channels typically fragments the network faster than removing high-prestige ones.

**Example.** A channel regularly references both a cluster of religious nationalist outlets and a cluster of economic libertarian outlets — two groups that do not directly cross-reference. Its citation count is modest and its PageRank ordinary, because neither cluster cites it heavily. Yet every shortest path between the two ecosystems runs through it, so its betweenness is among the highest in the network. It is the main vector through which narratives migrate from one community to the other.

---

## In-degree centrality

*The simplest prestige measure: what fraction of the network's other channels cite this one?*

In-degree centrality counts how many distinct channels cite or forward from a given channel, divided by the maximum possible (the number of other channels in the network). It is the most direct prestige measure available: no random walks, no iteration, just a count of citers normalised for network size. The score ignores how often each citer cites — a channel cited once by ten others has the same in-degree as one cited a hundred times by the same ten.

**References:**
- Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7)

**In practice:** In-degree answers the most direct prestige question Pulpit can ask: *which channels are the most-cited sources?* The informative use is together with PageRank or HITS Authority — a channel high on in-degree but middling on PageRank is *broadly* cited, often by peripheral accounts, whereas a channel high on PageRank but middling on in-degree is cited *selectively* by the network's main hubs. The two together separate "popular" from "prestigious".

**Example.** The official channel of a political party often tops the in-degree ranking — it is a routine reference point for many small accounts across the network. Its PageRank may be only middling, however, because most citations come from peripheral channels that themselves carry little prestige. A second channel — say, a strategist's commentary feed with much lower in-degree — may sit higher on PageRank because the few channels that cite it are precisely the network's main hubs. In-degree identifies the most-named channel; PageRank reveals which of the two is *strategically* central.

---

## Out-degree centrality

*The simplest expansiveness measure: what fraction of the network's other channels does this one cite?*

Out-degree centrality is the mirror image of in-degree: it counts how many distinct channels a given channel forwards from or references, divided by the maximum possible. It measures *expansiveness* — how widely a channel casts its citation net — independent of how often it cites each source. A channel forwarding from ten sources once each has the same out-degree as one forwarding from those same ten sources a hundred times each.

**References:**
- Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7)

**In practice:** Out-degree answers the dual question to in-degree: *which channels cast the widest net?* Paired with in-degree, it gives the classical role classification: pure producers (high in, low out), pure distributors (high out, low in), true hubs (high on both), and peripheral leaves (low on both). It is the simplest way Pulpit can sort channels into roles from raw citation counts alone.

**Example.** A daily-digest aggregator that links to thirty distinct sources each day routinely tops the out-degree ranking — its outgoing references fan across a large fraction of the network. Its in-degree is often low (few channels cite a curator back), so the pair clearly labels it as a distributor. A second channel — an opinion writer with much lower out-degree — forwards from only five sources, but those five are the network's most-cited authorities. Out-degree identifies the digest as the broadest amplifier; the comparison with HITS Hub reveals that the opinion writer's narrower citation pattern is the more strategically targeted one.

---

## Harmonic centrality

*A high harmonic centrality score means the rest of the network can reach this channel through short citation chains — even when its direct citers are few, indirect ones via aggregators count.*

Harmonic centrality measures how easily the rest of the network reaches a channel through citation chains, with closer citers counting for more than distant ones: a direct citer contributes full weight, a two-hop citer half, a three-hop citer a third, and so on. It generalises in-degree from direct citers to all citers via multi-hop paths, and stays well-defined on the sparse, partially disconnected citation graphs Pulpit typically builds — channels that cannot be reached simply do not contribute.

**References:**
- Boldi, P. & Vigna, S. (2014) "Axioms for centrality." *Internet Mathematics* 10(3–4). [doi:10.1080/15427951.2013.865686](https://doi.org/10.1080/15427951.2013.865686)

**In practice:** Harmonic centrality picks up channels that are *deeply embedded* in the citation graph even when they are not cited by many direct citers — a small channel that the network's main aggregators cite, and which those aggregators are themselves widely cited, will score high. The difference with in-degree is informative: a channel can have modest in-degree but high harmonic centrality if its few citers each have wide audiences of their own. The pair separates "broadly cited" from "well-positioned in the citation chain".

**Example.** A political strategist's channel is cited directly by only three high-traffic aggregators — its in-degree is just 3. But each of those three aggregators is itself cited by twenty other channels in the same ecosystem, so the strategist is two hops from sixty more. Harmonic centrality picks up both the direct and the two-hop citers, so its score is much higher than in-degree alone suggests. A second channel cited directly by twenty peripheral accounts (none of which is itself cited) has a higher in-degree but a lower harmonic centrality — because nobody reaches it *through* anyone interesting.

---

## Burt's constraint

*A low Burt's constraint score means this channel sits at a structural hole — its contacts cluster into groups that do not interact, so it is the only bridge between them.*

Burt's constraint quantifies how much of a channel's interaction is invested in contacts that already interact with each other — a measure of *ego-network redundancy*. A channel whose contacts all cite each other has high constraint: its information environment is closed in on itself. A channel whose contacts are mutually disconnected has low constraint: it sits at a *structural hole*, the only direct path between otherwise-separated groups. The framework is Burt's: structural holes confer information and control benefits, because the broker decides what crosses the gap.

**References:**
- Burt, R.S. (1992) *Structural Holes: The Social Structure of Competition*. Harvard University Press. [doi:10.4159/9780674038714](https://doi.org/10.4159/9780674038714)

**In practice:** Burt's constraint catches brokers that betweenness can miss. Betweenness rewards lying on many shortest paths — a global signal that floods toward high-traffic hubs. A small channel connecting two otherwise-disconnected, low-traffic clusters can have negligible betweenness yet very low constraint — its handful of contacts simply do not talk to each other. The pair `(BETWEENNESS, BURTCONSTRAINT)` cleanly separates global flow brokers from quiet local ones.

**Example.** In a mapped Italian political network, a channel with modest PageRank and a few thousand subscribers has a Burt's constraint of 0.08 — the lowest in the network. Investigation reveals it is run by a political operative who curates content from both far-right and religious-nationalist ecosystems, forwarding selectively to each. Its in-degree is unremarkable and its betweenness is mid-pack (the two ecosystems it bridges are themselves small), but its contacts on each side do not cite each other. Burt's constraint is the only measure Pulpit reports that flags this channel as a structural broker.

---

## Local clustering

*A high local clustering score means this channel's immediate neighbourhood is closed in on itself — its contacts also cite each other, forming tight mutual-amplification triangles.*

Local clustering measures the density of citations *among a channel's contacts*: how many of the channel's neighbours also cite each other directly. A score of 1 means every pair of the channel's contacts is connected; a score of 0 means none are. It captures the difference between a channel sitting inside a tight echo chamber (where all contacts mutually amplify each other) and one drawing from a diverse, unconnected set of sources.

**References:**
- Fagiolo, G. (2007) "Clustering in complex directed networks." *Physical Review E* 76(2), 026107. [doi:10.1103/PhysRevE.76.026107](https://doi.org/10.1103/PhysRevE.76.026107)
- Watts, D.J. & Strogatz, S.H. (1998) "Collective dynamics of 'small-world' networks." *Nature* 393(6684). [doi:10.1038/30918](https://doi.org/10.1038/30918)

**In practice:** Local clustering pinpoints channels embedded in mutual-amplification triangles — which is exactly the shape of a *coordinated cell*: a small group of channels that all forward each other's content. No other Pulpit measure singles out this pattern: a five-channel cell can look unremarkable on every prestige column yet have local clustering near 1.0 across all five members. Paired with Burt's constraint, it gives the canonical structural-holes-vs-echo-chamber decomposition.

**Example.** In a mapped extremist-channel ecosystem, five channels all cross-forwarding each other show up with local clustering between 0.6 and 0.8 per member — even though three of them have low PageRank and unremarkable citation counts, so none of the global-prestige or brokerage measures flag them. By contrast, a mainstream news aggregator drawing from twelve unrelated sources (a national newswire, an academic blog, a sports outlet, a foreign-policy magazine, and so on) scores near 0 on clustering: its sources do not cite each other.

---

## K-core coreness

*A high coreness number means this channel sits in the densely interconnected nucleus of the network; a low number means it is a peripheral amplifier on the network's edge.*

Coreness is the depth of the densest layer a channel survives in when the network is *peeled*: starting from the outermost layer, channels with too few connections are repeatedly removed; the layer in which a channel finally disappears is its coreness. A channel in the top layer sits in a tight nucleus where every member is connected to many others in the same nucleus — being there requires the channel's neighbours, and their neighbours' neighbours, all to clear the same threshold.

**References:**
- Seidman, S.B. (1983) "Network structure and minimum degree." *Social Networks* 5(3). [doi:10.1016/0378-8733(83)90028-X](https://doi.org/10.1016/0378-8733(83)90028-X)
- Kitsak, M. et al. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6(11). [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746)

**In practice:** Coreness answers a question prestige measures don't quite get to: *is this channel embedded in the network's reinforcing nucleus, or on its periphery?* A channel can have very high in-degree from many peripheral citers yet low coreness — its audience is broad but shallow. A modest in-degree with high coreness is the opposite case — a channel woven into a tight, mutually reinforcing core. The headline finding from network science is that coreness predicts how far a message would spread *better than in-degree does*, so high-coreness channels are typically more consequential than their citation counts alone suggest.

**Example.** A long-running nationalist outlet sits in the deepest coreness layer of a 400-channel ecosystem: each of its citers is itself cited by at least seven others in the same nucleus. Its in-degree puts it third overall, but coreness puts it first. A viral aggregator with 50,000 subscribers has the network's top in-degree, yet only middling coreness — its citers are mostly peripheral leaves that nobody else amplifies. Coreness identifies the nationalist outlet as the structurally consequential one; in-degree would put the aggregator first.

---

## Collective Influence

*A high collective-influence score flags a channel whose removal would most fragment the network — the optimal-percolation key spreaders, found by looking a couple of hops out rather than only at immediate ties.*

Collective Influence comes from optimal-percolation theory: the search for the minimal set of nodes whose removal shatters a network's giant connected component. For each channel it multiplies `(degree − 1)` by the sum of `(degree − 1)` over every channel sitting *exactly* ℓ hops away (Pulpit fixes ℓ = 2). A channel scores high only when it is itself well-connected *and* its two-hop surroundings are well-connected too — the signature of a node wedged at the heart of a dense region, whose deletion does maximal structural damage. The headline finding from the original study is that this ranking pinpoints the influential set more reliably than degree, k-core, PageRank or betweenness.

**References:**
- Morone, F. & Makse, H.A. (2015) "Influence maximization in complex networks through optimal percolation." *Nature* 524(7563). [doi:10.1038/nature14604](https://doi.org/10.1038/nature14604)

**In practice:** Collective Influence is the per-channel companion to Pulpit's [robustness analysis](robustness-analysis.md): robustness *removes* channels by a ranking and watches the network shrink, while collective influence *is* the near-optimal removal ranking read straight off the static graph. It complements two neighbours: where k-core coreness gives a coarse onion-layer depth and SIR spreading efficiency averages stochastic cascades, collective influence is a deterministic, percolation-grounded score of how structurally load-bearing a channel is. It is computed on the symmetrised, unweighted graph (matching coreness), so it reads the topology of who-connects-to-whom rather than tie strength, and is read **ordinally** — the ranking is the signal, not the raw magnitude.

**Example.** In a 400-channel political ecosystem, two channels have nearly identical k-core coreness — both sit in the same deep shell. Collective Influence separates them. The first is surrounded, two hops out, by a sprawl of other well-connected channels: removing it tears a hole that the surrounding density cannot route around, and its collective-influence score is among the highest in the network. The second sits in the same shell but its two-hop neighbourhood thins out into peripheral leaves, so its score is middling. Coreness calls them equals; collective influence correctly flags the first as the structurally load-bearing one — the channel a moderation effort aiming to fragment the ecosystem would target first.

---

## Trophic level

*A low trophic level means this channel is a structural source that others draw from; a high level means it is a terminal amplifier downstream of the content it carries.*

Trophic level places every channel on a single source-to-sink axis derived from the direction of citations. Channels at low levels publish content that flows downstream; channels at high levels mostly receive and re-broadcast content from elsewhere. The measure is well-defined even on the cyclic networks Pulpit builds (where the classical food-web definition fails) — it captures the same intuition as a balance equation across the whole citation flow, so it handles the messy structure of real citation graphs cleanly.

**References:**
- MacKay, R.S., Johnson, S. & Sansom, B. (2020) "How directed is a directed network?" *Royal Society Open Science* 7(9). [doi:10.1098/rsos.201138](https://doi.org/10.1098/rsos.201138)

**In practice:** Trophic level is the structural counterpart of content originality — content originality reads per-message provenance, trophic level reads citation-graph position. The pair separates *genuine sources* (high originality, low level) from *mid-chain relays* (low originality, mid level) and *terminal amplifiers* (low originality, high level). The score is particularly useful when a prestige measure ranks a heavily-cited aggregator first: trophic level can reveal that the aggregator sits mid-chain, with the actual source above it.

**Example.** In a 400-channel political ecosystem, a small commentary outlet with 4,000 subscribers and modest in-degree sits at trophic level 0 — the structural source of its part of the network. PageRank puts it in the second decile and in-degree puts it 87th, but trophic level identifies it as the chain's origin. A viral aggregator with 50,000 subscribers and the network's top citation count sits at trophic level 1.6 — receiving from the commentator and re-broadcasting to many peripheral channels. Every static prestige column ranks the aggregator first; trophic level correctly places it as a relay, not an origin.

---

## Within-module role

*Is this channel a hub inside its own community, a bridge between communities, or a peripheral member? The within-module role names the position directly, on top of any community partition.*

The within-module role characterises every channel by two scores measured *against its own community*: one for internal embeddedness (how unusually well-connected the channel is *within* its community), and one for cross-community reach (how broadly the channel's contacts spread *across* communities). These two scores are collapsed into seven canonical labels — from *ultra-peripheral* (a channel that barely interacts outside its own community) to *connector hub* (a channel that is both internally central and spans communities widely).

**References:**
- Guimerà, R. & Amaral, L.A.N. (2005) "Functional cartography of complex metabolic networks." *Nature* 433(7028). [doi:10.1038/nature03288](https://doi.org/10.1038/nature03288)

**In practice:** The role labels turn a coloured-blob community map into a concrete job description: a *provincial hub* is a kingpin of one community that rarely speaks outside it; a *connector hub* is both central within and spanning out, the most strategically significant broker; a non-hub *connector* is a low-profile bridge with modest internal weight but ties that systematically cross community boundaries. The label pairs naturally with global prestige measures: a top-decile PageRank channel can be either a *provincial hub* (locally dominant but not network-spanning) or a *connector hub* (both), and the label tells you which.

**Example.** In a 400-channel political ecosystem, two channels look nearly identical on the static prestige columns — comparable PageRank, similar core depth, similar citation strength. The role taxonomy separates them. The first lands as a *connector hub* — both internally central in its community *and* with ties that span multiple distinct communities. The second is a *provincial hub* — the kingpin of its own community, but with ties that do not systematically cross out. Reading PageRank alone, the two look like equivalent leaders; reading the role labels, they are different jobs. Removing the first severs both internal cohesion and cross-community flow; removing the second only fragments one community.

---

## Brokerage roles (Gould-Fernandez 1989)

*Burt's constraint and community bridging tell you that a channel is a broker; the brokerage census tells you what kind — does it guard what enters a faction, push its faction's content outward, or bridge two camps it belongs to neither of?*

The Gould–Fernandez census classifies every citation chain a channel mediates. Whenever channel *i* cites *v* and *v* cites *j* (a directed two-path `i → v → j`), the broker *v* is performing one of five distinct roles, decided by the groups — by default the analyst's **Organizations** — that *i*, *v* and *j* belong to:

- **Coordinator** — *i*, *v*, *j* all in *v*'s own group: a broker *within* its faction.
- **Gatekeeper** — *i* is an outsider, *v* and *j* share *v*'s group: *v* controls what flows *into* its faction.
- **Representative** — *i* and *v* share *v*'s group, *j* is an outsider: *v* controls what flows *out* of its faction.
- **Consultant** — *i* and *j* belong to one other group that is not *v*'s: *v* brokers between two members of a faction it sits outside.
- **Liaison** — *i*, *v*, *j* are in three different groups: *v* bridges two foreign camps, belonging to neither.

Pulpit reports the **total** number of two-paths a channel brokers (the sortable *Brokerage* column) and its **dominant role** (the *Brokerage role* column, alongside it exactly as the within-module Role sits beside its z-score). The five individual role counts are written to `nodes.csv` and the GEXF/GraphML exports for the full census.

**References:**
- Gould, R.V. & Fernandez, R.M. (1989) "Structures of mediation: A formal approach to brokerage in transaction networks." *Sociological Methodology* 19. [doi:10.2307/270949](https://doi.org/10.2307/270949)

**In practice:** This is the typed complement to Pulpit's other brokerage measures, which all report brokerage *intensity* without naming the *kind*. Burt's constraint says a channel's contacts are non-redundant; betweenness and [community bridging](#community-bridging) say it lies on cross-group paths — but none distinguishes a **gatekeeper** (which decides what reaches a faction's audience) from a **representative** (which carries a faction's message outward) from a **liaison** (an unaligned channel bridging two camps). In an influence-operation context these are different jobs with different leverage: gatekeepers are chokepoints for inbound narratives, representatives are a faction's outward megaphone, liaisons are the deniable conduits between camps that never cite each other directly. The dominant-role label is a quick descriptor — biased toward whichever role the channel's group sizes give it the most opportunity for — so read it together with the five raw counts in the export when the distinction matters. The census needs a meaningful group partition; with `ORGANIZATION` the roles read as brokerage between the analyst's own factions, and the measure returns nothing for a channel with no organisation.

**Example.** In a mapped national ecosystem, three channels have almost identical betweenness. The census pulls them apart. The first is overwhelmingly a **gatekeeper**: nearly all the two-paths it mediates run from outside channels into its own religious-nationalist organisation — it is the faction's inbound filter, deciding which external narratives its audience ever sees. The second is a **representative**: its brokered paths run the other way, from inside its economic-nationalist organisation out to channels in three rival camps — it is the organisation's outward voice. The third belongs, by organisation, to neither of the camps it connects: a **liaison** whose brokered paths almost all run between a state-media organisation and a diaspora organisation that never cite each other directly. Betweenness ranks the three as equals; the brokerage census identifies one as a chokepoint, one as a megaphone, and one as a bridge — and only the liaison is invisible to a measure that assumes brokers sit inside the groups they connect.

---

## Amplification factor

*How many times each of this channel's messages is re-broadcast, on average, by other channels in the network — a per-post measure of intra-network virality.*

Amplification factor is the ratio of *forwarding events received* to *messages produced*: if a channel publishes 200 messages and other channels in the network forward those messages a combined 800 times, the score is 4.0. A value of 1.0 means each post is, on average, re-broadcast once somewhere in the network; values above 1 mean the network forwards the channel's output faster than the channel produces it. The measure reads off raw forwarding activity, so it captures behavioural reach rather than structural position.

**References:**
- Bakshy, E., Hofman, J.M., Mason, W.A. & Watts, D.J. (2011) "Everyone's an influencer: quantifying influence on Twitter." *WSDM '11*. [doi:10.1145/1935826.1935845](https://doi.org/10.1145/1935826.1935845)
- Cha, M., Haddadi, H., Benevenuto, F. & Gummadi, K.P. (2010) "Measuring user influence in Twitter: the million follower fallacy." *ICWSM 2010*. [link](https://ojs.aaai.org/index.php/ICWSM/article/view/14033)

**In practice:** Amplification factor is the most direct Pulpit measure of *whose voice carries the furthest, post for post*. Paired with content originality, it sorts channels into four roles: high amplification + high originality = a primary source whose content travels (usually the most consequential channel for an analyst); high originality + low amplification = an original niche nobody re-broadcasts; low originality + high amplification = an aggregator whose curated forwards are themselves re-amplified; low on both = a passive consumer.

**Example.** In an analyst's target ecosystem, a commentary channel with 3,000 subscribers publishes 200 detailed messages; ten mainstream aggregators forward it regularly, producing 850 forwarding events. Its amplification factor is 4.25 — each post is, on average, re-broadcast more than four times. A political party's official channel with 50,000 subscribers publishes 1,200 messages, but only a handful of small accounts forward them, totalling 220 events — score 0.18, so most party messages never leave their own audience. Subscriber count would rank the party channel first; amplification factor reverses the ordering and correctly identifies the commentator as the network's most-amplified voice on a per-post basis.

---

## Content originality

*The share of a channel's posts that are not forwards from someone else — a simple producer-vs-redistributor measure.*

Content originality is the fraction of a channel's own messages that are not native Telegram forwards. A score of 1.0 means everything the channel publishes is original; 0.0 means everything is a forward; intermediate values give the production-to-redistribution mix. The score reads off the channel's own publishing ledger — not the citation network around it — so it is independent of structural choices that change other measures, and it can be read on its own.

**References:**
- Boyd, D., Golder, S. & Lotan, G. (2010) "Tweet, Tweet, Retweet: Conversational Aspects of Retweeting on Twitter." *HICSS-43*. [doi:10.1109/HICSS.2010.412](https://doi.org/10.1109/HICSS.2010.412)
- Kwak, H., Lee, C., Park, H. & Moon, S. (2010) "What is Twitter, a Social Network or a News Media?" *WWW 2010*. [doi:10.1145/1772690.1772751](https://doi.org/10.1145/1772690.1772751)

**In practice:** Content originality is Pulpit's most direct answer to *whose voice is genuinely original, post-for-post, and whose is curatorial?* It is the behavioural counterpart to the structural measures. Paired with amplification factor it spans four roles — primary source whose content travels (high on both), original niche (high originality, low amplification), curated aggregator (low originality, high amplification), and passive consumer (low on both). Paired with trophic level it separates genuine sources from mid-chain relays.

**Example.** A commentary outlet that publishes its own analyses emits 600 messages over the analysis window, 30 of which are forwards from peer channels — originality score 0.95: almost every post is original, with a thin layer of curated forwards. A content aggregator on the same topics emits 800 messages, 720 of which are forwards from a handful of sources — originality 0.10: by volume, almost all content is other people's. Subscriber count might rank the aggregator first, but originality flips the framing: the first channel is the local *producer*, the second the local *amplifier*.

---

## Diffusion lag

*The median time a channel waits before re-broadcasting someone else's content — a timing signature that separates early adopters from late amplifiers.*

Diffusion lag is the median number of hours between when a piece of content is first published and when a given channel forwards it. Channels with low lag are *early adopters* — fast-reacting in the network's content cycle; channels with high lag are *late amplifiers* — picking up content well after it has circulated. The median is used instead of the mean because waiting times follow a heavy-tailed distribution where a few extremely delayed forwards would otherwise dominate the average.

**References:**
- Vosoughi, S., Roy, D. & Aral, S. (2018) "The spread of true and false news online." *Science* 359(6380). [doi:10.1126/science.aap9559](https://doi.org/10.1126/science.aap9559)
- Iribarren, J.L. & Moro, E. (2009) "Impact of human activity patterns on the dynamics of information diffusion." *Physical Review Letters* 103(3), 038702. [doi:10.1103/PhysRevLett.103.038702](https://doi.org/10.1103/PhysRevLett.103.038702)

**In practice:** Diffusion lag answers a question no structural measure can: *when* does a channel typically react? It is the temporal companion of the volume and position measures. Paired with amplification factor, it splits forwarders into agenda-setters (low lag, high amplification — fast and well-amplified), consolidators (high lag, high amplification — slow takes that still travel), followers (low lag, low amplification — quick but unheard), and peripheral re-broadcasters (high lag, low amplification). The dimension is invisible to any static-graph measure.

**Example.** Two channels in a nationalist commentator network each forward roughly 60% of a primary broadcaster's posts, with comparable in-degree. One has a diffusion lag of 1.8 hours, the other 17. On every static and behavioural-volume measure they look interchangeable; temporally they are not. The first is part of the broadcaster's same-day distribution chain — an agenda-setter that extends the broadcaster's news window. The second re-broadcasts after the news cycle has moved on — a consolidator whose role is reinforcing narratives rather than seeding them.

---

## Spreading efficiency

*If this channel were the first to publish a piece of information, what fraction of the network would eventually receive it under a simulated cascade?*

Spreading efficiency simulates a simple cascade — analogous to an epidemic — seeded at each channel: the channel "infects" its forwarders with a probability proportional to how heavily they cite it, those forwarders infect their own citers in turn, and so on until the cascade dies out. The score is the average fraction of the network ever reached, taken across many simulated runs. A score of 0.32 means a cascade seeded at that channel reaches, on average, 32% of the other channels.

**References:**
- Kitsak, M. et al. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6(11). [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746)
- Pastor-Satorras, R., Castellano, C., Van Mieghem, P. & Vespignani, A. (2015) "Epidemic processes in complex networks." *Reviews of Modern Physics* 87(3). [doi:10.1103/RevModPhys.87.925](https://doi.org/10.1103/RevModPhys.87.925)

**In practice:** Spreading efficiency is Pulpit's only purely *dynamic* per-channel reach measure — every other measure characterises a channel by its static position. It identifies *superspreaders* in the original sense of the term: channels whose content would percolate furthest if the network were to relay a single piece of content. The most useful comparison is with amplification factor — high spreading + low amplification = unrealised potential; low spreading + high amplification = observed reach the structure alone wouldn't predict. The score should be read ordinally — what matters is the ranking, not the absolute percentages.

**Example.** A small commentary outlet with 4,000 subscribers has a second-decile PageRank and unremarkable citation count — every static prestige column dismisses it. Its spreading-efficiency score, however, places it among the top — each simulated cascade reaches roughly a third of the network. Inspection reveals the channel sits one hop upstream of three large aggregators, which themselves fan out to dozens of dependent channels; cascades percolate through that two-step neighbourhood before dying out. A political party's official channel with the highest citation count has a much lower spreading score — its citers are mostly peripheral leaves, and the cascade dies within one hop. Static prestige misses the commentator; spreading efficiency identifies it as the network's dynamical superspreader.

---

## Bridging centrality (Hwang et al. 2008)

*A high bridging centrality score means this channel is a topological bridge — a low-degree node wedged between high-degree regions, whose removal would most fragment the network.*

Bridging centrality combines betweenness (lying on shortest paths) with a *bridging coefficient* that asks whether the channel's contacts are themselves high-traffic. The combined score is high only for channels with both qualities: on many traversal paths *and* sitting at the narrow waist between busy regions. A channel deep inside a single dense cluster can have very high betweenness, but if its neighbours are themselves high-degree cluster members, the bridging coefficient knocks it down. Only true topological bridges keep both factors high.

**References:**
- Hwang, W., Kim, T., Ramanathan, M. & Zhang, A. (2008) "Bridging Centrality: Graph Mining from Element Level to Group Level." *KDD '08*. [doi:10.1145/1401890.1401941](https://doi.org/10.1145/1401890.1401941)

**In practice:** Bridging centrality separates *true bottlenecks* from *mere hubs*. A hub inside a dense cluster can have very high betweenness, but if its contacts are themselves high-degree, its bridging coefficient is small and the product knocks it down. By contrast, a modest channel that quietly connects two large clusters — whose disappearance would fracture the network — scores high on both factors. It does not need a community partition (it uses only degree information), so it can be read directly off the citation graph without any additional analysis step.

**Example.** A mapped political ecosystem of 400 channels contains a 200-channel nationalist cluster and a 200-channel religious-conservative cluster that otherwise share no direct contact. A within-cluster aggregator with in-degree 47 and top-decile PageRank has the network's highest plain betweenness — the channel every prestige column picks first. A second channel has just two meaningful ties, one into each cluster: its in-degree is 2, PageRank middling, plain betweenness three times smaller. Bridging centrality inverts the ordering. The aggregator's contacts are themselves high-degree cluster members, so its bridging coefficient is small. The two-tie channel's neighbours are both cluster hubs, so its bridging coefficient is huge. Bridging centrality correctly flags it as the single point of failure between the two clusters.

---

## Community bridging

*A high community bridging score means this channel is both structurally central AND bridges genuinely distinct communities.*

Community bridging combines betweenness centrality with a measure of how widely a channel's contacts spread across the network's detected communities. A channel that lies on shortest paths *and* whose contacts span multiple communities scores high; a channel that lies on shortest paths but whose contacts all belong to a single community scores zero. The measure requires a community partition, which Pulpit picks automatically from the strategies the user has configured for the run.

> **Naming note.** This composite was previously labelled "Bridging centrality", but that name properly belongs to the degree-based measure of Hwang et al. (2008) — now exposed separately as `BRIDGINGCENTRALITY`. This measure was renamed **Community bridging** (key `community_bridging`); the question it answers ("does this broker span *distinct communities*?") is the Guimerà–Amaral one.

**References:**
- Guimerà, R. & Amaral, L.A.N. (2005) "Functional cartography of complex metabolic networks." *Nature* 433(7028). [doi:10.1038/nature03288](https://doi.org/10.1038/nature03288)
- Freeman, L.C. (1977) "A set of measures of centrality based on betweenness." *Sociometry* 40(1). [doi:10.2307/3033543](https://doi.org/10.2307/3033543)

**In practice:** Community bridging fills a gap left by betweenness alone. A channel can rank highly on betweenness simply because it sits in a dense region, even if all its contacts belong to one community. Community bridging discounts this case: a *within-community kingpin* (high betweenness, low community bridging) is one role; a *genuine cross-community broker* (high on both) is another. The pair is the cleanest way to identify channels whose removal would not just shift traffic but split the network's coalition structure.

**Example.** Two channels have nearly identical betweenness scores. The first sits at the centre of a tightly cross-citing nationalist bloc; all its contacts belong to the same community. Its community-bridging score is 0 — it is a within-community kingpin. The second has similar betweenness but its contacts split across four distinct communities — nationalist, religious-conservative, mainstream right, and state media. Its community-bridging score is well above the first. Plain betweenness ranks them tied; community bridging correctly distinguishes a within-community kingpin from a strategically significant cross-community broker.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">
