from typing import Any

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
}


class OpsView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        task_info = []
        for name, defn in TASK_DEFINITIONS.items():
            status = tasks.get_status(name)
            task_info.append({**defn, "name": name, **status})
        return render(request, "runner/ops.html", {"tasks": task_info})


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
        if post.get("fixholes"):
            args.append("--fixholes")
        if post.get("do_refresh"):
            args.append("--refresh-messages-stats")
            val = post.get("refresh_value", "").strip()
            if val:
                args.append(val)
        fromid = post.get("fromid", "").strip()
        if fromid:
            args += ["--fromid", fromid]

    elif task == "search_channels":
        amount = post.get("amount", "").strip()
        if amount:
            args += ["--amount", amount]

    elif task == "export_network":
        if post.get("graph_3d"):
            args.append("--3d")
        if post.get("xlsx"):
            args.append("--xlsx")
        if post.get("gexf"):
            args.append("--gexf")
        if post.get("seo"):
            args.append("--seo")
        if post.get("no_graph"):
            args.append("--no-graph")
        if post.get("no_html"):
            args.append("--no-html")
        startdate = post.get("startdate", "").strip()
        if startdate:
            args += ["--startdate", startdate]
        enddate = post.get("enddate", "").strip()
        if enddate:
            args += ["--enddate", enddate]
        compare = post.get("compare", "").strip()
        if compare:
            args += ["--compare", compare]

    return args
