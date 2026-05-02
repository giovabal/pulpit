import json
import re
import shutil
from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

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
        "description": "Crawl all interesting channels and resolve cross-channel references.",
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
        channel_groups = list(ChannelGroup.objects.values_list("name", flat=True))
        has_vacancies = ChannelVacancy.objects.exists()
        return render(
            request,
            "runner/operations.html",
            {
                "tasks": task_info,
                "default_channel_types": set(settings.DEFAULT_CHANNEL_TYPES),
                "channel_groups": channel_groups,
                "has_vacancies": has_vacancies,
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
        offset = int(request.GET.get("offset", 0))
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
        path = Path(settings.BASE_DIR) / "exports" / name / "summary.json"
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


def _build_args(task: str, post: Any) -> list[str]:
    args: list[str] = []

    if task == "crawl_channels":
        if post.get("get_new_messages"):
            args.append("--get-new-messages")
        if post.get("fix_holes"):
            args.append("--fixholes")
        if post.get("fetch_recommended_channels"):
            args.append("--fetch-recommended-channels")
        if post.get("retry_references"):
            args.append("--retry-references")
        if post.get("force_retry_unresolved_references"):
            args.append("--force-retry-unresolved-references")
        if post.get("mine_about_texts"):
            args.append("--mine-about-texts")
        if post.get("refresh_degrees"):
            args.append("--refresh-degrees")
        if post.get("fix_missing_media"):
            args.append("--fix-missing-media")
        if post.get("do_refresh"):
            args.append("--refresh-messages-stats")
            val = post.get("refresh_value", "").strip()
            if val:
                args.append(val)
        ids = post.get("ids", "").strip()
        if ids:
            args += ["--ids", ids]
        channel_types = [ct for ct in ["CHANNEL", "GROUP", "USER"] if post.get(f"channel_type_{ct.lower()}")]
        if channel_types:
            args += ["--channel-types", ",".join(channel_types)]
        channel_groups = post.getlist("channel_groups")
        if channel_groups:
            args += ["--channel-groups", ",".join(channel_groups)]

    elif task == "search_channels":
        amount = post.get("amount", "").strip()
        if amount:
            args += ["--amount", amount]
        for line in post.get("extra_terms", "").splitlines():
            word = " ".join(line.split()).lower()
            if word:
                args += ["--extra-term", word]

    elif task == "structural_analysis":
        name_val = post.get("export_name", "").strip()
        if name_val:
            args += ["--name", name_val]
        if post.get("graph_3d"):
            args.append("--3dgraph")
        if post.get("xlsx"):
            args.append("--xlsx")
        if post.get("gexf"):
            args.append("--gexf")
        if post.get("graphml"):
            args.append("--graphml")
        if post.get("seo"):
            args.append("--seo")
        if post.get("graph"):
            args.append("--2dgraph")
        if post.get("html"):
            args.append("--html")
        if post.get("vertical_layout"):
            args.append("--vertical-layout")
        fa2 = post.get("fa2_iterations", "").strip()
        if fa2:
            args += ["--fa2-iterations", fa2]
        startdate = post.get("startdate", "").strip()
        if startdate:
            args += ["--startdate", startdate]
        enddate = post.get("enddate", "").strip()
        if enddate:
            args += ["--enddate", enddate]
        if post.get("draw_dead_leaves"):
            args.append("--draw-dead-leaves")
        measures_val = ",".join(post.getlist("measures"))
        if measures_val:
            args += ["--measures", measures_val]
        community_strategies_val = ",".join(post.getlist("community_strategies"))
        if community_strategies_val:
            args += ["--community-strategies", community_strategies_val]
        network_stat_groups_val = ",".join(post.getlist("network_stat_groups"))
        if network_stat_groups_val:
            args += ["--network-stat-groups", network_stat_groups_val]
        if not post.get("include_mentions"):
            args.append("--no-mentions")
        edge_weight_strategy_val = post.get("edge_weight_strategy", "").strip()
        if edge_weight_strategy_val:
            args += ["--edge-weight-strategy", edge_weight_strategy_val]
        recency_weights_val = post.get("recency_weights", "").strip()
        if recency_weights_val:
            args += ["--recency-weights", recency_weights_val]
        spreading_runs_val = post.get("spreading_runs", "").strip()
        if spreading_runs_val:
            args += ["--spreading-runs", spreading_runs_val]
        if post.get("consensus_matrix"):
            args.append("--consensus-matrix")
        community_distribution_threshold_val = post.get("community_distribution_threshold", "").strip()
        if community_distribution_threshold_val:
            args += ["--community-distribution-threshold", community_distribution_threshold_val]
        leiden_coarse_resolution_val = post.get("leiden_coarse_resolution", "").strip()
        if leiden_coarse_resolution_val:
            args += ["--leiden-coarse-resolution", leiden_coarse_resolution_val]
        leiden_fine_resolution_val = post.get("leiden_fine_resolution", "").strip()
        if leiden_fine_resolution_val:
            args += ["--leiden-fine-resolution", leiden_fine_resolution_val]
        mcl_inflation_val = post.get("mcl_inflation", "").strip()
        if mcl_inflation_val:
            args += ["--mcl-inflation", mcl_inflation_val]
        channel_types = [ct for ct in ["CHANNEL", "GROUP", "USER"] if post.get(f"channel_type_{ct.lower()}")]
        if channel_types:
            args += ["--channel-types", ",".join(channel_types)]
        channel_groups = post.getlist("channel_groups")
        if channel_groups:
            args += ["--channel-groups", ",".join(channel_groups)]
        if post.get("timeline_step"):
            args += ["--timeline-step", "year"]
        if not post.get("vacancy_only_after"):
            args.append("--no-vacancy-only-after")
        vacancy_measures_val = ",".join(post.getlist("vacancy_measures"))
        if vacancy_measures_val:
            args += ["--vacancy-measures", vacancy_measures_val]
        vacancy_months_before_val = post.get("vacancy_months_before", "").strip()
        if vacancy_months_before_val:
            args += ["--vacancy-months-before", vacancy_months_before_val]
        vacancy_months_after_val = post.get("vacancy_months_after", "").strip()
        if vacancy_months_after_val:
            args += ["--vacancy-months-after", vacancy_months_after_val]
        vacancy_max_candidates_val = post.get("vacancy_max_candidates", "").strip()
        if vacancy_max_candidates_val:
            args += ["--vacancy-max-candidates", vacancy_max_candidates_val]
        vacancy_ppr_alpha_val = post.get("vacancy_ppr_alpha", "").strip()
        if vacancy_ppr_alpha_val:
            args += ["--vacancy-ppr-alpha", vacancy_ppr_alpha_val]

    elif task == "compare_analysis":
        project_dir = post.get("project_dir", "").strip()
        if project_dir:
            args.append(project_dir)
        target_val = post.get("compare_target", "").strip()
        if target_val:
            args += ["--target", target_val]
        if post.get("seo"):
            args.append("--seo")

    return args
