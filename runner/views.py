import json
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

from network import (
    community as net_community,
    measures as net_measures,
    robustness as net_robustness,
    vacancy_analysis,
)
from runner import tasks
from webapp.models import ChannelGroup, ChannelVacancy, SearchTerm
from webapp.utils import colors as palette_utils
from webapp_engine.config import (
    CRAWL_DEFAULTS,
    STRUCTURAL_DEFAULTS,
    list_defaults,
    load_payload_by_id,
    save_named,
)

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
            "CRAWL_UPDATE_TYPE_EXCLUDED_INFO": settings.CRAWL_UPDATE_TYPE_EXCLUDED_INFO,
            "CRAWL_MINE_ABOUT_TEXTS": settings.CRAWL_MINE_ABOUT_TEXTS,
            "CRAWL_FETCH_RECOMMENDED": settings.CRAWL_FETCH_RECOMMENDED,
            "CRAWL_RETRY_LOST_AND_PRIVATE": settings.CRAWL_RETRY_LOST_AND_PRIVATE,
            "CRAWL_GET_NEW_MESSAGES": settings.CRAWL_GET_NEW_MESSAGES,
            "CRAWL_FETCH_REPLIES": settings.CRAWL_FETCH_REPLIES,
            "CRAWL_REFRESH_MESSAGES_STATS": settings.CRAWL_REFRESH_MESSAGES_STATS,
            "CRAWL_FIX_HOLES": settings.CRAWL_FIX_HOLES,
            "CRAWL_FIX_MISSING_MEDIA": settings.CRAWL_FIX_MISSING_MEDIA,
            "CRAWL_RETRY_LOST_MESSAGES": settings.CRAWL_RETRY_LOST_MESSAGES,
            "CRAWL_RETRY_REFERENCES": settings.CRAWL_RETRY_REFERENCES,
            "CRAWL_FORCE_RETRY_UNRESOLVED_REFERENCES": settings.CRAWL_FORCE_RETRY_UNRESOLVED_REFERENCES,
            "CRAWL_DOWNLOAD_IMAGES": settings.TELEGRAM_CRAWLER_DOWNLOAD_IMAGES,
            "CRAWL_DOWNLOAD_VIDEO": settings.TELEGRAM_CRAWLER_DOWNLOAD_VIDEO,
            "CRAWL_DOWNLOAD_AUDIO": settings.TELEGRAM_CRAWLER_DOWNLOAD_AUDIO,
            "CRAWL_DOWNLOAD_STICKERS": settings.TELEGRAM_CRAWLER_DOWNLOAD_STICKERS,
            "CRAWL_DOWNLOAD_OTHER_MEDIA": settings.TELEGRAM_CRAWLER_DOWNLOAD_OTHER_MEDIA,
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
            "SA_DEAD_LEAVES_COLOR": settings.DEAD_LEAVES_COLOR,
            "SA_COMMUNITY_PALETTE": settings.COMMUNITY_PALETTE,
            "SA_COMMUNITY_PALETTE_REVERSED": settings.COMMUNITY_PALETTE_REVERSED,
            "SA_BRIDGING_BASIS": settings.SA_BRIDGING_BASIS,
            "SA_STRUCTURAL_SIMILARITY": settings.SA_STRUCTURAL_SIMILARITY,
            "SA_BEHAVIOURAL_EQUIVALENCE": settings.SA_BEHAVIOURAL_EQUIVALENCE,
            "SA_CONSENSUS_MATRIX": settings.SA_CONSENSUS_MATRIX,
            "SA_INTEREST_STRUCTURAL": settings.SA_INTEREST_STRUCTURAL,
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
            "SA_VACANCY_MONTHS_BEFORE": settings.SA_VACANCY_MONTHS_BEFORE,
            "SA_VACANCY_MONTHS_AFTER": settings.SA_VACANCY_MONTHS_AFTER,
            "SA_VACANCY_MAX_CANDIDATES": settings.SA_VACANCY_MAX_CANDIDATES,
            # SA robustness params
            "SA_ROBUSTNESS": settings.SA_ROBUSTNESS,
            "SA_ROBUSTNESS_ALPHA": settings.SA_ROBUSTNESS_ALPHA,
            "SA_ROBUSTNESS_RUNS": settings.SA_ROBUSTNESS_RUNS,
            "SA_ROBUSTNESS_NULL": settings.SA_ROBUSTNESS_NULL,
            "SA_ROBUSTNESS_SEED": settings.SA_ROBUSTNESS_SEED,
            "SA_ROBUSTNESS_SAMPLE": settings.SA_ROBUSTNESS_SAMPLE,
            # SA interest (per-message structural reach)
            "SA_INTEREST_WINDOW_DAYS": settings.SA_INTEREST_WINDOW_DAYS,
            "SA_INTEREST_INCLUDE_MENTIONS": settings.SA_INTEREST_INCLUDE_MENTIONS,
            # SA string params
            "SA_EDGE_WEIGHT_STRATEGY": settings.SA_EDGE_WEIGHT_STRATEGY,
            # SA expanded sets for checkbox groups
            "sa_measures": _expand(settings.SA_MEASURES, set(net_measures.VALID_MEASURES)),
            "sa_strategies": _expand(settings.SA_COMMUNITY_STRATEGIES, set(net_community.VALID_STRATEGIES)),
            "sa_stat_groups": _expand(settings.SA_NETWORK_STAT_GROUPS, set(net_measures.ALL_NETWORK_STAT_GROUPS)),
            "sa_layouts_2d": {s.strip().upper() for s in settings.SA_LAYOUTS_2D.split(",") if s.strip()},
            "sa_layouts_3d": {s.strip().upper() for s in settings.SA_LAYOUTS_3D.split(",") if s.strip()},
            "sa_vacancy_measures": _expand(settings.SA_VACANCY_MEASURES, set(vacancy_analysis.ALL_VACANCY_MEASURES)),
            "sa_robustness_strategies": _expand(
                settings.SA_ROBUSTNESS_STRATEGIES, {s.upper() for s in net_robustness.ALL_STRATEGIES}
            ),
        }

        return render(
            request,
            "runner/operations.html",
            {
                "tasks": task_info,
                "default_channel_types": set(settings.DEFAULT_CHANNEL_TYPES),
                "channel_groups": channel_groups,
                "has_vacancies": has_vacancies,
                # (key, label) pairs for the bridging-basis dropdown.  ORGANIZATION is excluded
                # because organisation membership isn't a community-detection result —
                # entropy across pre-declared categories doesn't carry the same meaning.
                "bridging_basis_choices": sorted(
                    (
                        (key, net_community.COMMUNITY_STRATEGY_LABELS.get(key, key))
                        for key in net_community.VALID_STRATEGIES
                        if key != "ORGANIZATION"
                    ),
                    key=lambda kv: kv[1],
                ),
                "palette_names": palette_utils.list_palette_names(),
                "ad": ad,
            },
        )


