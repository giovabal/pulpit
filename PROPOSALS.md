# Proposals for Pulpit: New Features and Improvements

## 3. Content & Semantic Analysis

### 3.1 — Topic modeling per channel

Run BERTopic or LDA on stored message text to assign each channel to topic clusters. Topics become a new community type: `TOPIC`. This is particularly powerful for researchers who don't know the domain well enough to define Organizations manually.

**Academic basis:** BERTopic (Grootendorst 2022) with multilingual sentence transformers works well for short Telegram messages. Iamverdeci et al. (2023) used this on Ukrainian-conflict Telegram networks.

### 3.2 — Narrative tracking

Rather than just detecting topics, track which narrative frames appear in messages (keyword lists or small embedding classifiers). Count how often each channel uses each narrative. Output narrative adoption rates per channel, and flag channels that adopt new narratives quickly (narrative amplifiers) vs. originate them.

---

## 4. New Network Measures

### 4.4 — Narrative diffusion lag

Measure how quickly a channel adopts content that originated elsewhere (via forwards). Early adopters vs. late amplifiers. Implementable as a per-node measure: average `(message.date - message.forwarded_from.original_date)` for all forwarded messages. Requires storing the original post date of the forwarded message.

---

## 6. Crawling Improvements

### 6.3 — Group/supergroup reply crawling

Supergroups (`megagroup=True`) store discussion replies. Currently, these are crawled as channels but their replies (comments) are not fetched. Fetching replies would reveal which channels' posts generate discussion and who participates. New `Message.reply_to` field and `--crawl-replies` option.

### 6.4 — Reply count per message

Telethon's `Message.replies.replies` (integer, the public reply count shown on broadcast channel posts) is available on every message but not stored. Add a `reply_count IntegerField(null=True)` to the `Message` model and populate it in `get_message()`. Display it in the post footer alongside views and forwards; export it in the channel table XLSX. Useful for distinguishing posts that generate discussion from those that are passively consumed.

---

## 7. Web UI Improvements

### 7.1 — Message filters: minimum views and minimum forwards

The message options dropdown supports sort order and content-type filter but has no quantitative threshold. Add two optional number inputs — "Min views" and "Min forwards" — applied in `_apply_message_options()` in `webapp/views.py`. Useful for surfacing viral posts on high-volume channels without scrolling past thousands of low-reach messages.

### 7.2 — Message filter: pinned status

Pinned and previously-pinned messages are visually distinguished with CSS classes (`is-pinned`, `was-pinned`) but there is no filter to show only pinned posts. Add a "Pinned only" checkbox to the message options dropdown. Pinned posts represent editorial choices and are analytically interesting in their own right.

### 7.3 — Engagement rate chart on channel detail page

Views and message counts are tracked separately in monthly time series, but no engagement-rate chart (average views per message per month) exists. The data is derivable from the existing `MessagesHistoryDataView` and `ViewsHistoryDataView` endpoints, or a dedicated `ChannelEngagementHistoryView` can compute it server-side. Surfaces content effectiveness trends over time.

### 7.4 — Channel list: filter by channel type

The `structural_analysis` CLI already accepts `--channel-types` (Channel, Group, User), and the operations panel has a Channel Types fieldset, but the public channel list page (`/channels/`) has no type filter. Adding Channel / Group / User checkboxes above the channel table would let analysts isolate, for instance, only supergroups in a mixed dataset.

---

## 8. Backoffice Improvements

### 8.1 — Bulk set `uninteresting_after`

The `uninteresting_after` date field is editable per-channel in the edit page, but there is no bulk operation. Analysts working with a large set of channels that all became inactive on the same date must edit each one individually. Extend `ChannelViewSet.bulk_assign()` in `backoffice/api/views.py` to accept an `uninteresting_after` value, and add a date picker to the bulk action bar in the channels table.

---

← [README](README.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">
