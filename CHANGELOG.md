# Changelog

## [0.3] - To be announced
### Improvements
- Channel `about` field is now included in admin search.
- Isolated nodes are grouped into a single community in Louvain and Infomap strategies.
- `KCORE` community strategy now produces finer-grained results using k-shell decomposition.
- The local web server no longer breaks when `export_network` is re-run.
- `export_network` produces a leaner graph mini-site with unused assets removed.

### New features
- Multiple community strategies can be applied simultaneously via `COMMUNITIES_STRATEGY`.

## Backward incompatibility
- IE is no longer supported in graph mini-site.


## [0.2] - 2026-03-03
### Improvements
- `get_channels` output is more detailed and informative.
- `get_channels` now resolves previously unresolved channel references.
- Profile pictures are downloaded only once.
- `FloodWaitError` handling in the crawler is more robust.

### New features
- Stats page showing month-by-month global channel activity.
- `get_channels` gained a `--fixholes` option to detect and fill gaps in message history.


## [0.1.2] - 2026-03-02
### Fixed
- Direct channel references in messages are now correctly processed.


## [0.1.1] - 2026-02-23
### Fixed
- The measure selection menu now works correctly.


## [0.1] - 2026-02-21
### Added
- First official release of TNExp.
