"""Perceptual fingerprints of the stored message pictures (``hash_media``, ``crawl_channels --hash-images``).

Two 64-bit hashes per image, computed with Pillow and numpy (no extra dependency):

* **pHash** (Zauner 2010): the image is reduced to 32 × 32 grayscale, its 2-D discrete cosine transform
  taken, and the 8 × 8 lowest frequencies — the DC term excluded — compared with their median. Robust to
  re-encoding, resizing and mild colour or contrast changes; the hash ``network.image_copies`` matches on.
* **dHash**: 9 × 8 grayscale, one bit per horizontal gradient sign — a second, independent fingerprint
  kept for audits and tie-breaks.

A near-uniform image (a blank, a flat colour) has no usable fingerprint — every bit is noise and it would
match every other flat image — so it is skipped, like an unreadable file. Files are hashed once per Telegram
photo id: a forward shares its source's file, so it shares its fingerprint.
"""

import logging
import os
from collections.abc import Callable

from django.conf import settings

import numpy as np
from scipy.fft import dct

logger = logging.getLogger(__name__)

#: Side of the grayscale thumbnail the DCT runs on, and of the low-frequency block kept.
PHASH_SIZE = 32
PHASH_BLOCK = 8
#: Standard deviation (0–255 grayscale) below which a thumbnail counts as uniform and is not hashed.
MIN_GRAY_STD = 4.0


def _to_signed(bits: np.ndarray) -> int:
    """Pack 64 booleans into a signed 64-bit integer (the range a BigIntegerField stores)."""
    value = 0
    for bit in bits.ravel():
        value = (value << 1) | int(bool(bit))
    return value - (1 << 64) if value >= 1 << 63 else value


def fingerprint(path: str) -> tuple[int, int, int, int] | None:
    """``(phash, dhash, width, height)`` of the image at ``path``, or ``None`` when unreadable or uniform."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            gray = img.convert("L")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.debug("cannot hash %s: %s", path, exc)
        return None
    resample = Image.Resampling.LANCZOS
    small = np.asarray(gray.resize((PHASH_SIZE, PHASH_SIZE), resample), dtype=float)
    if small.std() < MIN_GRAY_STD:
        return None
    freq = dct(dct(small, axis=0, norm="ortho"), axis=1, norm="ortho")[:PHASH_BLOCK, :PHASH_BLOCK]
    coeffs = freq.ravel()[1:]  # drop the DC term: it carries brightness, not structure
    phash_bits = np.concatenate([[False], coeffs > np.median(coeffs)])
    diff = np.asarray(gray.resize((PHASH_BLOCK + 1, PHASH_BLOCK), resample), dtype=float)
    dhash_bits = diff[:, 1:] > diff[:, :-1]
    return _to_signed(phash_bits), _to_signed(dhash_bits), width, height


def hamming(a: int, b: int) -> int:
    """Bits that differ between two signed 64-bit hashes."""
    return ((a ^ b) & 0xFFFFFFFFFFFFFFFF).bit_count()


def hash_stored_pictures(
    *,
    limit: int | None = None,
    rehash: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Fingerprint every stored message-picture file not fingerprinted yet (or all with ``rehash``).

    One file per Telegram photo id. A fingerprint whose ``file_name`` no longer matches the stored file
    (the photo was re-downloaded) is refreshed. Returns ``{"hashed", "skipped", "unchanged"}`` counts.
    """
    from webapp.models import ImageFingerprint, MessagePicture

    existing = dict(
        ImageFingerprint.objects.filter(kind=ImageFingerprint.KIND_PICTURE).values_list("telegram_id", "file_name")
    )
    files: dict[int, str] = {}
    for tid, name in (
        MessagePicture.objects.exclude(picture="").values_list("telegram_id", "picture").iterator(chunk_size=5000)
    ):
        files.setdefault(tid, name)
    todo = [(tid, name) for tid, name in files.items() if rehash or existing.get(tid) != name]
    if limit is not None:
        todo = todo[: max(int(limit), 0)]
    counts = {"hashed": 0, "skipped": 0, "unchanged": len(files) - len(todo)}
    total = len(todo)
    for i, (tid, name) in enumerate(todo, start=1):
        result = fingerprint(os.path.join(settings.MEDIA_ROOT, name))
        if result is None:
            counts["skipped"] += 1
        else:
            phash, dhash, width, height = result
            ImageFingerprint.objects.update_or_create(
                telegram_id=tid,
                kind=ImageFingerprint.KIND_PICTURE,
                defaults={"phash": phash, "dhash": dhash, "width": width, "height": height, "file_name": name},
            )
            counts["hashed"] += 1
        if progress and (i % 500 == 0 or i == total):
            progress(f"hashing images … {i}/{total}")
    return counts
