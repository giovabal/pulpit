# Chars in the BMP whose Unicode default is *text* presentation: without a
# trailing U+FE0F (Variation Selector-16) they render as monochrome glyphs
# instead of colored emoji. The Telegram reaction stream supplies them bare,
# so we re-attach VS16 at render time. List is the set actually seen as
# Telegram reaction emojis (full table in emoji-variation-sequences.txt).
_EMOJI_DEFAULT_TEXT = frozenset(
    "❤❣♥♦♠♣"  # hearts, suits
    "☺☹"  # smileys
    "✌✋✊☝✍"  # hand gestures
    "☕☘⚠✴✳"  # coffee, shamrock, warning, stars
    "☄☂☔"  # comet, umbrella
)


def emoji_present(s: str) -> str:
    """Append U+FE0F to single dual-presentation default-text chars so browsers render them as colored emoji."""
    if not s or "️" in s or "︎" in s:
        return s
    if len(s) == 1 and s in _EMOJI_DEFAULT_TEXT:
        return s + "️"
    return s
