import json
import re
import shutil
from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

from network import community as net_community, measures as net_measures, vacancy_analysis
from runner import tasks
from webapp.models import ChannelGroup, ChannelVacancy, SearchTerm

TASK_DEFINITIONS: dict[str, dict[str, str]] = {
    "search_channels": {
        "title": "Search Channels",
        "description": "Search Telegram for channels matching each SearchTerm in the database.",
        "icon": "bi-search",
    },
    "crawl_channels": {
        "title": "Crawl Channels",
        "description": "Crawl all in-target channels and resolve cross-channel references.",
        "icon": "bi-cloud-download",
    },
    "structural_analysis": {
        "title": "Structural Analysis",
        "description": "Build the graph, compute measures, detect communities, and write output files.",
        "icon": "bi-diagram-3",
    },
    "compare_analysis": {
        "title": "Compare Analysis",
        "description": "Compare this structural analysis with a previous one and generate side-by-side comparison tables and scatter plots.",
        "icon": "bi-intersect",
    },
}


class AnalysisPageView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "runner/analysis.html")


class OperationsView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        task_info = []
        for name, defn in TASK_DEFINITIONS.items():
            status = tasks.get_status(name)
            task_info.append({**defn, "name": name, **status})
        channel_groups = list(ChannelGroup.objects.values("key", "name"))
        has_vacancies = ChannelVacancy.objects.exists()

        def _expand(raw: str, all_set: set) -> set:
            items = {s.strip().upper() for s in raw.split(",") if s.strip()}
            return all_set if "ALL" in items else items

        ad = {
            # Crawl defaults
            "CRAWL_GET_CHANNELS_INFO": settings.CRAWL_GET_CHANNELS_INFO,
            "CRAWL_MINE_ABOUT_TEXTS": settings.CRAWL_MINE_ABOUT_TEXTS,
            "CRAWL_FETCH_RECOMMENDED": settings.CRAWL_FETCH_RECOMMENDED,
            "CRAWL_RETRY_LOST_AND_PRIVATE": settings.CRAWL_RETRY_LOST_AND_PRIVATE,
            "CRAWL_GET_NEW_MESSAGES": settings.CRAWL_GET_NEW_MESSAGES,
            "CRAWL_FETCH_REPLIES": settings.CRAWL_FETCH_REPLIES,
            "CRAWL_REFRESH_MESSAGES_STATS": settings.CRAWL_REFRESH_MESSAGES_STATS,
            "CRAWL_FIXHOLES": settings.CRAWL_FIXHOLES,
            "CRAWL_FIX_MISSING_MEDIA": settings.CRAWL_FIX_MISSING_MEDIA,
            "CRAWL_RETRY_LOST_MESSAGES": settings.CRAWL_RETRY_LOST_MESSAGES,
            "CRAWL_RETRY_REFERENCES": settings.CRAWL_RETRY_REFERENCES,
            "CRAWL_FORCE_RETRY_UNRESOLVED": settings.CRAWL_FORCE_RETRY_UNRESOLVED,
            "CRAWL_IN_DEGREES": settings.CRAWL_IN_DEGREES,
            "CRAWL_OUT_DEGREES": settings.CRAWL_OUT_DEGREES,
            # SA outputs
            "SA_OUTPUT_GRAPH": settings.SA_OUTPUT_GRAPH,
            "SA_OUTPUT_3DGRAPH": settings.SA_OUTPUT_3DGRAPH,
            "SA_OUTPUT_HTML": settings.SA_OUTPUT_HTML,
            "SA_OUTPUT_XLSX": settings.SA_OUTPUT_XLSX,
            "SA_OUTPUT_GEXF": settings.SA_OUTPUT_GEXF,
            "SA_OUTPUT_GRAPHML": settings.SA_OUTPUT_GRAPHML,
            "SA_OUTPUT_CSV": settings.SA_OUTPUT_CSV,
            "SA_SEO": settings.SA_SEO,
            "SA_VERTICAL_LAYOUT": settings.SA_VERTICAL_LAYOUT,
            "SA_DRAW_DEAD_LEAVES": settings.SA_DRAW_DEAD_LEAVES,
            "SA_STRUCTURAL_SIMILARITY": settings.SA_STRUCTURAL_SIMILARITY,
            "SA_CONSENSUS_MATRIX": settings.SA_CONSENSUS_MATRIX,
            "SA_TIMELINE_STEP": settings.SA_TIMELINE_STEP,
            "SA_INCLUDE_MENTIONS": settings.SA_INCLUDE_MENTIONS,
            "SA_INCLUDE_SELF_REFERENCES": settings.SA_INCLUDE_SELF_REFERENCES,
            "SA_INCLUDE_LOST": settings.SA_INCLUDE_LOST,
            "SA_INCLUDE_PRIVATE": settings.SA_INCLUDE_PRIVATE,
            # SA numeric params
            "SA_FA2_ITERATIONS": settings.SA_FA2_ITERATIONS,
            "SA_SPREADING_RUNS": settings.SA_SPREADING_RUNS,
            "SA_DIFFUSION_WINDOW": settings.SA_DIFFUSION_WINDOW,
            "SA_LEIDEN_COARSE_RESOLUTION": settings.SA_LEIDEN_COARSE_RESOLUTION,
            "SA_LEIDEN_FINE_RESOLUTION": settings.SA_LEIDEN_FINE_RESOLUTION,
            "SA_MCL_INFLATION": settings.SA_MCL_INFLATION,
            "SA_COMMUNITY_DISTRIBUTION_THRESHOLD": settings.SA_COMMUNITY_DISTRIBUTION_THRESHOLD,
            "SA_RECENCY_WEIGHTS": settings.SA_RECENCY_WEIGHTS or "",
            "SA_VACANCY_MONTHS_BEFORE": settings.SA_VACANCY_MONTHS_BEFORE,
            "SA_VACANCY_MONTHS_AFTER": settings.SA_VACANCY_MONTHS_AFTER,
            "SA_VACANCY_MAX_CANDIDATES": settings.SA_VACANCY_MAX_CANDIDATES,
            "SA_VACANCY_PPR_ALPHA": settings.SA_VACANCY_PPR_ALPHA,
            # SA string params
            "SA_EDGE_WEIGHT_STRATEGY": settings.SA_EDGE_WEIGHT_STRATEGY,
            # SA expanded sets for checkbox groups
            "sa_measures": _expand(settings.SA_MEASURES, set(net_measures.VALID_MEASURES)),
            "sa_strategies": _expand(settings.SA_COMMUNITY_STRATEGIES, set(net_community.VALID_STRATEGIES)),
            "sa_stat_groups": _expand(settings.SA_NETWORK_STAT_GROUPS, set(net_measures.ALL_NETWORK_STAT_GROUPS)),
            "sa_layouts_2d": {s.strip().upper() for s in settings.SA_LAYOUTS_2D.split(",") if s.strip()},
            "sa_layouts_3d": {s.strip().upper() for s in settings.SA_LAYOUTS_3D.split(",") if s.strip()},
            "sa_vacancy_measures": _expand(settings.SA_VACANCY_MEASURES, set(vacancy_analysis.ALL_VACANCY_MEASURES)),
        }

        return render(
            request,
            "runner/operations.html",
            {
                "tasks": task_info,
                "default_channel_types": set(settings.DEFAULT_CHANNEL_TYPES),
                "channel_groups": channel_groups,
                "has_vacancies": has_vacancies,
                "ad": ad,
            },
        )


