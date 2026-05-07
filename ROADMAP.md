# Roadmap for Pulpit: Activities for Next Versions

## [0.18]
- Separate forward and mention edge weights. Currently, message forwards and `t.me/` inline mentions are summed into a single edge weight. Storing them as two separate edge attributes (`weight_forwards`, `weight_mentions`) in GEXF/GraphML/CSV exports would let analysts distinguish strong-signal forwards (deliberate reposting) from weak-signal mentions (inline links). The data is already split in `_build_edge_list()` (`network/graph_builder.py`) — `forwarded_counts` and `reference_counts` are separate dicts that get added together only at the last step. Edge weight computation would stay the same for the final `weight` attribute; the two components would be stored alongside it as extra attributes.

- Custom and sticker reactions. `_save_reactions()` in the crawler explicitly skips custom/sticker reactions (the `else` branch when `hasattr(rc.reaction, "emoticon")` is false). At minimum, tally them under a `custom` bucket so that total reaction counts are not understated on channels whose communities use custom emoji packs.

- Screenshots missing
-- Crawl channels panel open (13)
-- Search channels panel open (new, instead of 13)
-- 2D Graph, coloring by community (00)
-- Whole-network statistics table (04)
-- Vacancy analysis in page (new)
-- Channel details with graphs (10) (exchange position with 11)
-- Channel details with messages (12)
-- Manage (09)
-- 3D graph (06, 07, 08)


## [0.19]
- regency weights should be centered on a period of time, and there must regency weights even for the future
- vacancy needs enough data for being efficient and significant, find academically validated ways to say if data are enough
- nodes could have a category (like individuals, organizations, and so on. Or by nationality), this could be reflected in shapes of nodes in graph (like squares, circles, diamonds, and so on)
- Organization changes overtime.
- group analysis, groups as selectors, similar to whole network analysis
- Community evolution visualization: when `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.


## [0.20]
- persist structural analysis options, so they can be chosen before analysis, imported and exported
- in homepage add a scattered graph that show number of connection / number of effective forwards (ie.: number against multiplicity)


## [1.0]
- Have a deep inspection of Python code, search for bugs, bad practices and dead code
- Have a deep inspection of JS code, search for bugs, bad practices and dead code
- Have a deep inspection of HTML and CSS code, search for bugs, bad practices and dead code
- Have a deep inspection of HTML code, make sure the app and the HTML output of analysis are respecting accessibility rules and can provide a decent experience for people using screen readers
- Have a deep inspection of all options accepted by commands, look for inconsistencies and bad practices
- I need strong layout coherence through all the software, inspect webapp templates and HTML outputs
- Read the code and review documentation, propose variations.


---
