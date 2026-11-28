import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import exporter, publication, site, tables
from webapp.models import Project
from webapp_engine.command_logging import styled_warning_logs


class Command(BaseCommand):
    help = "Compare this structural analysis with a previous one and generate side-by-side comparison tables."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "project_dir",
            metavar="PROJECT_DIR",
            help=(
                "Path to a graph/ output directory from a previous structural_analysis run "
                "(the directory that contains index.html). "
                "Its data/, graph files, *_table.html, and *.xlsx files are copied with _2 suffixes; "
                "network_compare_table.html is generated with side-by-side metrics tables and scatter plots."
            ),
        )
        parser.add_argument(
            "--seo",
            action=argparse.BooleanOptionalAction,
            default=False,
            help=(
                "Optimise the export for search engines once it is published; without it the export keeps "
                "search engines and AI crawlers out. Applied to every page of the target export, the "
                "compared copies included. See docs/export-formats.md#publishing-an-export."
            ),
        )
        parser.add_argument(
            "--public-url",
            dest="public_url",
            default=None,
            metavar="URL",
            help=(
                "The address the target export will be published at (canonical links and sitemap.xml with "
                "--seo). Defaults to the one its structural_analysis run recorded in summary.json."
            ),
        )
        parser.add_argument(
            "--target",
            dest="target",
            default="",
            help=("Name of the export to write comparison files into (exports/<name>/). Required."),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Route logger.warning/error lines (e.g. exporter HTML patching) through
        # self.style so they carry severity colour in the Operations panel.
        with styled_warning_logs(self.style):
            self._handle(*args, **options)

    def _handle(self, *args: Any, **options: Any) -> None:
        compare_dir = os.path.abspath(options["project_dir"])
        if not os.path.isdir(compare_dir):
            raise CommandError(f"Not a directory: {compare_dir!r}")
        if not os.path.isfile(os.path.join(compare_dir, "index.html")):
            raise CommandError(
                f"{compare_dir!r} does not look like a graph/ output directory "
                "(no index.html found). Point to the directory that contains index.html."
            )

        target_name = re.sub(r"[^\w\-]", "-", (options.get("target") or "").strip()).strip("-")
        if not target_name:
            raise CommandError("--target is required: specify the name of the export to write comparison files into.")
        root_target = str(Path(settings.BASE_DIR) / "exports" / target_name)
        # Both exports must be this version's kind of site: the pages of the two are combined under one set of
        # scripts and styles, and an export made before pages carried the shared navigation has neither the
        # markers the site pass fills nor the scripts its own pages were written for.
        for role, folder in (("target", root_target), ("compared", compare_dir)):
            if os.path.isfile(os.path.join(folder, "index.html")) and not site.is_site(folder):
                raise CommandError(
                    f"The {role} export ({folder}) was made by an earlier version of Pulpit and cannot be combined "
                    "with this version's pages. Run its structural analysis again, then compare."
                )
        # Create the target before anything writes into it: copy_compare_project / the table writers
        # below open files directly in root_target, so the directory must already exist.
        os.makedirs(root_target, exist_ok=True)
        project_title: str = Project.load().title
        seo = options["seo"]
        raw_public_url = options.get("public_url")
        if raw_public_url is None:
            raw_public_url = _recorded_public_url(root_target)
        try:
            public_url = publication.normalise_public_url(raw_public_url)
        except ValueError as exc:
            raise CommandError(f"--public-url: {exc}") from exc

        self.stdout.write("- compare analysis files")
        exporter.copy_shared_assets(root_target)
        tables.copy_compare_project(compare_dir, root_target)
        self.stdout.write("- comparison table (html)")
        tables.write_network_compare_table_html(
            output_filename=os.path.join(root_target, "network_compare_table.html"),
            seo=seo,
            project_title=project_title,
        )
        # The landing page, the navigation and the data dictionary are rebuilt from the files now on disk, the
        # compared copies included, and the publication policy is applied to every page.
        self.stdout.write("- overview, navigation, methods record and data dictionary")
        written = site.finalise(root_target, project_title=project_title, seo=seo, public_url=public_url)
        self.stdout.write(f"- publication: {'search-optimised' if seo else 'private'} — {', '.join(written)}")

        self.stdout.write(self.style.SUCCESS("\nDone."))


def _recorded_public_url(root_target: str) -> str:
    """The ``--public-url`` the target export's own run recorded in its summary.json, ``""`` without one."""
    try:
        with open(os.path.join(root_target, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        return ""
    options = summary.get("options") if isinstance(summary, dict) else None
    value = options.get("public_url") if isinstance(options, dict) else None
    return value if isinstance(value, str) else ""
