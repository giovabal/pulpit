"""Near-copy detection: text re-posted without Telegram's forward header.

A *near-copy* is an original (non-forwarded) message whose text is near-identical to an
earlier original message in scope. The citation graph reads it as if the copying channel
had forwarded the earliest publication — Pulpit's text-reuse counterpart of the newspaper
reprinting networks of the Viral Texts project (Smith, Cordell & Dillon 2013; Smith,
Cordell, Dillon & Stramp 2015), where the earliest printing is the origin and every later
reprint an edge toward it. Pacheco et al. (2021) list the same trace — near-identical text
across accounts — among the coordination signals the forward graph cannot see.

**Criterion.** Broder's (1997) *resemblance*: the Jaccard similarity of the two messages'
word-shingle sets, ``|S(a) ∩ S(b)| / |S(a) ∪ S(b)|``, at or above ``threshold``. Shingling
is the standard definition of near-duplicate text since the AltaVista web clustering of
Broder, Glassman, Manasse & Zweig (1997); Henzinger (2006) evaluated it at web scale and
Tao, Abel, Hauff & Houben (WWW 2013) used shingle overlap as the core signal for near-
duplicate tweets. The threshold is application-dependent in that literature (0.5 is
Broder's "roughly the same", 0.8–0.9 "near-exact"); Pulpit defaults to 0.8 — calibrated on
a real corpus, the 0.7–0.8 band is dominated by organisational *templates* with a
substitution (same announcement, another city), which are not copies of a specific post,
while 0.8 and above is verbatim text with a prefix or suffix added.

**Pipeline** (deterministic, no external dependency):

1. *Normalisation* — Unicode NFKC, lower-case, URLs / ``t.me`` links / ``@handles`` /
   e-mail addresses removed, word tokens only (punctuation and emoji drop out). A copy that
   only swaps the link or the signature handle therefore scores 1.0 — Tao et al.'s
   "nearly exact copy" level.
2. *Shingles* — word ``shingle_size``-grams (default 3; shorter than Broder's web setting
   because posts are short). Messages with fewer than ``min_tokens`` tokens are ineligible:
   Jaccard over a handful of shingles is noise.
3. *Per-channel boilerplate removal* — a shingle present in ≥ ``BOILERPLATE_SHARE`` of a
   channel's eligible messages (channels with ≥ ``BOILERPLATE_MIN_MESSAGES`` of them) is a
   header or signature and is removed from that channel's messages. Without it, two unrelated
   posts of one organisation match on their contact block alone, and a genuine re-post with a
   changed header is diluted below the threshold.
4. *Exact all-pairs join* — prefix filtering (Chaudhuri, Ganti & Kaushik 2006; Bayardo, Ma &
   Srikant, WWW 2007; the PPJoin family of Xiao et al.): shingles are ordered by global
   frequency and only each message's prefix is indexed, so every pair at or above the
   threshold is found and verified exactly, with no MinHash approximation.
5. *Orientation* — each copy points to the **earliest** message among its direct matches
   (date, then primary key), regardless of channel. When that earliest match is the copier's
   own earlier post the link is a *self-copy* (an archive re-post); the graph builder treats
   it like a self-forward.

**Interpretive caveat.** A match proves that the same text appeared earlier in another
in-scope channel, not that it was copied *from* there: two channels quoting the same
manifesto years apart will link, and a text first posted outside the corpus credits whichever
in-scope channel posted it first. Every link is therefore exported with its similarity, the
publication lag and the size of its text cluster (``near_copies.csv``) so the analyst can
audit what counted.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import math
import re
import unicodedata
from collections.abc import Iterable

from django.db.models import Q

#: Default Jaccard resemblance at or above which two messages are near-copies.
NEAR_COPY_THRESHOLD = 0.8
#: Default minimum number of normalised word tokens for a message to be eligible.
NEAR_COPY_MIN_TOKENS = 8
#: Default word-shingle size.
NEAR_COPY_SHINGLE_SIZE = 3
#: A shingle present in at least this share of a channel's eligible messages is boilerplate.
BOILERPLATE_SHARE = 0.2
#: Boilerplate is only estimated for channels with at least this many eligible messages.
BOILERPLATE_MIN_MESSAGES = 5
#: Minimum shingles a message must keep after boilerplate removal to stay eligible.
MIN_SHINGLES_AFTER_BOILERPLATE = 3

_URL_RE = re.compile(r"https?://\S+|\bt\.me/\S+|\bwww\.\S+", re.IGNORECASE)
_HANDLE_RE = re.compile(r"@\w+|\S+@\S+\.\S+")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def original_text_q() -> Q:
    """Messages eligible on either side of a near-copy: dated, with text, and carrying no forward
    header of any kind (resolved channel, private channel, hidden user, or a bare forward date)."""
    return (
        Q(forwarded_from__isnull=True)
        & Q(forwarded_from_private__isnull=True)
        & Q(fwd_from_date__isnull=True)
        & Q(fwd_from_from_name="")
        & Q(date__isnull=False)
        & ~Q(message="")
    )


def normalise_tokens(text: str) -> list[str]:
    """Lower-cased NFKC word tokens with URLs, ``t.me`` links, handles and e-mails removed."""
    normalised = unicodedata.normalize("NFKC", text).lower()
    normalised = _URL_RE.sub(" ", normalised)
    normalised = _HANDLE_RE.sub(" ", normalised)
    return _TOKEN_RE.findall(normalised)


def shingle_set(tokens: list[str], size: int) -> set[str]:
    """The set of word ``size``-grams of *tokens* (empty when the text is shorter than *size*)."""
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


@dataclasses.dataclass(frozen=True)
class NearCopy:
    """One copy → origin link: *copy* re-posted the text of the earlier *origin* message."""

    copy_id: int
    copy_channel_id: int
    copy_date: datetime.datetime
    origin_id: int
    origin_channel_id: int
    origin_date: datetime.datetime
    similarity: float
    copy_tokens: int
    origin_tokens: int
    #: Number of in-scope messages near-identical to this one (transitively): a text shared by
    #: ten channels is more likely a common meme or quotation than a copy of one specific post.
    cluster_size: int

    @property
    def is_self_copy(self) -> bool:
        return self.copy_channel_id == self.origin_channel_id

    @property
    def lag_hours(self) -> float:
        return (self.copy_date - self.origin_date).total_seconds() / 3600


def _similar_pairs(docs: dict[int, set[str]], threshold: float) -> dict[tuple[int, int], float]:
    """Every unordered pair of *docs* whose Jaccard resemblance is ≥ *threshold* (exact).

    Prefix filtering: shingles are ordered by global frequency (rare first, ties by text so
    the order is total), each document indexes only its first ``n − ⌈t·n⌉ + 1`` shingles, and
    two documents at or above the threshold must share a shingle inside both prefixes
    (Chaudhuri, Ganti & Kaushik 2006), so the candidates found this way are complete and
    each is verified exactly.
    """
    frequency: collections.Counter[str] = collections.Counter()
    for shingles in docs.values():
        frequency.update(shingles)
    rank = {s: i for i, s in enumerate(sorted(frequency, key=lambda s: (frequency[s], s)))}
    index: dict[str, list[int]] = collections.defaultdict(list)
    pairs: dict[tuple[int, int], float] = {}
    for doc_id in sorted(docs):
        shingles = docs[doc_id]
        ordered = sorted(shingles, key=rank.__getitem__)
        prefix_length = len(ordered) - math.ceil(threshold * len(ordered)) + 1
        candidates: set[int] = set()
        for shingle in ordered[:prefix_length]:
            candidates.update(index[shingle])
            index[shingle].append(doc_id)
        for other in candidates:
            other_shingles = docs[other]
            intersection = len(shingles & other_shingles)
            union = len(shingles) + len(other_shingles) - intersection
            similarity = intersection / union if union else 0.0
            if similarity >= threshold:
                pairs[(min(doc_id, other), max(doc_id, other))] = similarity
    return pairs


def _strip_boilerplate(docs: dict[int, set[str]], channel_of: dict[int, int]) -> dict[int, set[str]]:
    """Remove each channel's recurring shingles (headers, signatures) from that channel's messages."""
    per_channel: dict[int, list[int]] = collections.defaultdict(list)
    for doc_id, channel_id in channel_of.items():
        if doc_id in docs:
            per_channel[channel_id].append(doc_id)
    stripped: dict[int, set[str]] = dict(docs)
    for doc_ids in per_channel.values():
        if len(doc_ids) < BOILERPLATE_MIN_MESSAGES:
            continue
        counts: collections.Counter[str] = collections.Counter()
        for doc_id in doc_ids:
            counts.update(docs[doc_id])
        # At least two occurrences, so a channel at the message floor cannot lose every shingle.
        floor = max(2, math.ceil(BOILERPLATE_SHARE * len(doc_ids)))
        boilerplate = {s for s, c in counts.items() if c >= floor}
        if not boilerplate:
            continue
        for doc_id in doc_ids:
            stripped[doc_id] = docs[doc_id] - boilerplate
    return stripped


def find_near_copies(
    messages: Iterable[tuple[int, int, datetime.datetime, str]],
    *,
    threshold: float = NEAR_COPY_THRESHOLD,
    min_tokens: int = NEAR_COPY_MIN_TOKENS,
    shingle_size: int = NEAR_COPY_SHINGLE_SIZE,
) -> list[NearCopy]:
    """Detect near-copies among *messages* — ``(id, channel_id, date, text)`` tuples.

    Returns one :class:`NearCopy` per message that has at least one earlier match, pointing to
    the earliest of its direct matches (including the copier's own earlier posts, which yield
    self-copies). Sorted by copy date, then id, for reproducible output.
    """
    if not 0 < threshold <= 1:
        raise ValueError(f"near-copy threshold must be in (0, 1], got {threshold}")
    if shingle_size < 1 or min_tokens < shingle_size:
        raise ValueError(
            f"near-copy shingle size must be ≥ 1 and min tokens ≥ shingle size, got {shingle_size} / {min_tokens}"
        )
    channel_of: dict[int, int] = {}
    date_of: dict[int, datetime.datetime] = {}
    tokens_of: dict[int, int] = {}
    docs: dict[int, set[str]] = {}
    for message_id, channel_id, date, text in messages:
        if date is None or not text:
            continue
        tokens = normalise_tokens(text)
        if len(tokens) < min_tokens:
            continue
        docs[message_id] = shingle_set(tokens, shingle_size)
        channel_of[message_id] = channel_id
        date_of[message_id] = date
        tokens_of[message_id] = len(tokens)
    docs = _strip_boilerplate(docs, channel_of)
    docs = {m: s for m, s in docs.items() if len(s) >= MIN_SHINGLES_AFTER_BOILERPLATE}
    if len(docs) < 2:
        return []

    pairs = _similar_pairs(docs, threshold)
    if not pairs:
        return []

    def order_key(message_id: int) -> tuple[datetime.datetime, int]:
        return (date_of[message_id], message_id)

    # Earliest direct match per message, and the connected clusters for the audit column.
    origin_of: dict[int, int] = {}
    similarity_of: dict[int, float] = {}
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        root = node
        while parent.setdefault(root, root) != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for (a, b), similarity in pairs.items():
        parent[find(a)] = find(b)
        for later, earlier in ((a, b), (b, a)):
            if order_key(earlier) < order_key(later):
                current = origin_of.get(later)
                if current is None or order_key(earlier) < order_key(current):
                    origin_of[later] = earlier
                    similarity_of[later] = similarity
    cluster_size: collections.Counter[int] = collections.Counter(find(m) for m in parent)

    links = [
        NearCopy(
            copy_id=copy_id,
            copy_channel_id=channel_of[copy_id],
            copy_date=date_of[copy_id],
            origin_id=origin_id,
            origin_channel_id=channel_of[origin_id],
            origin_date=date_of[origin_id],
            similarity=round(similarity_of[copy_id], 4),
            copy_tokens=tokens_of[copy_id],
            origin_tokens=tokens_of[origin_id],
            cluster_size=cluster_size[find(copy_id)],
        )
        for copy_id, origin_id in origin_of.items()
    ]
    links.sort(key=lambda link: (link.copy_date, link.copy_id))
    return links


def near_copies_for_channels(
    channel_ids: list[int],
    *,
    cutoff_q: Q,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    threshold: float = NEAR_COPY_THRESHOLD,
    min_tokens: int = NEAR_COPY_MIN_TOKENS,
    shingle_size: int = NEAR_COPY_SHINGLE_SIZE,
) -> list[NearCopy]:
    """Near-copies among the alive original messages of *channel_ids* that pass *cutoff_q* (the
    period chokepoint, ``network.utils.channel_cutoff_q``).

    Origins are searched over the channels' whole in-target history, so a copy of an old post
    counts in the window the copy was published in — exactly like a forward of an old post; only
    the *copy* must fall inside ``[start_date, end_date]``.
    """
    from webapp.models import Message

    rows = (
        Message.objects.alive()
        .filter(cutoff_q, original_text_q(), channel_id__in=channel_ids)
        .values_list("id", "channel_id", "date", "message")
        .iterator(chunk_size=5000)
    )
    links = find_near_copies(rows, threshold=threshold, min_tokens=min_tokens, shingle_size=shingle_size)
    if start_date is None and end_date is None:
        return links
    # Same window predicate the forward edges use (``make_date_q``), evaluated by the database so
    # the two agree on time zones; chunked for SQLite's bound-parameter limit.
    from network.utils import make_date_q

    copy_ids = [link.copy_id for link in links]
    in_window: set[int] = set()
    for start in range(0, len(copy_ids), 500):
        chunk = copy_ids[start : start + 500]
        in_window.update(
            Message.objects.filter(pk__in=chunk).filter(make_date_q(start_date, end_date)).values_list("pk", flat=True)
        )
    return [link for link in links if link.copy_id in in_window]
