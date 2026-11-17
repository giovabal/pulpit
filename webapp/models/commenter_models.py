"""The analyst's decisions on commenter accounts (Manage → Commenters).

A commenter is the account behind a :class:`~webapp.models.MessageReply`, identified by the reply's
marked ``sender_id`` (positive for a user account). There is no row per account: the accounts and
their activity are read from the stored replies (:mod:`webapp.commenters`), and a
``CommenterReview`` exists only once the analyst has said something about one — whether the
audience statistics keep or leave it out, or a note.
"""

from django.db import models

from webapp.models.base import BaseModel


class CommenterReview(BaseModel):
    """Keep or leave out one commenter account, overriding the automatic bot / bulk flags."""

    sender_id = models.BigIntegerField(unique=True)
    # None = follow the automatic flags; True = always left out; False = always kept.
    excluded = models.BooleanField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"Commenter {self.sender_id}"
