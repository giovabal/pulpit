"""Starter domain categories and the sites filed under them (Manage → Domains edits both).

A starting point, not a classification: everything else stays uncategorised until the analyst files it,
and any assignment here can be changed. The ``role`` drives the outbound-link layer's share measures.
"""

from django.db import migrations

STARTER = [
    (
        "Mainstream social",
        "#1d9bf0",
        "mainstream",
        "Large mainstream social networks, moderated under their platforms' terms of service.",
        [
            "x.com",
            "twitter.com",
            "fxtwitter.com",
            "vxtwitter.com",
            "fixupx.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "vk.com",
            "reddit.com",
            "threads.net",
        ],
    ),
    (
        "Video",
        "#e62117",
        "mainstream",
        "Mainstream video hosting.",
        ["youtube.com", "youtu.be", "vimeo.com", "music.youtube.com", "twitch.tv"],
    ),
    (
        "Alternative platform",
        "#7b3fa0",
        "alternative",
        "Social and video platforms marketed as free-speech alternatives, with lighter moderation.",
        [
            "gab.com",
            "odysee.com",
            "bitchute.com",
            "rumble.com",
            "minds.com",
            "gettr.com",
            "truthsocial.com",
            "parler.com",
            "bastyon.com",
            "brighteon.com",
            "lbry.tv",
            "dlive.tv",
        ],
    ),
    (
        "Messaging",
        "#5865f2",
        "",
        "Invitation links to other messaging services and chat servers.",
        ["discord.gg", "discord.com", "whatsapp.com", "signal.group", "signal.me", "matrix.to", "element.io"],
    ),
    (
        "Crowdfunding / donations",
        "#f2a900",
        "monetisation",
        "Donation, crowdfunding and membership-payment services.",
        [
            "givesendgo.com",
            "gofundme.com",
            "patreon.com",
            "ko-fi.com",
            "buymeacoffee.com",
            "subscribestar.com",
            "paypal.me",
            "paypal.com",
            "cash.app",
            "donorbox.org",
            "entropystream.live",
            "zrzutka.pl",
            "pomagam.pl",
            "siepomaga.pl",
            "patronite.pl",
        ],
    ),
    (
        "Shop / merch",
        "#2e9e5b",
        "monetisation",
        "Shops and print-on-demand merchandise services; a movement's own shop is the analyst's to file.",
        [
            "amazon.com",
            "etsy.com",
            "redbubble.com",
            "teespring.com",
            "spreadshirt.com",
            "myshopify.com",
            "bigcartel.com",
        ],
    ),
    (
        "Blog / newsletter",
        "#ff6719",
        "",
        "Blogging and newsletter platforms (each platform-hosted outlet is its own site).",
        ["substack.com", "medium.com", "blogspot.com", "wordpress.com", "tumblr.com", "ghost.io"],
    ),
    (
        "Archive",
        "#6b7280",
        "",
        "Web archives — often used to share a page without sending traffic to it.",
        ["archive.org", "web.archive.org", "archive.ph", "archive.today", "archive.is", "ghostarchive.org"],
    ),
    (
        "File hosting",
        "#0f766e",
        "",
        "File and document hosting.",
        ["mega.nz", "drive.google.com", "docs.google.com", "dropbox.com", "mediafire.com", "files.catbox.moe"],
    ),
    (
        "Shortener",
        "#a3a3a3",
        "",
        "Link shorteners: the destination is hidden (not resolved — that would take a network request per link).",
        [
            "bit.ly",
            "tinyurl.com",
            "t.co",
            "goo.gl",
            "ow.ly",
            "is.gd",
            "cutt.ly",
            "rb.gy",
            "shorturl.at",
            "linktr.ee",
            "lnk.bio",
        ],
    ),
]


def add_starter(apps, schema_editor):
    DomainCategory = apps.get_model("webapp", "DomainCategory")
    Domain = apps.get_model("webapp", "Domain")
    for name, color, role, description, sites in STARTER:
        category, _ = DomainCategory.objects.get_or_create(
            name=name, defaults={"color": color, "role": role, "description": description}
        )
        for site in sites:
            Domain.objects.get_or_create(name=site, defaults={"category": category})


def remove_starter(apps, schema_editor):
    DomainCategory = apps.get_model("webapp", "DomainCategory")
    DomainCategory.objects.filter(name__in=[row[0] for row in STARTER]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("webapp", "0074_domains"),
    ]

    operations = [migrations.RunPython(add_starter, remove_starter)]