class RunTaskView(View):
    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        if tasks.get_status(task)["status"] == "running":
            return JsonResponse({"error": "Task already running"}, status=409)
        try:
            _validate_post_constraints(task, request.POST)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        args = _build_args(task, request.POST)
        # Persist any new search terms only after validation passes; otherwise a
        # 400 leaves the DB written despite the user-visible failure.
        if task == "search_channels" and request.POST.get("save_terms"):
            extra_raw = request.POST.get("extra_terms", "")
            for line in extra_raw.splitlines():
                word = " ".join(line.split()).lower()
                if word:
                    SearchTerm.objects.get_or_create(word=word)
        try:
            tasks.launch(task, args)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        return JsonResponse({"status": "started", "args": args})


class WriteCliCommandView(View):
    """Produce the `python manage.py <task> --flag ...` line for the current form.

    Reuses `_validate_post_constraints` + `_build_args` so the displayed
    command is exactly what the Run endpoint would launch. Validation
    errors return 400 with the same message as Save/Run.
    """

    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFINITIONS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        try:
            _validate_post_constraints(task, request.POST)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        args = _build_args(task, request.POST)
        # shlex.quote each arg so multi-word values (e.g. search_channels
        # --extra-term "hello world") remain executable when copy-pasted.
        command_parts = ["python", "manage.py", task] + [shlex.quote(a) for a in args]
        command = " ".join(command_parts)
        return JsonResponse({"command": command, "args": args})


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
#   ("value",         post_key, cli_flag)              ".strip()-d value; skipped when empty"
#   ("csv",           post_key, cli_flag)              "post.getlist(key) joined by ','"
#   ("csv_unique",    post_key, cli_flag)              "csv with order-preserving dedupe"
#   ("const",         post_key, cli_flag, const_value) "fixed second arg when post[key] is truthy"
#   ("bool_explicit", post_key, on_flag, off_flag)     "always emit on/off form (tri-state CLI)"
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
    elif kind == "bool_explicit":
        _, key, on_flag, off_flag = spec
        args.append(on_flag if post.get(key) else off_flag)
    elif kind == "channel_types":
        _, flag = spec
        types = [ct for ct in _CHANNEL_TYPE_KEYS if post.get(f"channel_type_{ct.lower()}")]
        if types:
            args += [flag, ",".join(types)]
    elif kind == "measures_with_bridging":
        # Like a normal csv kind, but the BRIDGING entry gets its community basis
        # appended in parenthesised form when the shared bridging-basis dropdown
        # picks a non-default value.  Bare BRIDGING falls through to the backend
        # default (LEIDEN_DIRECTED).
        _, flag = spec
        chosen = post.getlist("measures")
        bridging_basis = (post.get("bridging_basis") or "").strip().upper()
        tokens: list[str] = []
        for m in chosen:
            if m == "BRIDGING" and bridging_basis:
                tokens.append(f"BRIDGING({bridging_basis})")
            else:
                tokens.append(m)
        if tokens:
            args += [flag, ",".join(tokens)]
    elif kind == "robustness_strategies":
        # Multi-select checkboxes; the "bridging" entry gets its community basis
        # appended in parenthesised form when the shared bridging-basis dropdown
        # picks a non-default value (the field is shared with the BRIDGING measure
        # — see measures_with_bridging above).  Bare bridging falls through to the
        # backend default (leiden_directed).
        #
        # The strategy list doubles as the master switch: at least one strategy
        # checked ⇒ pass --robustness, none checked ⇒ pass --no-robustness
        # (BooleanOptionalAction). The .operations-structural file has no separate
        # `enabled` key — SA_ROBUSTNESS is derived from bool(strategies) in settings.
        _, flag = spec
        chosen = post.getlist("robustness_strategies")
        bridging_basis = (post.get("bridging_basis") or "").strip().lower()
        tokens: list[str] = []
        for s in chosen:
            if s == "bridging" and bridging_basis:
                tokens.append(f"bridging({bridging_basis})")
            else:
                tokens.append(s)
        if tokens:
            args += ["--robustness", flag, ",".join(tokens)]
        else:
            args.append("--no-robustness")
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
        # Channels — every toggle uses bool_explicit so an unchecked Operations
        # panel checkbox sends --no-<flag>, which overrides any configuration
        # default that would otherwise re-enable the operation.
        ("bool_explicit", "get_channels_info", "--get-channels-info", "--no-get-channels-info"),
        (
            "bool_explicit",
            "update_type_excluded_info",
            "--update-type-excluded-info",
            "--no-update-type-excluded-info",
        ),
        ("bool_explicit", "mine_about_texts", "--mine-about-texts", "--no-mine-about-texts"),
        ("bool_explicit", "fetch_recommended", "--fetch-recommended", "--no-fetch-recommended"),
        ("bool_explicit", "retry_lost_and_private", "--retry-lost-and-private", "--no-retry-lost-and-private"),
        # Messages
        ("bool_explicit", "get_new_messages", "--get-new-messages", "--no-get-new-messages"),
        ("bool_explicit", "fetch_replies", "--fetch-replies", "--no-fetch-replies"),
        (
            "bool_explicit",
            "refresh_messages_stats",
            "--refresh-messages-stats",
            "--no-refresh-messages-stats",
        ),
        ("value", "refresh_limit", "--refresh-limit"),
        ("value", "refresh_from", "--refresh-from"),
        ("value", "refresh_to", "--refresh-to"),
        ("bool_explicit", "fix_holes", "--fix-holes", "--no-fix-holes"),
        ("bool_explicit", "fix_missing_media", "--fix-missing-media", "--no-fix-missing-media"),
        ("bool_explicit", "retry_lost_messages", "--retry-lost-messages", "--no-retry-lost-messages"),
        ("bool_explicit", "retry_references", "--retry-references", "--no-retry-references"),
        (
            "bool_explicit",
            "force_retry_unresolved_references",
            "--force-retry-unresolved-references",
            "--no-force-retry-unresolved-references",
        ),
        # Media types
        ("bool_explicit", "download_images", "--download-images", "--no-download-images"),
        ("bool_explicit", "download_video", "--download-video", "--no-download-video"),
        ("bool_explicit", "download_audio", "--download-audio", "--no-download-audio"),
        ("bool_explicit", "download_stickers", "--download-stickers", "--no-download-stickers"),
        ("bool_explicit", "download_other_media", "--download-other-media", "--no-download-other-media"),
        # Degrees
        ("bool_explicit", "in_degrees", "--in-degrees", "--no-in-degrees"),
        ("bool_explicit", "out_degrees", "--out-degrees", "--no-out-degrees"),
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
        # Output toggles: bool_explicit (paired with BooleanOptionalAction in argparse)
        # so unchecking the box in the panel emits --no-X and beats the saved-true
        # default. Same fix as commit 5737cac applied to the crawl side.
        ("bool_explicit", "graph", "--graph-2d", "--no-graph-2d"),
        ("bool_explicit", "graph_3d", "--graph-3d", "--no-graph-3d"),
        ("bool_explicit", "html", "--html", "--no-html"),
        ("bool_explicit", "xlsx", "--xlsx", "--no-xlsx"),
        ("bool_explicit", "gexf", "--gexf", "--no-gexf"),
        ("bool_explicit", "graphml", "--graphml", "--no-graphml"),
        ("bool_explicit", "csv", "--csv", "--no-csv"),
        ("bool_explicit", "seo", "--seo", "--no-seo"),
        ("bool_explicit", "vertical_layout", "--vertical-layout", "--no-vertical-layout"),
        ("csv_unique", "layouts_2d", "--layouts-2d"),
        ("csv_unique", "layouts_3d", "--layouts-3d"),
        ("value", "fa2_iterations", "--fa2-iterations"),
        ("value", "startdate", "--startdate"),
        ("value", "enddate", "--enddate"),
        ("bool_explicit", "draw_dead_leaves", "--draw-dead-leaves", "--no-draw-dead-leaves"),
        ("value", "dead_leaves_color", "--dead-leaves-color"),
        ("value", "community_palette", "--community-palette"),
        (
            "bool_explicit",
            "community_palette_reversed",
            "--community-palette-reversed",
            "--no-community-palette-reversed",
        ),
        ("measures_with_bridging", "--measures"),
        ("csv", "community_strategies", "--community-strategies"),
        ("csv", "network_stat_groups", "--network-stat-groups"),
        ("bool_explicit", "include_mentions", "--mentions", "--no-mentions"),
        ("bool_explicit", "include_self_references", "--self-references", "--no-self-references"),
        ("value", "edge_weight_strategy", "--edge-weight-strategy"),
        ("value", "spreading_runs", "--spreading-runs"),
        ("value", "diffusion_window", "--diffusion-window"),
        ("bool_explicit", "consensus_matrix", "--consensus-matrix", "--no-consensus-matrix"),
        ("bool_explicit", "structural_similarity", "--structural-similarity", "--no-structural-similarity"),
        ("bool_explicit", "behavioural_equivalence", "--behavioural-equivalence", "--no-behavioural-equivalence"),
        ("bool_explicit", "interest_structural", "--interest-structural", "--no-interest-structural"),
        ("value", "interest_window_days", "--interest-window-days"),
        (
            "bool_explicit",
            "interest_include_mentions",
            "--interest-include-mentions",
            "--no-interest-include-mentions",
        ),
        ("value", "community_distribution_threshold", "--community-distribution-threshold"),
        ("value", "leiden_coarse_resolution", "--leiden-coarse-resolution"),
        ("value", "leiden_fine_resolution", "--leiden-fine-resolution"),
        ("value", "mcl_inflation", "--mcl-inflation"),
        ("channel_types", "--channel-types"),
        ("csv", "channel_groups", "--channel-groups"),
        ("bool_explicit", "include_lost", "--include-lost", "--no-include-lost"),
        ("bool_explicit", "include_private", "--include-private", "--no-include-private"),
        ("const", "timeline_step", "--timeline-step", "year"),
        ("csv", "vacancy_measures", "--vacancy-measures"),
        ("value", "vacancy_months_before", "--vacancy-months-before"),
        ("value", "vacancy_months_after", "--vacancy-months-after"),
        ("value", "vacancy_max_candidates", "--vacancy-max-candidates"),
        ("value", "robustness_alpha", "--robustness-alpha"),
        ("robustness_strategies", "--robustness-strategies"),
        ("value", "robustness_runs", "--robustness-runs"),
        ("value", "robustness_null", "--robustness-null"),
        ("value", "robustness_seed", "--robustness-seed"),
        ("value", "robustness_sample", "--robustness-sample"),
    ],
    "compare_analysis": [
        ("positional", "project_dir"),
        ("value", "compare_target", "--target"),
        ("bool_explicit", "seo", "--seo", "--no-seo"),
    ],
}


