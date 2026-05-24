# Roadmap for Pulpit: Activities for Next Versions
## [0.22]
- Community evolution visualization: when `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.
- regency weights should be centered on a period of time, and there must regency weights even for the future

## [1.0]
Have a review of all measurements available in Pulpit. Read documentation for having a good grasp of what is the Pulpit goal. Then:
1. find measures that Pulpit offers and that aren't useful in this specific case;
1. find measures that Pulpit doesn't offers yet and that can be useful in this specific case.
Let me choose which to remove and which to accept, if any.
---
Organization attribution of a channel can change overtime, so it can happens that a channel is in-target only for a period of time, or that is in-target over a long time but under two alternating organizations.
Basically any organization attribution pass through a model that defines a start and an end, both optional.
Only for period of time where a channel belongs to in-target organizations messages are crawled, relationships are measured and so on.
If `to_inspect` it's always crawled, as it is now.
If starting time is None it means that organization attribution goes back to channel creation time, if ending time is None it means that organization attribution goes up to present time. Starting and ending times are None by default.

This is a deep refactorization. I need you to write a clear plan for python code, for analysis, for UI and everything that's needed. In a few spots there are decision to take, so ask me throughly and do not make your own decision.
---
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


## [2.0]
https://github.com/textgain/grasp
