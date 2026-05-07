# Roadmap for Pulpit: Activities for Next Versions

## [0.18]
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
- Read the code and review documentation, make the documentation complete and coherent, propose variations.
