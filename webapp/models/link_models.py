"""The web sites channels link to, and the analyst's categories for them (Manage → Domains).

``Domain`` holds one row per *site* — a registered domain, or a whole platform-hosted outlet such as
``name.substack.com`` (:func:`network.links.site_of`) — with the counts of its last indexing
(``index_domains``, over the in-target channels' messages). ``DomainCategory`` is the analyst's grouping:
a starter list ships with the migrations, and every assignment can be changed. A category's ``role``
feeds the outbound-link layer's share measures (``--links``): which categories count as monetisation,
as mainstream platforms, as alternative platforms.
"""

from django.db import models

from webapp.models.base import BaseColorModel, BaseModel


class DomainCategory(BaseColorModel):
    """A kind of site (mainstream social, crowdfunding, shop, …), with a colour for the charts."""

    ROLE_NONE = ""
    ROLE_MONETISATION = "monetisation"
    ROLE_MAINSTREAM = "mainstream"
    ROLE_ALTERNATIVE = "alternative"
    ROLE_CHOICES = (
        (ROLE_NONE, "—"),
        (ROLE_MONETISATION, "Monetisation"),
        (ROLE_MAINSTREAM, "Mainstream platform"),
        (ROLE_ALTERNATIVE, "Alternative platform"),
    )

    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_NONE, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "domain categories"

    def __str__(self) -> str:
        return self.name


class Domain(BaseModel):
    """One linked site, its category and the counts of the last ``index_domains`` run."""

    name = models.CharField(max_length=255, unique=True)
    category = models.ForeignKey(
        DomainCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="domains"
    )
    note = models.TextField(blank=True, default="")
    # Index counts over the in-target channels' alive, in-period messages: one per (message, site).
    posts = models.PositiveIntegerField(default=0)
    channels = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-posts", "name"]

    def __str__(self) -> str:
        return self.name
