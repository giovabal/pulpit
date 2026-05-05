# Roadmap

Planned features and areas for further development. None of the items listed here are implemented yet. The list is a working record of directions, not a commitment.

---

## Accessibility

- ARIA attributes across all interactive HTML outputs

## Community analysis

- **Organisation changes over time** — track how channel–organisation assignments change across network snapshots
- **Group-level analysis** — whole-network and community statistics computed per ChannelGroup, analogous to the per-strategy community table
- **Pairwise structural similarity matrix** — cosine similarity of node feature vectors across all computed measures

## Events

- Link events to a specific group, channel, or organisation — not only as global annotations

## Content and semantic analysis

**Topic modelling per channel** — run BERTopic or LDA on stored message text to assign each channel to topic clusters, producing a new community type `TOPIC`. Particularly useful for researchers who do not know the domain well enough to define organisations manually. Academic basis: BERTopic (Grootendorst 2022) with multilingual sentence transformers.

**Narrative tracking** — detect which narrative frames appear in messages (keyword lists or embedding classifiers), count adoption rates per channel, flag channels that adopt new narratives quickly (amplifiers) vs. originate them.

## New network measures

**Influence operation risk score** — composite measure combining low content originality, high amplification, high HITS hub score, and posting-tempo synchrony with other channels. Produces a single `IO_RISK` score per channel. Not a verdict — explicitly documented as a triage tool. Based on frameworks from Sharma et al. (2021) and Nizzoli et al. (2021).

**Narrative diffusion lag** — average delay between when a message was first published and when a given channel forwarded it. Distinguishes early adopters (fast amplifiers) from late ones. Requires storing the original post date of the forwarded message.

## Graph visualisation

**Ego-graph exploration mode** — clicking a node isolates it and its N-hop neighbourhood, grays out everything else, and allows N to be adjusted via a slider (1–3 hops). Essential for drilling into individual channels without losing network context.

**Path finder** — given two channels selected by the user, highlight the shortest path(s) between them in the graph. Shows exactly which intermediary channels connect two otherwise-distant outlets. Implementable in JavaScript using BFS on the already-loaded `channel_position.json` edge data.

**Community evolution Sankey** — when Compare Analysis is used, a Sankey diagram in `network_compare_table.html` shows how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented with D3.js.

## Crawling

**Supergroup reply crawling** — supergroups (`megagroup=True`) store discussion replies. Currently, these are crawled as channels but their replies are not fetched. Fetching replies would reveal which channels' posts generate the most discussion and who participates. New `Message.reply_to` field and `--crawl-replies` option.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md) · [Roadmap](roadmap.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">
