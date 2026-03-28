# Proposals for Pulpit: New Features and Improvements

Below is a prioritized, structured list of proposals organized into thematic clusters, from the most analytically impactful to the most engineering-focused. Sections 1–9 contain the full proposals; section 10 is the priority matrix.

---

## 1. Temporal Network Analysis

### 1.1 — Network snapshots & temporal evolution

Currently, `--startdate`/`--enddate` filters the entire export to a single window. The proposal is a new command or `--snapshots` mode that generates a series of exports (e.g. monthly or quarterly) and outputs a JSON timeline format. The frontend could then animate the graph: nodes appearing, edges strengthening, communities shifting.

**Academic basis:** Holme & Saramäki (2012) established that static-graph analysis misses the order and timing of links, which is essential for influence propagation. In Telegram research, studies of Russian IOs found that network topology changed dramatically before and after major events (elections, invasions). A static snapshot of 2 years of data hides this.

### 1.2 — First-mover / cascade detection

For each (source → target) edge, record the chronological order of first reference: which channel first forwarded another, and which came later? This identifies true originators vs. followers. Exportable as a `first_seen` edge attribute in `channel_position.json`.

---

## 2. Coordinated Inauthentic Behavior Detection

### 2.1 — Cross-posting similarity score

Detect channels that post identical or near-identical content (cosine similarity of message fingerprints). Channels with high similarity across many messages are candidates for coordinated behavior. Expose as a new node measure `COSIMILARITY` (average similarity to nearest neighbor) and as a new community strategy `COSIMILARITY_CLUSTER`.

**Academic basis:** Sharma et al. (2021), Nizzoli et al. (2021) — synchronized posting and content duplication are the two strongest signals of coordinated inauthentic behavior on Telegram. Current tools (e.g., TeleTracker, Botometer) use exactly this.

### 2.2 — Posting tempo synchrony

Measure the variance of posting timestamps between channel pairs. Channels that consistently post the same content within seconds/minutes of each other, over many days, suggest a coordinated network. Compute a `SYNCHRONY` measure: pairwise cross-correlation of hourly posting histograms.

### 2.3 — Hashtag / keyword co-occurrence graph

Beyond channel-to-channel edges from forwards and `t.me/` links, build a second graph layer: channels co-mentioning the same hashtags or keywords. This surfaces coordination that doesn't leave forwarding traces — channels that receive the same instructions and post independently.

### 2.4 — CooRNet-style coordinated link sharing

Build a co-sharing graph: channels that forward the *same source message* within a short time window (e.g., within 60 minutes of each other) get an edge in a secondary graph. Keep edges only below a latency threshold. The resulting graph exposes coordination rings invisible in the direct forward graph. Implemented as `export_network --coordinated-sharing`, producing a second graph layer.

**Academic basis:** Giglietto et al. (2020, CooRNet) formalized this for Facebook; the method is directly applicable to Telegram's forwarding mechanism.

### 2.5 — Forwarding latency as a coordination signal

For each forwarded message, store the time delta between the original post and the forward (`message.date - original_publication_date`). Channels with a very tight latency distribution (spike within minutes, not a heavy tail) exhibit coordinated amplification, not organic sharing. Requires storing `Message.forwarded_from_date` during crawling — Telethon exposes this via `fwd_from.date`.

**Academic basis:** Khaund et al. (2021, WebSci) showed that coordinated Telegram clusters produce synchronized posting bursts detectable only through temporal analysis.

---

## 3. Content & Semantic Analysis

### 3.1 — Topic modeling per channel

Run BERTopic or LDA on stored message text to assign each channel to topic clusters. Topics become a new community type: `TOPIC`. This is particularly powerful for researchers who don't know the domain well enough to define Organizations manually.

**Academic basis:** BERTopic (Grootendorst 2022) with multilingual sentence transformers works well for short Telegram messages. Iamverdeci et al. (2023) used this on Ukrainian-conflict Telegram networks.

### 3.2 — Narrative tracking

Rather than just detecting topics, track which narrative frames appear in messages (keyword lists or small embedding classifiers). Count how often each channel uses each narrative. Output narrative adoption rates per channel, and flag channels that adopt new narratives quickly (narrative amplifiers) vs. originate them.

### 3.3 — Language detection per channel

Automatically detect the primary language of each channel's messages (using `langdetect` or `lingua`). Store as a `Channel.language` field. Use in the graph frontend as a filter/coloring option. Critical for multilingual monitoring projects.

