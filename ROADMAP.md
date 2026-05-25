# Roadmap for Pulpit: Activities for Next Versions
## [0.22]
- Community evolution visualization: when `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.
- regency weights should be centered on a period of time, and there must regency weights even for the future

- ForceAtlas2 3D (100 iterations) … done
Traceback (most recent call last):
  File "/home/jo/job/anpi/pulpit_ac/manage.py", line 23, in <module>
  File "/home/jo/job/anpi/pulpit_ac/manage.py", line 19, in main
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/django/core/management/__init__.py", line 443, in execute_from_command_line
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/django/core/management/__init__.py", line 437, in execute
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/django/core/management/base.py", line 420, in run_from_argv
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/django/core/management/base.py", line 464, in execute
    output = self.handle(*args, **options)
  File "/home/jo/job/anpi/pulpit_ac/network/management/commands/structural_analysis.py", line 1958, in handle
    entry = self._run_year_export(
  File "/home/jo/job/anpi/pulpit_ac/network/management/commands/structural_analysis.py", line 1249, in _run_year_export
    year_extra_positions[name.lower()] = _extra_layout_funcs_2d[name](graph)
  File "/home/jo/job/anpi/pulpit_ac/network/layout.py", line 239, in tsne_positions_2d
    embedding = TSNE(n_components=2, random_state=42, perplexity=perplexity).fit_transform(features)
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/sklearn/utils/_set_output.py", line 316, in wrapped
    data_to_wrap = f(self, X, *args, **kwargs)
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/sklearn/base.py", line 1336, in wrapper
    return fit_method(estimator, *args, **kwargs)
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/sklearn/manifold/_t_sne.py", line 1135, in fit_transform
  File "/home/jo/job/anpi/pulpit_ac/.venv/lib/python3.12/site-packages/sklearn/manifold/_t_sne.py", line 847, in _check_params_vs_input
    raise ValueError(
ValueError: perplexity (5) must be less than n_samples (5)



## [1.0]
Have a review of all measurements available in Pulpit. Read documentation for having a good grasp of what is the Pulpit goal. Then:
1. find measures that Pulpit offers and that aren't useful in this specific case;
1. find measures that Pulpit doesn't offers yet and that can be useful in this specific case.
Let me choose which to remove and which to accept, if any.
- Time-bounded organization attribution — a channel can be in-target only for a period, or in-target across a long span under alternating organizations; attribution goes through a model with optional start/end (None = channel creation / present). Only messages within in-target periods are crawled and measured; `to_inspect` channels are always crawled. … done in [0.23] (the `ChannelAttribution` model).
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
