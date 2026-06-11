# Proposals for Pulpit: New Features and Improvements

## 1 — Topic modeling per channel

Run BERTopic or LDA on stored message text to assign each channel to topic clusters. Topics become a new community type: `TOPIC`. This is particularly powerful for researchers who don't know the domain well enough to define Organizations manually.

**Academic basis:** BERTopic (Grootendorst 2022) with multilingual sentence transformers works well for short Telegram messages. Iamverdeci et al. (2023) used this on Ukrainian-conflict Telegram networks.

---

## 2 — Narrative tracking

Rather than just detecting topics, track which narrative frames appear in messages (keyword lists or small embedding classifiers). Count how often each channel uses each narrative. Output narrative adoption rates per channel, and flag channels that adopt new narratives quickly (narrative amplifiers) vs. originate them.

---

← [README](README.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">