### 3.4 — URL domain analysis

Extract domains from the `webpage_url` field (already stored on messages). Build a secondary graph: channels sharing the same external URLs or domains. Channels that consistently share links to the same set of domains — especially obscure ones — form implicit networks even without direct forwards. Output as `domain_table` or an additional edge type in the graph.

---

## 4. New Network Measures

### 4.1 — Flow betweenness (random-walk betweenness)

Standard betweenness assumes shortest paths. Random-walk betweenness (Newman 2005) accounts for all paths, weighted by their probability — more realistic for how information actually diffuses. Implement via `networkx.current_flow_betweenness_centrality`. Useful for identifying brokers that standard betweenness misses in dense graphs.


### 4.3 — Ego network density

For each channel, compute the density of connections among its immediate neighbors. High ego-network density = channel embedded in a cohesive echo chamber. Low = channel serves as a hub for otherwise disconnected sources. Complementary to `BURTCONSTRAINT`.

### 4.4 — Narrative diffusion lag

Measure how quickly a channel adopts content that originated elsewhere (via forwards). Early adopters vs. late amplifiers. Implementable as a per-node measure: average `(message.date - message.forwarded_from.original_date)` for all forwarded messages. Requires storing the original post date of the forwarded message.

### 4.5 — Normalized Mutual Information between community strategies

Currently, community tables are shown per-strategy. A new entry in `network_table` could show NMI between every pair of strategies (LEIDEN vs ORGANIZATION, LOUVAIN vs INFOMAP, etc.). This answers: does the algorithmic partition agree with the analyst's manual grouping? High NMI means your Organizations map well onto structural clusters; low NMI means the network's topology cuts across your labels.

### 4.6 — View engagement ratio

Telegram stores per-message view counts (already crawled into `Message.views`). A `VIEW_ENGAGEMENT_RATIO` measure — `avg_views / participants_count` — flags channels where views grow much faster than the subscriber-to-view ratio would predict, a likely signal of view-botting. This is a Telegram-specific signal not available on other platforms.

---

## 5. Graph Visualization Improvements

### 5.1 — Timeline slider on the graph

If temporal snapshots are generated (see 1.1), add a timeline slider to `graph.html` that morphs the graph between snapshots. Nodes fade in/out, edges change weight, communities shift. Uses Sigma.js `animateNodes()` for smooth transitions.

### 5.2 — Edge type differentiation

Currently, edges from `forwarded_from` and from `t.me/` references are merged. Expose them as separate edge types (toggle in the UI): "Forwards only", "References only", "Both". Different rendering (solid vs. dashed) for each type. This lets researchers distinguish direct content amplification from looser mentions.

### 5.3 — Ego-graph exploration mode

Clicking a node currently shows in/out edges in a sidebar. Add a dedicated "Explore neighborhood" mode: clicking a node isolates it and its N-hop neighborhood, grays out everything else, and allows N to be adjusted (slider 1–3 hops). Essential for drilling into individual channels without losing network context.

### 5.4 — Path finder

Given two channels selected by the user, highlight the shortest path(s) between them in the graph. Shows exactly which intermediary channels connect two otherwise-distant outlets. Implementable in JS using BFS on the already-loaded `channel_position.json` edge data.

### 5.5 — Community evolution visualization

