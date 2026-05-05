import os
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from network import tables


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
            action="store_true",
            default=False,
            help=(
                "Optimise the output mini-site for search engine discovery: sets indexable robots tags. "
                "Without this flag the output actively discourages indexing."
            ),
        )
        parser.add_argument(
            "--target",
            dest="target",
            default="",
            help=("Name of the export to write comparison files into (exports/<name>/). Required."),
        )

    def handle(self, *args: Any, **options: Any) -> None:
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
        project_title: str = settings.PROJECT_TITLE
        seo = options["seo"]

        def exists(name: str) -> bool:
            return os.path.isfile(os.path.join(root_target, name))

        self.stdout.write("- compare analysis files")
        compare_files = tables.copy_compare_project(compare_dir, root_target)
        self.stdout.write("- comparison table (html)")
        tables.write_network_compare_table_html(
            output_filename=os.path.join(root_target, "network_compare_table.html"),
            seo=seo,
            project_title=project_title,
        )
        self.stdout.write("- index")
        os.makedirs(root_target, exist_ok=True)
        tables.write_index_html(
            output_filename=os.path.join(root_target, "index.html"),
            seo=seo,
            project_title=project_title,
            include_graph=exists("graph.html"),
            include_3d_graph=exists("graph3d.html"),
            include_channel_html=exists("channel_table.html"),
            include_channel_xlsx=exists("channel_table.xlsx"),
            include_network_html=exists("network_table.html"),
            include_network_xlsx=exists("network_table.xlsx"),
            include_community_html=exists("community_table.html"),
            include_community_xlsx=exists("community_table.xlsx"),
            include_consensus_matrix_html=exists("consensus_matrix.html"),
            include_structural_similarity=exists("structural_similarity.html"),
            include_compare_html=True,
            compare_files=compare_files,
        )

        self.stdout.write(self.style.SUCCESS("\nDone."))