def _build_args(task: str, post: Any) -> list[str]:
    args: list[str] = []
    for spec in TASK_ARG_SPECS.get(task, []):
        _apply_spec(spec, post, args)
    return args


# ── Save-as-defaults specs ────────────────────────────────────────────────────
# Translate Operations-panel form fields into nested paths inside
# .operations-crawl / .operations-structural. Each entry is
# (post_key | (key1, key2, …), "section.field", kind).
#
# kinds:
#   "bool"                     post.get(key) truthy → True else False
#   "list"                     post.getlist(key) verbatim
#   "value"                    post.get(key, "").strip()
#   "value_optional"           same as value, empty string preserved
#   "int" / "float"            cast; empty → fall back to defaults.py value
#   "bool_to_enum:<off>,<on>"  checkbox → on-string or off-string
#   "channel_types_triplet"    three checkboxes (CHANNEL/GROUP/USER) → list

TASK_DEFAULT_SPECS: dict[str, list[tuple]] = {
    "crawl_channels": [
        ("get_channels_info", "channels.get_channels_info", "bool"),
        ("update_type_excluded_info", "channels.update_type_excluded_info", "bool"),
        ("mine_about_texts", "channels.mine_about_texts", "bool"),
        ("fetch_recommended", "channels.fetch_recommended", "bool"),
        ("retry_lost_and_private", "channels.retry_lost_and_private", "bool"),
        ("get_new_messages", "messages.get_new_messages", "bool"),
        ("fetch_replies", "messages.fetch_replies", "bool"),
        ("refresh_messages_stats", "messages.refresh_messages_stats", "bool"),
        ("fix_holes", "messages.fix_holes", "bool"),
        ("fix_missing_media", "messages.fix_missing_media", "bool"),
        ("retry_lost_messages", "messages.retry_lost_messages", "bool"),
        ("retry_references", "messages.retry_references", "bool"),
        ("force_retry_unresolved_references", "messages.force_retry_unresolved_references", "bool"),
        ("in_degrees", "degrees.in_degrees", "bool"),
        ("out_degrees", "degrees.out_degrees", "bool"),
        ("download_images", "downloads.images", "bool"),
        ("download_video", "downloads.video", "bool"),
        ("download_audio", "downloads.audio", "bool"),
        ("download_stickers", "downloads.stickers", "bool"),
        ("download_other_media", "downloads.other_media", "bool"),
        (
            ("channel_type_channel", "channel_type_group", "channel_type_user"),
            "scope.channel_types",
            "channel_types_triplet",
        ),
    ],
    "structural_analysis": [
        ("graph", "outputs.graph", "bool"),
        ("graph_3d", "outputs.graph_3d", "bool"),
        ("html", "outputs.html", "bool"),
        ("xlsx", "outputs.xlsx", "bool"),
        ("gexf", "outputs.gexf", "bool"),
        ("graphml", "outputs.graphml", "bool"),
        ("csv", "outputs.csv", "bool"),
        ("seo", "outputs.seo", "bool"),
        ("vertical_layout", "outputs.vertical_layout", "bool"),
        ("structural_similarity", "outputs.structural_similarity", "bool"),
        ("behavioural_equivalence", "outputs.behavioural_equivalence", "bool"),
        ("consensus_matrix", "outputs.consensus_matrix", "bool"),
        ("draw_dead_leaves", "outputs.draw_dead_leaves", "bool"),
        ("dead_leaves_color", "graph.dead_leaves_color", "value"),
        ("community_palette", "graph.community_palette", "palette_name"),
        ("community_palette_reversed", "graph.community_palette_reversed", "bool"),
        ("timeline_step", "outputs.timeline_step", "bool_to_enum:none,year"),
        ("edge_weight_strategy", "edges.weight_strategy", "value"),
        ("include_mentions", "edges.include_mentions", "bool"),
        ("include_self_references", "edges.include_self_references", "bool"),
        ("include_lost", "scope.include_lost", "bool"),
        ("include_private", "scope.include_private", "bool"),
        ("fa2_iterations", "computation.fa2_iterations", "fa2_iterations"),
        ("community_distribution_threshold", "computation.community_distribution_threshold", "int"),
        ("leiden_coarse_resolution", "computation.leiden_coarse_resolution", "float"),
        ("leiden_fine_resolution", "computation.leiden_fine_resolution", "float"),
        ("mcl_inflation", "computation.mcl_inflation", "float"),
        ("spreading_runs", "computation.spreading_runs", "int"),
        ("diffusion_window", "computation.diffusion_window", "int"),
        ("layouts_2d", "layouts.layouts_2d", "list"),
        ("layouts_3d", "layouts.layouts_3d", "list"),
        ("measures", "measures.selected", "list"),
        ("bridging_basis", "measures.bridging_basis", "value_optional"),
        ("community_strategies", "communities.strategies", "list"),
        ("network_stat_groups", "network_stats.groups", "list"),
        ("vacancy_measures", "vacancy.measures", "list"),
        ("vacancy_months_before", "vacancy.months_before", "int"),
        ("vacancy_months_after", "vacancy.months_after", "int"),
        ("vacancy_max_candidates", "vacancy.max_candidates", "int"),
        ("robustness_alpha", "robustness.alpha", "float"),
        ("robustness_strategies", "robustness.strategies", "list"),
        ("robustness_runs", "robustness.runs", "int"),
        ("robustness_null", "robustness.null", "int"),
        ("robustness_seed", "robustness.seed", "int"),
        ("robustness_sample", "robustness.sample", "int"),
        ("interest_structural", "interest.structural", "bool"),
        ("interest_window_days", "interest.window_days", "int"),
        ("interest_include_mentions", "interest.include_mentions", "bool"),
    ],
}


