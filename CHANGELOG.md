# Changelog

## [0.3] - To be announced
### Improvements
- Searching channels in admin now involves `about` field too.
- With Louvain and Infomap communities isolated nodes all belongs to the same community.
- `KCORE` community strategy now generates more nuanced results.
- Improved usability of the local python webserver.

### New features
- More than one community strategy can be applied at once.


## [0.2] - 2026-03-03
### Improvements
- `get_channels` now has a better and more informative output.
- `get_channels` now checks for previously unresolved citations and fix them.
- Download of profile pictures is done just one time.
- Better management of FloodWaitError in crawler.

### New features
- Stats page with month-by-month global channel activity.
- `get_channels` has a new option `--fixholes` to search for and fix missing messages.


## [0.1.2] - 2026-03-02
### Fixed
- Direct references to other channels in messages now is processed.


## [0.1.1] - 2026-02-23
### Fixed
- Measure menu is now working.


## [0.1] - 2026-02-21
### Added
- First official release of TNExp.
