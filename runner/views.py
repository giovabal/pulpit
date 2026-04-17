from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

from runner import tasks

TASK_DEFINITIONS: dict[str, dict[str, str]] = {
    "get_channels": {
        "title": "Get Channels",
        "description": "Crawl all interesting channels and resolve cross-channel references.",
        "icon": "bi-cloud-download",
    },
    "search_channels": {
        "title": "Search Channels",
        "description": "Search Telegram for channels matching each SearchTerm in the database.",
        "icon": "bi-search",
    },
    "export_network": {
        "title": "Export Network",
        "description": "Build the graph, compute measures, detect communities, and write output files.",
        "icon": "bi-diagram-3",
    },
    "compare_networks": {
        "title": "Compare Networks",
        "description": "Copy a previously exported network and generate side-by-side comparison tables and scatter plots.",
        "icon": "bi-intersect",
    },
}


class OperationsView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        task_info = []
        for name, defn in TASK_DEFINITIONS.items():
            status = tasks.get_status(name)
            task_info.append({**defn, "name": name, **status})
        return render(
            request,
            "runner/operations.html",
            {"tasks": task_info, "default_channel_types": set(settings.DEFAULT_CHANNEL_TYPES)},
        )


class RunTaskView(View):
    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        if tasks.get_status(task)["status"] == "running":
            return JsonResponse({"error": "Task already running"}, status=409)
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


class TaskStatusView(View):
    def get(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        offset = int(request.GET.get("offset", 0))
        status = tasks.get_status(task)
        lines, new_offset = tasks.get_log_lines(task, offset)
        return JsonResponse({**status, "lines": lines, "next_offset": new_offset})


def _build_args(task: str, post: Any) -> list[str]:
    args: list[str] = []

    if task == "get_channels":
        if post.get("get_new_messages"):
            args.append("--get-new-messages")
        if post.get("fixholes"):
            args.append("--fixholes")
        if post.get("fetch_recommended_channels"):
            args.append("--fetch-recommended-channels")
        if post.get("force_retry_unresolved_references"):
            args.append("--force-retry-unresolved-references")
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

    elif task == "search_channels":
        amount = post.get("amount", "").strip()
        if amount:
            args += ["--amount", amount]

    elif task == "export_network":
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
        channel_types = [ct for ct in ["CHANNEL", "GROUP", "USER"] if post.get(f"channel_type_{ct.lower()}")]
        if channel_types:
            args += ["--channel-types", ",".join(channel_types)]

    elif task == "compare_networks":
        project_dir = post.get("project_dir", "").strip()
        if project_dir:
            args.append(project_dir)
        if post.get("seo"):
            args.append("--seo")

    return args