def _read_default(defaults: dict, dotted_path: str):
    cur: Any = defaults
    for part in dotted_path.split("."):
        cur = cur[part]
    return cur


def _set_nested(d: dict, dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


_FORM_PAYLOAD_MISSING = object()


_BRIDGING_VALID_BASES: frozenset[str] = frozenset(s for s in net_community.VALID_STRATEGIES if s != "ORGANIZATION")


def _validate_post_constraints(task: str, post: Any) -> None:
    """Cross-field validation shared by Save and Run.

    Raises ValueError on inconsistent input. Both DefaultsListView.post
    (save) and RunTaskView.post (run) call this before doing any work, so
    a bad POST is rejected with HTTP 400 + a human-readable message rather
    than reaching the management command and surfacing as a cryptic
    subprocess error.

    Per-task rules:

    * ``structural_analysis``:
        - BRIDGING basis (explicit or default LEIDEN_DIRECTED) must be a
          real strategy (ORGANIZATION excluded because organisation
          membership isn't a community-detection result).
        - BRIDGING basis must be among the selected community_strategies.
        - consensus_matrix requires ≥2 non-ORGANIZATION strategies.

    * ``compare_analysis``: ``project_dir`` and ``compare_target`` are both
      required (the management command would otherwise reject them with a
      CommandError surfaced as a 500 from the runner).

    * ``search_channels``: ``amount``, when set, must be a positive integer.
      QuerySet slicing with non-positive values silently returns an empty
      or counterintuitive (negative-index) slice.
    """
    if not hasattr(post, "getlist"):
        return

    if task == "structural_analysis":
        measures = post.getlist("measures") or []
        robust = post.getlist("robustness_strategies") or []
        strategies = {s.upper() for s in (post.getlist("community_strategies") or [])}

        needs_bridging = "BRIDGING" in measures or "bridging" in {r.lower() for r in robust}
        if needs_bridging:
            basis = (post.get("bridging_basis") or "").strip().upper() or "LEIDEN_DIRECTED"
            if basis not in _BRIDGING_VALID_BASES:
                raise ValueError(
                    f"BRIDGING basis '{basis}' is not a valid community-detection strategy"
                    " (ORGANIZATION is excluded because organisation membership is not a detection result)"
                )
            if basis not in strategies:
                present = ", ".join(sorted(strategies)) or "none selected"
                raise ValueError(
                    f"BRIDGING basis '{basis}' must be one of the selected community strategies (currently: {present})"
                )

        if post.get("consensus_matrix"):
            non_org = strategies - {"ORGANIZATION"}
            if len(non_org) < 2:
                raise ValueError(
                    "Consensus matrix requires at least two non-ORGANIZATION community strategies"
                    f" (currently: {', '.join(sorted(non_org)) or 'none'})"
                )
        return

    if task == "compare_analysis":
        if not (post.get("project_dir") or "").strip():
            raise ValueError("Source export (project_dir) is required")
        if not (post.get("compare_target") or "").strip():
            raise ValueError("Target export name is required")
        return

    if task == "search_channels":
        raw_amount = (post.get("amount") or "").strip()
        if raw_amount:
            try:
                amount = int(raw_amount)
            except ValueError as exc:
                raise ValueError(f"Amount must be an integer, got {raw_amount!r}") from exc
            if amount < 0:
                raise ValueError(f"Amount must be zero or a positive integer, got {amount}")
        return


def _read_nested(d: Any, dotted_path: str) -> Any:
    cur: Any = d
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _FORM_PAYLOAD_MISSING
        cur = cur[part]
    return cur


def _toml_to_form_payload(task: str, merged: dict) -> dict:
    """Reverse of `_form_to_toml_payload`: project a merged TOML dict onto the
    flat ``{form_field_name: value}`` shape the client can apply uniformly.

    Walks the same `TASK_DEFAULT_SPECS` entries used by saving so the field
    mapping stays single-sourced. Fields missing from the merged dict are
    omitted (the client leaves those inputs untouched).
    """
    out: dict = {}
    for post_key, toml_path, kind in TASK_DEFAULT_SPECS[task]:
        value = _read_nested(merged, toml_path)
        if value is _FORM_PAYLOAD_MISSING:
            continue
        if kind == "channel_types_triplet":
            labels = ("CHANNEL", "GROUP", "USER")
            selected = set(value or [])
            for i, name in enumerate(post_key):
                out[name] = labels[i] in selected
        elif kind.startswith("bool_to_enum:"):
            _off, on = kind.split(":", 1)[1].split(",", 1)
            out[post_key] = value == on
        else:
            out[post_key] = value
    return out


def _form_to_toml_payload(task: str, post: Any) -> dict:
    _validate_post_constraints(task, post)
    defaults = CRAWL_DEFAULTS if task == "crawl_channels" else STRUCTURAL_DEFAULTS
    payload: dict = {}
    for post_key, toml_path, kind in TASK_DEFAULT_SPECS[task]:
        if kind == "bool":
            value = bool(post.get(post_key))
        elif kind == "list":
            value = list(post.getlist(post_key))
        elif kind == "value":
            value = post.get(post_key, "").strip()
        elif kind == "value_optional":
            value = post.get(post_key, "").strip()
        elif kind == "palette_name":
            value = post.get(post_key, "").strip()
            if value and not palette_utils.is_known_palette(value):
                raise ValueError(f"Unknown palette: {value!r}")
            if not value:
                value = _read_default(defaults, toml_path)
        elif kind == "int":
            raw = post.get(post_key, "").strip()
            try:
                value = int(raw) if raw else _read_default(defaults, toml_path)
            except (ValueError, TypeError):
                value = _read_default(defaults, toml_path)
        elif kind == "float":
            raw = post.get(post_key, "").strip()
            try:
                value = float(raw) if raw else _read_default(defaults, toml_path)
            except (ValueError, TypeError):
                value = _read_default(defaults, toml_path)
        elif kind == "fa2_iterations":
            # Either an integer (saved as int) or "Nx" multiplier (saved as str).
            # Empty input falls back to the schema default (which is also "7x").
            raw = post.get(post_key, "").strip().lower()
            if not raw:
                value = _read_default(defaults, toml_path)
            elif raw.endswith("x"):
                try:
                    float(raw[:-1])  # validate the number part
                    value = raw
                except (ValueError, TypeError):
                    value = _read_default(defaults, toml_path)
            else:
                try:
                    value = int(float(raw))
                except (ValueError, TypeError):
                    value = _read_default(defaults, toml_path)
        elif kind == "channel_types_triplet":
            labels = ("CHANNEL", "GROUP", "USER")
            value = [labels[i] for i, k in enumerate(post_key) if post.get(k)]
        elif kind.startswith("bool_to_enum:"):
            off, on = kind.split(":", 1)[1].split(",", 1)
            value = on if post.get(post_key) else off
        else:
            raise ValueError(f"Unknown default-spec kind: {kind!r}")
        _set_nested(payload, toml_path, value)
    return payload


class PaletteColorsView(View):
    """Return the colour list of a single pypalettes palette so the Operations form
    can render a live swatch preview without embedding the whole 2707-palette catalogue."""

    def get(self, request: HttpRequest, name: str) -> JsonResponse:
        if not palette_utils.is_known_palette(name):
            return JsonResponse({"error": "unknown palette"}, status=404)
        reverse = request.GET.get("reverse", "").lower() in {"1", "true", "on", "yes"}
        try:
            raw = palette_utils.palette_colors(name, reverse=reverse)
        except (ValueError, KeyError) as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        hex_list = [palette_utils.rgb_to_hex(palette_utils.parse_color(c)) for c in raw]
        return JsonResponse({"name": name, "reverse": reverse, "colors": hex_list})


class DefaultsListView(View):
    """List defaults snapshots for a task (GET) or create a new one (POST).

    GET response shape: ``{"items": [{id, title, pulpit_version,
    generated_at_iso, generated_at_human, is_base}, ...]}``. The bare baseline
    file appears first (id=``"base"``) followed by user snapshots, newest-first.

    POST: the request body is the same FormData the Run endpoint accepts, plus
    a required ``title`` field. The server allocates a fresh timestamped
    filename and returns the new item's metadata.
    """

    def get(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFAULT_SPECS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        return JsonResponse({"items": list_defaults(task)})

    # Match the HTML form's `<input maxlength="120">` so a script that bypasses
    # the browser can't seed huge titles that would bloat the on-disk TOML.
    MAX_TITLE_LENGTH = 120

    def post(self, request: HttpRequest, task: str) -> JsonResponse:
        if task not in TASK_DEFAULT_SPECS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        title = (request.POST.get("title") or "").strip()
        if not title:
            return JsonResponse({"error": "title is required"}, status=400)
        if len(title) > self.MAX_TITLE_LENGTH:
            return JsonResponse(
                {"error": f"title must be at most {self.MAX_TITLE_LENGTH} characters"},
                status=400,
            )
        try:
            payload = _form_to_toml_payload(task, request.POST)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        try:
            item = save_named(task, payload, title)
        except OSError as exc:
            return JsonResponse({"error": f"write failed: {exc}"}, status=500)
        return JsonResponse({"saved": True, "item": item})


class DefaultsItemView(View):
    """Load one defaults snapshot, projecting it onto the form-field name space.

    Response shape: ``{"values": {form_field_name: value, ...}}``. Returns 404
    if the file is absent or the id is malformed.
    """

    def get(self, request: HttpRequest, task: str, snapshot_id: str) -> JsonResponse:
        if task not in TASK_DEFAULT_SPECS:
            return JsonResponse({"error": "Unknown task"}, status=404)
        merged = load_payload_by_id(task, snapshot_id)
        if merged is None:
            return JsonResponse({"file_present": False}, status=404)
        return JsonResponse({"values": _toml_to_form_payload(task, merged)})
