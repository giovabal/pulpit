# Proposals for Pulpit: New Features and Improvements

- vacancy needs enough data for being efficient and significant, find academically validated way to says if data are enough
- nodes could have a category (like individuals, organizations, and so on. Or by nationality), this could be reflected in shapes of nodes in graph (like squares, circles, diamonds, and so on)
- Organization changes overtime.
- group analysis, similar to whole network analysis
- Normalized Mutual Information between community strategies: a new entry in `network_table` could show NMI between every pair of strategies (LEIDEN vs ORGANIZATION, LOUVAIN vs INFOMAP, etc.). This answers: does the algorithmic partition agree with the analyst's manual grouping? High NMI means your Organizations map well onto structural clusters; low NMI means the network's topology cuts across your labels.
- pairwise structural similarity matrix (cosine similarity of node feature vectors across all measures)


Before major release (/plan)
- I need strong layout coherence through all the software, inspect webapp templates and HTML outputs
- review documentation
- aria attributes


## 3. Content & Semantic Analysis

### 3.1 — Topic modeling per channel

Run BERTopic or LDA on stored message text to assign each channel to topic clusters. Topics become a new community type: `TOPIC`. This is particularly powerful for researchers who don't know the domain well enough to define Organizations manually.

**Academic basis:** BERTopic (Grootendorst 2022) with multilingual sentence transformers works well for short Telegram messages. Iamverdeci et al. (2023) used this on Ukrainian-conflict Telegram networks.

### 3.2 — Narrative tracking

Rather than just detecting topics, track which narrative frames appear in messages (keyword lists or small embedding classifiers). Count how often each channel uses each narrative. Output narrative adoption rates per channel, and flag channels that adopt new narratives quickly (narrative amplifiers) vs. originate them.

---

## 4. New Network Measures

### 4.4 — Narrative diffusion lag

Measure how quickly a channel adopts content that originated elsewhere (via forwards). Early adopters vs. late amplifiers. Implementable as a per-node measure: average `(message.date - message.forwarded_from.original_date)` for all forwarded messages. Requires storing the original post date of the forwarded message.


---

## 5. Graph Visualization Improvements

### 5.1 — Timeline slider on the graph

If temporal snapshots are generated (see 1.1), add a timeline slider to `graph.html` that morphs the graph between snapshots. Nodes fade in/out, edges change weight, communities shift. Uses Sigma.js `animateNodes()` for smooth transitions.

### 5.3 — Ego-graph exploration mode

Clicking a node currently shows in/out edges in a sidebar. Add a dedicated "Explore neighborhood" mode: clicking a node isolates it and its N-hop neighborhood, grays out everything else, and allows N to be adjusted (slider 1–3 hops). Essential for drilling into individual channels without losing network context.

### 5.4 — Path finder

Given two channels selected by the user, highlight the shortest path(s) between them in the graph. Shows exactly which intermediary channels connect two otherwise-distant outlets. Implementable in JS using BFS on the already-loaded `channel_position.json` edge data.

### 5.5 — Community evolution visualization

When `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.

---

## 6. Crawling Improvements

### 6.3 — Group/supergroup reply crawling

Supergroups (`megagroup=True`) store discussion replies. Currently, these are crawled as channels but their replies (comments) are not fetched. Fetching replies would reveal which channels' posts generate discussion and who participates. New `Message.reply_to` field and `--crawl-replies` option.


---

## 9. Academic & Methodological Additions

### 9.1 — Influence operation risk score

Composite measure combining: low content originality + high amplification + high HITS hub + high posting tempo synchrony with other channels. Produces a single `IO_RISK` score per channel. Not a definitive verdict (clearly documented as such), but a useful triage tool for analysts. Based on the framework from Sharma et al. (2021) and Nizzoli et al. (2021).

---

← [README](README.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">
