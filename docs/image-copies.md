# Image copies

*Who re-posts whose pictures without forwarding them?*

A movement that organises through images — chapter posters, training photos, banners from a shared "propaganda kit" — spreads much of its content by **re-uploading** it: a channel saves the picture and posts it again as its own. Telegram records no forward header, so the citation graph never sees the borrowing. Pulpit can find these re-posts by comparing the stored pictures, and read each one as a citation of the earliest post that showed the image.

Two steps: **fingerprint** the stored pictures (once, then incrementally), and **detect** the copies at export time.

---

## 1. Fingerprints

```bash
python manage.py hash_media             # every stored picture not fingerprinted yet
python manage.py hash_media --limit 500 # at most 500 files
python manage.py hash_media --rehash    # all of them again
```

…or tick **Index → Hash stored images** on the Crawl card (`crawl_channels --hash-images`), which runs the same step after each crawl. Each stored picture file — one per Telegram photo id, so a forward shares its source's fingerprint — gets two 64-bit perceptual hashes (`webapp.models.ImageFingerprint`):

- **pHash** (Zauner 2010): the image reduced to 32 × 32 grayscale, its 2-D discrete cosine transform, and the 8 × 8 lowest frequencies (the DC term left out) compared with their median. Robust to re-encoding, resizing and mild colour or contrast changes; this is the hash the matching uses.
- **dHash**: a 9 × 8 gradient-sign hash, kept for audits.

A near-uniform image (a blank, a flat colour) gets no fingerprint — its bits are noise and it would match every other flat image — and neither does an unreadable file. Hashing takes about 10 ms per picture; *Maintenance → Orphan media* also drops the fingerprints of photos no message references any more.

## 2. Detection

`--image-copy-edges` (panel: **Edge weights → Include image copies as edges**; off by default):

- **Unit = a post.** An album (one Telegram media group) is one post, however many pictures it holds, so a re-posted five-photo album counts once. A post's date is its first message's.
- **Only posts without a forward header take part.** A forward is a citation already; a forward of a picture keeps the photo id, so it never counts twice.
- **Same image** = the same Telegram photo id (a server-side re-post; distance 0), or pHashes differing in at most `--image-copy-distance` of 64 bits (default **6**; panel *Image-copy distance ≤*). Re-encoded and resized copies sit well inside 6; distinct images differ in about 32 bits. A picture not fingerprinted yet matches by photo id only.
- **Boilerplate**: an image on at least 20 % of a channel's picture posts (its logo, a banner, a watermark template) is ignored for that channel, once it has at least 5 picture posts.
- **Earliest origin**: each post points to the earliest post, by date then id, that shows one of its images — in any channel in scope, its own included (a *self-copy*, which follows `--self-references` like a self-forward). Origins are searched over the channels' whole in-target history; only the copy has to fall inside the date window.

Matching is exact: every pair of distinct hashes is compared (XOR and bit count, in blocks), which takes seconds for tens of thousands of pictures.

## What it changes

Each copy is one citation event copier → origin:

| Where | Effect |
| :-- | :-- |
| Edges | a new raw count `weight_image_copies` beside `weight_forwards`, `weight_mentions`, `weight_copies`; every edge-weight strategy counts it, and the copying post joins the citing-message denominator of `PARTIAL_REFERENCES` unless it already cites (a `t.me/` link, a text near-copy) |
| Amplification | a copy received counts as a forward received |
| Content originality | a copy made counts as a non-original message (once per post, even when its text is a near-copy too) |
| Diffusion lag | a cross-channel copy contributes its lag (copy date − origin date) |
| Dominance, MRQAP, label mixing, dyadic export | follow the raw counts; `dyads/events.csv` lists each copy with type `image_copy` |
| Audit | `data/image_copies.csv` (and per timeline period): both posts, channels, dates, lag, distance, image-cluster size, self-copy flag |

## Visual originality

`VISUALORIGINALITY` (a measure; panel chip *Visual Originality*) is the share of a channel's picture posts whose images are seen first in that channel: `1 − posts copying another channel's earlier image / picture posts`, over posts without a forward header inside the window. A self-copy stays original. Empty for a channel with no such picture post. It runs the detection itself when image-copy edges are off, with the same distance. Read it as a proxy for *documenting one's own activity* — photographing one's own training and events — against redistributing a shared visual stock.

## Guardrails

- **A match shows the same image appeared earlier in scope, not who made it.** The origin is the first in-scope post, not the author: a meme from outside the scope is credited to whichever monitored channel posted it first. The `cluster_size` column helps: a picture shown by many posts is more likely a common meme than a copy of one channel.
- **Backup and mirror channels.** A group that keeps a backup channel ("… (Censored)", "… Uncensored") and re-posts its pictures there produces a heavy copy edge between its own two channels. On the Active Club corpus about half of the cross-channel copies were of this kind, often months after the original. Look at the heaviest copy pairs in `data/image_copies.csv` and read them as one actor's internal traffic, not as diffusion between groups.
- **Crops, mirror images and text overlays** beyond the distance are missed; a heavily cropped poster is a different image to pHash. Widening the distance catches more of them and starts to match unrelated images with similar layouts (dark backgrounds, centred logos).
- **Only stored pictures count.** Videos, GIFs and stickers are not compared; pictures the crawler did not download (the *Image download* toggle) match by photo id only — a re-upload, which gets a new id, is then invisible.
- **Coverage of the hashes.** Run `hash_media` before the export; the run's `PARAMETERS.md` lists the rules, and the copies found are counted in `summary.json` (`image_copies`).

## References

- Zauner, C. (2010) *Implementation and benchmarking of perceptual image hash functions.* Master's thesis, Upper Austria University of Applied Sciences.
- Zannettou, S., Caulfield, T., Blackburn, J., De Cristofaro, E., Sirivianos, M., Stringhini, G. & Suarez-Tangil, G. (2018) "On the origins of memes by means of fringe web communities." *Proceedings of the Internet Measurement Conference 2018*, 188–202. [doi:10.1145/3278532.3278550](https://doi.org/10.1145/3278532.3278550) — pHash clustering of images across communities.

---

← [Event impact](event-impact.md) · [Outbound links](outbound-links.md) →
