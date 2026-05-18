# Roadmap for Pulpit: Activities for Next Versions
## [0.21]
- choosing a palette in operations, for 2D and 3D graphs. Create a smart widget. Or include a few and then let choose them in graph.
- persistence of operations options
- Organization changes overtime.
- Community evolution visualization: when `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.
- Home page and channels page seems slow, find a way to have them faster.
- in homepage add a scattered graph that show number of connection / number of effective forwards (ie.: number against multiplicity)
- regency weights should be centered on a period of time, and there must regency weights even for the future
- vacancy needs enough data for being efficient and significant, find academically validated ways to say if data are enough
- nodes could have a category (like individuals, organizations, and so on. Or by nationality), this could be reflected in shapes of nodes in graph (like squares, circles, diamonds, and so on)

## [1.0]
- Zenodo registration
- Have a deep inspection of Python code, search for bugs, bad practices and dead code
- Have a deep inspection of JS code, search for bugs, bad practices and dead code
- Have a deep inspection of HTML and CSS code, search for bugs, bad practices and dead code
- Have a deep inspection of HTML code, make sure the app and the HTML output of analysis are respecting accessibility rules and can provide a decent experience for people using screen readers
- Have a deep inspection of all options accepted by commands, verify their coherence, look for inconsistencies and bad practices
- I need strong layout coherence through all the software, inspect webapp templates and HTML outputs
- Explore the Python code looking for factorizations, propose them to me and wait for approval.
- Explore the JS code looking for factorizations, propose them to me and wait for approval.
- Explore the CSS code looking for factorizations, propose them to me and wait for approval.
- Explore the Django template code looking for factorizations, propose them to me and wait for approval.
