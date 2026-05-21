# Roadmap for Pulpit: Activities for Next Versions
## [0.21]
---
When saving .operations* options files, the button opens a modal where a title is asked.
This title will be the first option in the file, under the section [meta]. A second option in [meta] will be the pulpit version used to create them.
File name will be .operations-[action]-[timestamp]
When clicking load button a modal will be opened and a list of .operations-[action]* options can be choosen, each line will show title and a human readable timestamp. Selecting one of those loads the options into the form.
Base options files are now present and committed: .operations-[action] (without the timestamp and with "Pulpit default" as title). Those (and only them) are committed.
The file listing, the writing, the reading are all actions made by python code, interaction happens via specific API.
Writing sends the form to the API and it is written by python code. Loading reads from API and populates form via JS.
---
Fan out subagents for this task. Have a deep verification of their findings before accepting them.
Have a deep inspection of all options accepted by commands, verify their coherence, look for inconsistencies and bad practices.
Any change must be reflected in how API for operations defaults works.
---
I need to change the behaviour of operations options.
Default values are stored in ~/configuration/.operations* files
They are loaded and saved as it is now.
[telegram] options should be in .env, not in .operations* files
Their values are used as a way to pre-populate forms, and in no other way. In particular they are not used by CLI operations.
Next to load and save options buttons there must be a "write CLI command", it will send actual form to the API and the API will answers with a command line that will be shown as it is shown now, in red, bottom part of the form.
Moreover default settings in settings.py should be set in a way that they basicly do nothing if CLI commands are invoked bare.
---

- Community evolution visualization: when `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.
- regency weights should be centered on a period of time, and there must regency weights even for the future

## [1.0]
Have a review of all measurements available in Pulpit. Read documentation for having a good grasp of what is the Pulpit goal. Then:
1. find measures that Pulpit offers and that aren't useful in this specific case;
1. find measures that Pulpit doesn't offers yet and that can be useful in this specific case.
Let me choose which to remove and which to accept, if any.

---
Organization attribution of a channel can change overtime, so it can happens that a channel is in-target only for a period of time.
Basically any organization attribution pass through a model that defines a start and an end, both optional.
Only in that period of time messages are crawled, relationships are measured and so on.
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
