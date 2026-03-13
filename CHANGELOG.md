# Changelog

## [0.4] - To be announced
### New features
- New option for `COMMUNITIES_STRATEGY`: `LEIDEN`.
- `CHANNEL_TYPES` option allows to define which kind of channels you want to explore.
- `search_channels` command now accepts `--amount` to limit how many search terms are processed per run.
- `export_network` command now produces tabular output alongside the graph mini-site.
- Project name changed from `TNExp` to `Pulpit`.

### Improvements
- Improved resilience against internet connection fails during crawling.
- Expanded documentation.
- Graph mini-site has a simpler file structure.
- Graph mini-site upgraded to Bootstrap 5.3, JQuery 4.0 and Sigma 3.0
- Graph mini-site moved from Font Awesome to Bootstrap Icons.
- Graph mini-site using CDNs instead of local libraries.


## [0.3.1] - 2026-03-08
### Fixed
- `KCORE` communities are now following their natural order, starting from the innermost core.


## [0.3] - 2026-03-08
### New features
- Multiple community strategies can be applied simultaneously via `COMMUNITIES_STRATEGY`.
- HITS Hub, HITS Authority, Betweenness Centrality, and In-degree Centrality network measures added to graph export and node detail panel.
- `NETWORK_MEASURES` option controls which measures are calculated and exported. Default is `PAGERANK`.
- About dialog in the graph mini-site: shows a description of Pulpit, a link to the GitHub repository, graph statistics, and explanatory text for all computed measures and active community strategies.
- Labels visibility option in the graph Options panel: Always, On size (default), or Never.
- Clicking a channel name in the connections list (inbound, outbound, or mutual) navigates to that channel's detail and highlights its network.

### Improvements
- Channels that resolve to user accounts are now flagged and skipped during crawling and graph export.
- Channel `about` field is now included in admin search.
- Isolated nodes are grouped into a single community in Louvain and Infomap strategies.
- `KCORE` community strategy now produces finer-grained results using k-shell decomposition.
- The local web server no longer breaks when `export_network` is re-run.
- `export_network` produces a leaner graph mini-site with unused assets removed.
- `export_network` now prints step-by-step progress so you can follow what is happening.
- Graph mini-site upgraded to Bootstrap 5.
- Node detail panel shows only the measures that were actually computed for the current export.

### Backward incompatibility
- IE is no longer supported in graph mini-site.


## [0.2] - 2026-03-03
### New features
- Stats page showing month-by-month global channel activity.
- `get_channels` gained a `--fixholes` option to detect and fill gaps in message history.

### Improvements
- `get_channels` output is more detailed and informative.
- `get_channels` now resolves previously unresolved channel references.
- Profile pictures are downloaded only once.
- `FloodWaitError` handling in the crawler is more robust.


## [0.1.2] - 2026-03-02
### Fixed
- Direct channel references in messages are now correctly processed.


## [0.1.1] - 2026-02-23
### Fixed
- The measure selection menu now works correctly.


## [0.1] - 2026-02-21
### Added
- First official release of Pulpit.

---

← [README](README.md)
