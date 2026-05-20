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

--------------------

[23/38] [id=42] Sample Channel (Censored) | hole-fix limit reached, checkpoint saved

-------------------

[63/83] [id=60] 6549155363 | fetching profile pictures
[63/83] [id=60] 6549155363 | fetching channel details
Error updating info for 6549155363: Cannot cast InputPeerUser to any kind of InputChannel.
updating info failed for 6549155363
Traceback (most recent call last):
  File "/path/to/pulpit/crawler/management/commands/crawl_channels.py", line 128, in per_channel_step
  File "/path/to/pulpit/crawler/management/commands/crawl_channels.py", line 505, in _refresh_channel_info_for_channel
  File "/path/to/pulpit/crawler/channel_crawler.py", line 333, in refresh_channel_info
  File "/path/to/pulpit/crawler/channel_crawler.py", line 154, in set_more_channel_details
    channel_full_info = self.api_client.client(GetFullChannelRequest(channel=telegram_channel))
  File "/path/to/pulpit/.venv/lib/python3.12/site-packages/telethon/sync.py", line 39, in syncified
    return loop.run_until_complete(coro)
  File "/usr/lib/python3.12/asyncio/base_events.py", line 687, in run_until_complete
    return future.result()
  File "/path/to/pulpit/.venv/lib/python3.12/site-packages/telethon/client/users.py", line 30, in __call__
    return await self._call(self._sender, request, ordered=ordered)
  File "/path/to/pulpit/.venv/lib/python3.12/site-packages/telethon/client/users.py", line 44, in _call
  File "/path/to/pulpit/.venv/lib/python3.12/site-packages/telethon/tl/functions/channels.py", line 805, in resolve
    self.channel = utils.get_input_channel(await client.get_input_entity(self.channel))
  File "/path/to/pulpit/.venv/lib/python3.12/site-packages/telethon/utils.py", line 258, in get_input_channel
  File "/path/to/pulpit/.venv/lib/python3.12/site-packages/telethon/utils.py", line 133, in _raise_cast_fail
    raise TypeError('Cannot cast {} to any kind of {}.'.format(
TypeError: Cannot cast InputPeerUser to any kind of InputChannel.


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