class RunTaskView(View):
    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        if tasks.get_status(task)["status"] == "running":
            return JsonResponse({"error": "Task already running"}, status=409)
        if task == "search_channels" and request.POST.get("save_terms"):
            extra_raw = request.POST.get("extra_terms", "")
            for line in extra_raw.splitlines():
                word = " ".join(line.split()).lower()
                if word:
                    SearchTerm.objects.get_or_create(word=word)
        args = _build_args(task, request.POST)
        try:
            tasks.launch(task, args)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        return JsonResponse({"status": "started", "args": args})


class AbortTaskView(View):
    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        sent = tasks.abort(task)
        return JsonResponse({"sent": sent})


class ResetTaskView(View):
    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        ok = tasks.reset(task)
        return JsonResponse({"reset": ok})


class TaskStatusView(View):
    def get(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        try:
            offset = max(0, int(request.GET.get("offset", 0)))
        except (ValueError, TypeError):
            return JsonResponse({"error": "invalid offset"}, status=400)
        status = tasks.get_status(task)
        lines, new_offset = tasks.get_log_lines(task, offset)
        return JsonResponse({**status, "lines": lines, "next_offset": new_offset})


class GraphDirsView(View):
    """Scan for valid export directories usable as compare-analysis targets."""

    def get(self, request: HttpRequest) -> JsonResponse:
        current_graph = Path(settings.BASE_DIR) / settings.GRAPH_OUTPUT_DIR
        found: list[dict] = []
        seen: set[str] = set()

        def _check(path: Path) -> None:
            key = str(path.resolve())
            if key in seen:
                return
            seen.add(key)
            if path.name.endswith((".tmp", ".old")):
                return  # staging or backup directory from an in-progress / interrupted export
            if path.resolve() == current_graph.resolve():
                return  # cannot compare a network with itself
            if not (path / "index.html").exists():
                return
            entry: dict = {
                "path": str(path),
                "title": None,
                "export_date": None,
                "total_nodes": None,
                "total_edges": None,
            }
            meta_path = path / "data" / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    entry["title"] = meta.get("project_title") or None
                    entry["export_date"] = meta.get("export_date") or None
                    entry["total_nodes"] = meta.get("total_nodes")
                    entry["total_edges"] = meta.get("total_edges")
                except (json.JSONDecodeError, OSError):
                    pass
            found.append(entry)

        # Scan named exports in BASE_DIR/exports/
        exports_root = Path(settings.BASE_DIR) / "exports"
        try:
            for item in sorted(exports_root.iterdir()):
                if item.is_dir():
                    _check(item)
        except (PermissionError, OSError):
            pass

        # Scan sibling directories of BASE_DIR for other Pulpit projects.
        parent = Path(settings.BASE_DIR).parent
        try:
            for item in sorted(parent.iterdir()):
                if not item.is_dir():
                    continue
                # Direct graph/ dir (e.g. sibling_project/graph/)
                _check(item / settings.GRAPH_OUTPUT_DIR)
                # Or the directory itself if it looks like a graph export
                _check(item)
        except (PermissionError, OSError):
            pass

        found.sort(key=lambda d: (d.get("export_date") or "", d["path"]), reverse=True)
        return JsonResponse({"dirs": found})


class ExportsListView(View):
    """List all named exports (BASE_DIR/exports/*/summary.json)."""

    def get(self, request: HttpRequest) -> JsonResponse:
        exports: list[dict] = []
        exports_root = Path(settings.BASE_DIR) / "exports"
        try:
            for item in sorted(exports_root.iterdir()):
                if not item.is_dir() or item.name.endswith((".tmp", ".old")):
                    continue
                summary_path = item / "summary.json"
                if not summary_path.exists():
                    continue
                try:
                    data = json.loads(summary_path.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                exports.append(
                    {
                        "name": item.name,
                        "created_at": data.get("created_at"),
                        "pulpit_version": data.get("pulpit_version", ""),
                        "nodes": data.get("nodes"),
                        "edges": data.get("edges"),
                        "options": data.get("options", {}),
                    }
                )
        except (PermissionError, OSError):
            pass
        exports.sort(key=lambda e: e.get("created_at") or "", reverse=True)
        return JsonResponse({"exports": exports})


class ExportDetailView(View):
    """Return the full summary.json for a named export, or delete the export directory."""

    def get(self, request: HttpRequest, name: str) -> JsonResponse:
        if not re.match(r"^[\w\-]+$", name):
            return JsonResponse({"error": "invalid name"}, status=400)
        exports_root = (Path(settings.BASE_DIR) / "exports").resolve()
        path = (exports_root / name / "summary.json").resolve()
        try:
            path.relative_to(exports_root)
        except ValueError:
            return JsonResponse({"error": "invalid path"}, status=400)
        if not path.exists():
            return JsonResponse({"error": "not found"}, status=404)
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return JsonResponse({"error": "unreadable"}, status=500)
        return JsonResponse(data)

    def delete(self, request: HttpRequest, name: str) -> JsonResponse:
        if not re.match(r"^[\w\-]+$", name):
            return JsonResponse({"error": "invalid name"}, status=400)
        exports_root = (Path(settings.BASE_DIR) / "exports").resolve()
        path = (exports_root / name).resolve()
        try:
            path.relative_to(exports_root)
        except ValueError:
            return JsonResponse({"error": "invalid path"}, status=400)
        if not path.is_dir():
            return JsonResponse({"error": "not found"}, status=404)
        if not (path / "summary.json").exists():
            return JsonResponse({"error": "not a valid export directory"}, status=400)
        shutil.rmtree(path)
        return JsonResponse({"deleted": name})


# ── Per-task arg specs ────────────────────────────────────────────────────────
# Each spec is a tuple starting with a kind keyword that names the translation
# from POST data to a CLI argument. Adding a flag is a one-line table edit.
#
#   ("flag",          post_key, cli_flag)              "if post.get(key): args += [cli_flag]"
#   ("inverted_flag", post_key, cli_flag)              "if not post.get(key): args += [cli_flag]"
#   ("value",         post_key, cli_flag)              ".strip()-d value; skipped when empty"
#   ("csv",           post_key, cli_flag)              "post.getlist(key) joined by ','"
#   ("csv_unique",    post_key, cli_flag)              "csv with order-preserving dedupe"
#   ("const",         post_key, cli_flag, const_value) "fixed second arg when post[key] is truthy"
#   ("channel_types", cli_flag)                        "CHANNEL/GROUP/USER triplet → csv"
#   ("extra_terms",   post_key)                        "one --extra-term per non-blank line"
#   ("positional",    post_key)                        "a bare argument (no flag) when set"

_CHANNEL_TYPE_KEYS = ("CHANNEL", "GROUP", "USER")


def _apply_spec(spec: tuple, post: Any, args: list[str]) -> None:
    kind = spec[0]
    if kind == "flag":
        _, key, flag = spec
        if post.get(key):
            args.append(flag)
    elif kind == "inverted_flag":
        _, key, flag = spec
        if not post.get(key):
            args.append(flag)
    elif kind == "value":
        _, key, flag = spec
        val = post.get(key, "").strip()
        if val:
            args += [flag, val]
    elif kind == "csv":
        _, key, flag = spec
        val = ",".join(post.getlist(key))
        if val:
            args += [flag, val]
    elif kind == "csv_unique":
        _, key, flag = spec
        val = ",".join(dict.fromkeys(post.getlist(key)))
        if val:
            args += [flag, val]
    elif kind == "const":
        _, key, flag, const_value = spec
        if post.get(key):
            args += [flag, const_value]
    elif kind == "channel_types":
        _, flag = spec
        types = [ct for ct in _CHANNEL_TYPE_KEYS if post.get(f"channel_type_{ct.lower()}")]
        if types:
            args += [flag, ",".join(types)]
    elif kind == "extra_terms":
        _, key = spec
        for line in post.get(key, "").splitlines():
            word = " ".join(line.split()).lower()
            if word:
                args += ["--extra-term", word]
    elif kind == "positional":
        _, key = spec
        val = post.get(key, "").strip()
        if val:
            args.append(val)
    else:
        raise ValueError(f"Unknown arg-spec kind: {kind!r}")


TASK_ARG_SPECS: dict[str, list[tuple]] = {
    "crawl_channels": [
        # Channels
        ("flag", "get_channels_info", "--get-channels-info"),
        ("flag", "mine_about_texts", "--mine-about-texts"),
        ("flag", "fetch_recommended_channels", "--fetch-recommended-channels"),
        ("flag", "retry_lost_and_private", "--retry-lost-and-private"),
        # Messages
        ("flag", "get_new_messages", "--get-new-messages"),
        ("flag", "fetch_replies", "--fetch-replies"),
        ("flag", "do_refresh", "--refresh-messages-stats"),
        ("value", "refresh_limit", "--refresh-limit"),
        ("value", "refresh_from", "--refresh-from"),
        ("value", "refresh_to", "--refresh-to"),
        ("flag", "fix_holes", "--fixholes"),
        ("flag", "fix_missing_media", "--fix-missing-media"),
        ("flag", "retry_lost_messages", "--retry-lost-messages"),
        ("flag", "retry_references", "--retry-references"),
        ("flag", "force_retry_unresolved_references", "--force-retry-unresolved-references"),
        # Degrees
        ("flag", "in_degrees", "--in-degrees"),
        ("flag", "out_degrees", "--out-degrees"),
        # Scope
        ("value", "ids", "--ids"),
        ("channel_types", "--channel-types"),
        ("csv", "channel_groups", "--channel-groups"),
    ],
    "search_channels": [
        ("value", "amount", "--amount"),
        ("extra_terms", "extra_terms"),
    ],
    "structural_analysis": [
        ("value", "export_name", "--name"),
        ("flag", "graph_3d", "--3dgraph"),
        ("flag", "xlsx", "--xlsx"),
        ("flag", "gexf", "--gexf"),
        ("flag", "graphml", "--graphml"),
        ("flag", "csv", "--csv"),
        ("flag", "seo", "--seo"),
        ("flag", "graph", "--2dgraph"),
        ("flag", "html", "--html"),
        ("flag", "vertical_layout", "--vertical-layout"),
        ("csv_unique", "layouts_2d", "--2dlayouts"),
        ("csv_unique", "layouts_3d", "--3dlayouts"),
        ("value", "fa2_iterations", "--fa2-iterations"),
        ("value", "startdate", "--startdate"),
        ("value", "enddate", "--enddate"),
        ("flag", "draw_dead_leaves", "--draw-dead-leaves"),
        ("csv", "measures", "--measures"),
        ("csv", "community_strategies", "--community-strategies"),
        ("csv", "network_stat_groups", "--network-stat-groups"),
        ("inverted_flag", "include_mentions", "--no-mentions"),
        ("flag", "include_self_references", "--self-references"),
        ("value", "edge_weight_strategy", "--edge-weight-strategy"),
        ("value", "recency_weights", "--recency-weights"),
        ("value", "spreading_runs", "--spreading-runs"),
        ("value", "diffusion_window", "--diffusion-window"),
        ("flag", "consensus_matrix", "--consensus-matrix"),
        ("flag", "structural_similarity", "--structural-similarity"),
        ("value", "community_distribution_threshold", "--community-distribution-threshold"),
        ("value", "leiden_coarse_resolution", "--leiden-coarse-resolution"),
        ("value", "leiden_fine_resolution", "--leiden-fine-resolution"),
        ("value", "mcl_inflation", "--mcl-inflation"),
        ("channel_types", "--channel-types"),
        ("csv", "channel_groups", "--channel-groups"),
        ("flag", "include_lost", "--include-lost"),
        ("flag", "include_private", "--include-private"),
        ("const", "timeline_step", "--timeline-step", "year"),
        ("csv", "vacancy_measures", "--vacancy-measures"),
        ("value", "vacancy_months_before", "--vacancy-months-before"),
        ("value", "vacancy_months_after", "--vacancy-months-after"),
        ("value", "vacancy_max_candidates", "--vacancy-max-candidates"),
        ("value", "vacancy_ppr_alpha", "--vacancy-ppr-alpha"),
    ],
    "compare_analysis": [
        ("positional", "project_dir"),
        ("value", "compare_target", "--target"),
        ("flag", "seo", "--seo"),
    ],
}


def _build_args(task: str, post: Any) -> list[str]:
    args: list[str] = []
    for spec in TASK_ARG_SPECS.get(task, []):
        _apply_spec(spec, post, args)
    return args
