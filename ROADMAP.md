# Roadmap for Pulpit: Activities for Next Versions
## [0.21]
- Community evolution visualization: when `--compare` is used, enhance `network_compare_table.html` with a Sankey diagram showing how channels moved between communities across the two exports. Which channels left community A and joined community B? Implemented in JS using the D3.js Sankey module.
- regency weights should be centered on a period of time, and there must regency weights even for the future

## [1.0]
Organization attribution of a channel can change overtime, so it can happens that a channel is in-target only for a period of time.
Basically any organization attribution pass through a model that defines a start and an end, both optional.
Only in that period of time messages are crawled, relationships are measured and so on.

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
------------------------------

Recommended channels [36/83] 6517578024
get_recommended_channels failed for channel_id=6517578024: Invalid channel object. Make sure to pass the right types, for instance making sure that the request is designed for channels or otherwise look for a different one more suited (caused by GetChannelRecommendationsRequest)
Recommended channels [37/83] 6101608700
get_recommended_channels failed for channel_id=6101608700: Invalid channel object. Make sure to pass the right types, for instance making sure that the request is designed for channels or otherwise look for a different one more suited (caused by GetChannelRecommendationsRequest)



----------------------------

[6/83] [id=233] SAMPLE CHANNEL | replies for post #12 (1/10)
Error fetching replies for post 12 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #14 (2/10)
Error fetching replies for post 14 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #26 (4/10)
Error fetching replies for post 26 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #28 (5/10)
Error fetching replies for post 28 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #49 (7/10)
Error fetching replies for post 49 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #71 (8/10)
Error fetching replies for post 71 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #81 (9/10)
Error fetching replies for post 81 in SAMPLE CHANNEL: The message ID used in the peer was invalid (caused by GetRepliesRequest)
[6/83] [id=233] SAMPLE CHANNEL | replies for post #85 (10/10)
