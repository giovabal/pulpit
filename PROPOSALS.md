# Proposals for Pulpit: New Features and Improvements

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

### 4.5 — Closeness centrality

The only fundamental centrality measure not yet in the registry. Closeness = average inverse distance from a node to all other reachable nodes. Channels with high closeness can spread information quickly across the network without necessarily having many direct connections. `nx.closeness_centrality()` works out of the box on directed graphs; adding a `CLOSENESS` key to `_registry.py` and a one-function wrapper in `network/measures/_centrality.py` is the full scope.

### 4.6 — Per-node local clustering coefficient

`nx.average_clustering()` is already used as a whole-network statistic, but per-node `nx.clustering()` is never computed or exported. Add a `LOCALCLUSTERING` measure. Channels with high local clustering are embedded in echo-chamber cliques; channels with low values are structural bridges even when their ego-density is low. Pairs well with `EGODENSITY` for a richer characterisation of local structure.

### 4.7 — Separate forward and mention edge weights

Currently, message forwards and `t.me/` inline mentions are summed into a single edge weight. Storing them as two separate edge attributes (`weight_forwards`, `weight_mentions`) in the graph and in GEXF/GraphML exports would let analysts distinguish strong-signal forwards (deliberate reposting) from weak-signal mentions (inline links). The data is already split in `_build_edge_list()` (`network/graph_builder.py`) — `forwarded_counts` and `reference_counts` are separate dicts that get added together only at the last step. Edge weight computation would stay the same for the final `weight` attribute; the two components would be stored alongside it as extra attributes.

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

### 6.4 — Reply count per message

Telethon's `Message.replies.replies` (integer, the public reply count shown on broadcast channel posts) is available on every message but not stored. Add a `reply_count IntegerField(null=True)` to the `Message` model and populate it in `get_message()`. Display it in the post footer alongside views and forwards; export it in the channel table XLSX. Useful for distinguishing posts that generate discussion from those that are passively consumed.

### 6.5 — Edit tracking per message

`Message.edit_date` is returned by Telethon but never stored. Add an `edit_date DateTimeField(null=True)` to `Message` and show an "edited" indicator on post cards when the field is set. Relevant for disinformation research: post-publication edits can change meaning after initial amplification.

### 6.6 — Post author attribution

`Message.post_author` (a freeform string, set for channels with "Sign messages" enabled) is not stored. Add a `post_author CharField(max_length=255, blank=True)` and display it on the post card. The `signatures` meta badge is already shown on the channel detail page; this fills in the per-post counterpart.

### 6.7 — Custom and sticker reactions

`_save_reactions()` in the crawler explicitly skips custom/sticker reactions (the `else` branch when `hasattr(rc.reaction, "emoticon")` is false). At minimum, tally them under a `custom` bucket so that total reaction counts are not understated on channels whose communities use custom emoji packs.

---

## 7. Web UI Improvements

### 7.1 — Message filters: minimum views and minimum forwards

The message options dropdown supports sort order and content-type filter but has no quantitative threshold. Add two optional number inputs — "Min views" and "Min forwards" — applied in `_apply_message_options()` in `webapp/views.py`. Useful for surfacing viral posts on high-volume channels without scrolling past thousands of low-reach messages.

### 7.2 — Message filter: pinned status

Pinned and previously-pinned messages are visually distinguished with CSS classes (`is-pinned`, `was-pinned`) but there is no filter to show only pinned posts. Add a "Pinned only" checkbox to the message options dropdown. Pinned posts represent editorial choices and are analytically interesting in their own right.

### 7.3 — Engagement rate chart on channel detail page

Views and message counts are tracked separately in monthly time series, but no engagement-rate chart (average views per message per month) exists. The data is derivable from the existing `MessagesHistoryDataView` and `ViewsHistoryDataView` endpoints, or a dedicated `ChannelEngagementHistoryView` can compute it server-side. Surfaces content effectiveness trends over time.

### 7.4 — Channel list: filter by channel type

The `structural_analysis` CLI already accepts `--channel-types` (Channel, Group, User), and the operations panel has a Channel Types fieldset, but the public channel list page (`/channels/`) has no type filter. Adding Channel / Group / User checkboxes above the channel table would let analysts isolate, for instance, only supergroups in a mixed dataset.

---

## 8. Backoffice Improvements

### 8.1 — Bulk set `uninteresting_after`

The `uninteresting_after` date field is editable per-channel in the edit page, but there is no bulk operation. Analysts working with a large set of channels that all became inactive on the same date must edit each one individually. Extend `ChannelViewSet.bulk_assign()` in `backoffice/api/views.py` to accept an `uninteresting_after` value, and add a date picker to the bulk action bar in the channels table.

---

## 9. Academic & Methodological Additions

### 9.1 — Influence operation risk score

Composite measure combining: low content originality + high amplification + high HITS hub + high posting tempo synchrony with other channels. Produces a single `IO_RISK` score per channel. Not a definitive verdict (clearly documented as such), but a useful triage tool for analysts. Based on the framework from Sharma et al. (2021) and Nizzoli et al. (2021).

---

## 10. Export Formats

### 10.1 — CSV node and edge list export

XLSX and GEXF are available but CSV is the most portable format for scripting (R, Python, shell). Add two optional files to every export: `nodes.csv` (one row per channel, same columns as `channel_table.xlsx`) and `edges.csv` (source_label, target_label, weight, weight_forwards, weight_mentions). Gate behind a `--csv` flag and an Operations panel checkbox alongside the existing GEXF/GraphML options.

---

## 11. Community Detection

### 11.1 — Label propagation

`nx.community.label_propagation_communities()` is a fast, parameter-free algorithm that runs in near-linear time. It would add a useful low-cost baseline for comparison with Leiden and Louvain, and is well-suited to large graphs where Infomap or MCL are slow. Adds one entry to the `detect()` function in `network/community.py`.

---

← [README](README.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">