When `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.

### 5.6 — Node positioning by measure

In addition to community coloring, add an option to position nodes by measure value rather than spatial layout: a scatter plot view where X and Y axes are any two measures (e.g. PageRank vs. Content Originality). Each node is a dot. This turns the graph into a 2D typology of channels. Already partially supported by the scatter plot in `network_table.html`, but not with spatial node rendering.

---

## 6. Crawling Improvements

### 6.1 — Scheduled incremental crawl

Add a `--since HOURS` option to `get_channels`: only crawl new messages from the last N hours. Combined with a cron job, enables near-real-time monitoring. Distinguishable from existing behavior because it doesn't backfill history; it only fetches messages newer than `max_telegram_id` with a time constraint.

### 6.3 — Group/supergroup reply crawling

Supergroups (`megagroup=True`) store discussion replies. Currently, these are crawled as channels but their replies (comments) are not fetched. Fetching replies would reveal which channels' posts generate discussion and who participates. New `Message.reply_to` field and `--crawl-replies` option.

### 6.4 — Reaction counts

Telegram messages have emoji reactions. Store `Message.reactions` as a JSON field (reaction emoji → count). Expose total reaction count as a new column in `channel_table`, and a reaction-weighted engagement measure. Reactions are already available in the Telethon API via `message.reactions`.

### 6.5 — Geo-tagged message tracking

Messages with location entities in text, or channels with `has_geo=True`. Extract and store location mentions; build a geographic distribution of channel audiences. Exportable as a heatmap alongside the network graph.

---

## 7. Organization & Workflow

### 7.1 — Bulk channel labeling via CSV import

Currently, channels are assigned to Organizations one-by-one in Django admin. Add a management command `import_organizations --file labels.csv` accepting a CSV with columns `telegram_id` or `username`, `organization_name`, `color`. Creates organizations and assigns channels in bulk. Essential for projects with hundreds of channels.

### 7.2 — Channel health dashboard

New Django admin view showing, for each channel: days since last crawl, message gap density (holes), whether `is_lost` is set, days since last subscriber count update. Lets operators quickly identify stale data.

### 7.3 — Multiple database support (PostgreSQL)

SQLite is fine for single-researcher use but breaks under concurrent writes. Add optional PostgreSQL configuration to `settings.py`. Primarily a `settings.py` + `requirements.txt` change. Enables multiple crawlers running in parallel (one per channel batch) and shared team environments.

---

## 8. Community Detection Enhancements

### 8.2 — CPM (Constant Potts Model) for Leiden

The Leiden algorithm in `leidenalg` supports multiple quality functions. Standard modularity has a resolution limit: it fails to find small communities in large networks. CPM does not. Adding a `LEIDEN_CPM` strategy alongside `LEIDEN` lets researchers compare and identify small communities that modularity-based detection merges into larger ones.

**Academic basis:** Traag et al. (2019) introduced CPM as a resolution-limit-free alternative to modularity within the Leiden framework.

---

## 9. Academic & Methodological Additions

### 9.1 — Influence operation risk score

Composite measure combining: low content originality + high amplification + high HITS hub + high posting tempo synchrony with other channels. Produces a single `IO_RISK` score per channel. Not a definitive verdict (clearly documented as such), but a useful triage tool for analysts. Based on the framework from Sharma et al. (2021) and Nizzoli et al. (2021).

### 9.2 — Structural similarity matrix export

Export a pairwise structural similarity matrix (cosine similarity of node feature vectors across all measures) as a CSV. Enables researchers to import into R or Python for further analysis — clustering, regression, ML — outside the Pulpit pipeline.

### 9.3 — Reproducible research archive

New `export_network --archive` flag that bundles: the `graph/` output directory, a snapshot of the `.env` configuration (with credentials stripped), a `git describe` version tag, the SQLite DB schema (not data), and a README into a ZIP file. Allows researchers to share self-contained, reproducible analysis packages.

---

## 10. Priority matrix

| Priority | Proposal | Effort | Impact |
| :------- | :------- | :----- | :----- |
| High | 1.1 Temporal snapshots | Medium | High — transforms static to dynamic analysis |
| High | 2.1 Cross-posting similarity | Medium | High — core IO detection signal |
| High | 5.2 Edge type differentiation (forwards vs. references) | Low | Medium — immediate interpretability gain |
| High | 5.3 Ego-graph exploration mode | Low | High — standard feature in all SNA tools |
| High | 2.5 Forwarding latency as coordination signal | Low | High — direct CIB evidence |
| Medium | 4.5 NMI between community strategies | Low | Medium — methodological validation |
| Medium | 3.3 Language detection | Low | Medium — essential for multilingual corpora |
| Medium | 5.4 Path finder | Low | Medium — intuitive for non-technical users |
| Medium | 7.1 Bulk CSV org import | Low | High for operational use at scale |
| Medium | 6.4 Reaction counts | Low | Medium — engagement signal not currently captured |
| Medium | 4.1 Flow betweenness | Low | Medium — better broker detection |
| Medium | 4.6 View engagement ratio | Low | Medium — Telegram-specific bot signal |
| Medium | 2.4 CooRNet-style coordinated sharing | Medium | High — exposes invisible coordination rings |
| Medium | 8.2 CPM Leiden (no resolution limit) | Low | Medium — better small-community detection |
| Low | 3.1 Topic modeling (BERTopic) | High | High but complex dependency |
| Low | 5.1 Timeline slider | High | High but depends on 1.1 |
| Low | 7.3 PostgreSQL support | Medium | Operational scalability |

---

← [README](README.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">
