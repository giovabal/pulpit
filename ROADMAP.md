# Roadmap for Pulpit: Activities for Next Versions

## [0.18]
- channels count diverge in home page and in structural analysis, in this last case is higher: explain why
- in 2d graph options modal windows add a switch for having colored edges (as it is now) or not (use a gray that's good for both light and dark backgrounds). And in "print" style, background color should be white
- in 2d graph options modal windows separate in 2 tabs analysisi options and styles options
- /plan bring layouts and styles of 2D graph to 3D graph
- in channels details page, Forwards received list filter, add a select for "include self-reference", "do not include self-references", "show only self-references"
- Screenshot missing
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
- vacancy needs enough data for being efficient and significant, find academically validated ways to say if data are enough
- nodes could have a category (like individuals, organizations, and so on. Or by nationality), this could be reflected in shapes of nodes in graph (like squares, circles, diamonds, and so on)
- Organization changes overtime.
- group analysis, groups as selectors, similar to whole network analysis

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
