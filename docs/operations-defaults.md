# Operations defaults & configuration

This page describes where each kind of setting lives, how the Operations panel pre-populates its forms, and what the **Save as defaults**, **Load defaults**, and **Write CLI command** buttons actually do.

The short version: every analyst-tunable option flows through one of three layers — `.env`, the `.operations-*` snapshot files, or the live form — and each layer has a single responsibility. The Operations panel reads the snapshot files to pre-populate the form; the CLI reads only the explicit flags you pass. There is no longer a silent settings-fallback chain.

---

## The three layers

### 1. `configuration/.env` — credentials and deployment

Everything that's *about the machine Pulpit is running on*:

- Telegram API credentials (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE_NUMBER`).
- Telegram client tuning (`TELEGRAM_SESSION_NAME`, `TELEGRAM_CONNECTION_RETRIES`, `TELEGRAM_RETRY_DELAY`, `TELEGRAM_FLOOD_SLEEP_THRESHOLD`, `TELEGRAM_IGNORE_FLOODWAIT`, `TELEGRAM_FLOODWAIT_SLEEP_SECONDS`, `TELEGRAM_CRAWLER_GRACE_TIME`). All optional with sensible defaults — see `configuration/env.example`.
- Django basics (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, database, language/timezone).
- Web access policy (`WEB_ACCESS`).
- Project identity (`PROJECT_TITLE`).

The `.env` file is read once at startup by `python-decouple`. Restart the server after editing it.

Comments must live on their own line. `python-decouple` does not strip inline `#` comments, so writing `WEB_ACCESS=ALL  # explanation` leaves the explanation in the value. (Pulpit defensively strips inline comments from `WEB_ACCESS` to absorb that footgun, but it's a footgun nonetheless — see `env.example` for the correct pattern.)

### 2. `configuration/.operations-{crawl,structural}` — bundled "Pulpit defaults" baseline

These two committed TOML files carry the **baseline pre-population values for the Operations-panel forms**. They are tracked in git so a fresh checkout already has reasonable form defaults; whoever curates a Pulpit fork bumps these files to taste.

Each file starts with a `[meta]` block:
```toml
[meta]
title = "Pulpit defaults"
pulpit_version = "0.21"
generated_at = "2026-05-21T00:00:00Z"
```

Followed by typed sections that mirror `webapp_engine/config/defaults.py`:
- `.operations-crawl` has `[downloads]`, `[scope]`, `[channels]`, `[messages]`, `[degrees]`.
- `.operations-structural` has `[graph]`, `[outputs]`, `[edges]`, `[scope]`, `[computation]`, `[layouts]`, `[measures]`, `[communities]`, `[network_stats]`, `[vacancy]`, `[robustness]`.

These files are loaded once at startup and exposed under `settings.CRAWL_*` / `settings.SA_*` / `settings.COMMUNITY_PALETTE` etc. **Only the Operations panel reads those settings** — the CLI commands no longer consult them.

If a file is missing or omits a section, the loader fills in from the hardcoded factory-empty defaults in `webapp_engine/config/defaults.py` (everything off, every list empty). That's the "do nothing if invoked like that" semantics the CLI also enforces.

### 3. Saved snapshots — `configuration/.operations-{stem}-{timestamp}`

Every click of **Save as defaults** writes a new file alongside the baseline:
```
configuration/.operations-crawl-2026-05-21T14-32-00Z
configuration/.operations-structural-2026-05-21T14-35-12Z
```

These are gitignored. They never overwrite the baseline. They never affect the form's startup pre-population — they're only loaded on demand when you click **Load defaults** and pick one from the picker.

The `[meta]` block at the top of each snapshot records the title you typed, the Pulpit version that produced it, and the UTC timestamp.

---

## The three Operations-panel buttons

All three sit in the footer of the Crawl-channels and Structural-analysis forms, styled in the project's indigo accent palette.

### Save as defaults

Click → modal asks for a **title** (e.g. *"Production crawl, no media"*) → `POST /operations/defaults/<task>/` with the form data + the title → server writes a new `.operations-{stem}-{timestamp}` file with a `[meta]` block carrying the title.

The committed baseline is read-only via the API. Saves always create a new file; duplicate titles are allowed (uniqueness comes from the filename's timestamp). Same-second collisions advance the timestamp by 1 second so concurrent saves don't overwrite each other.

Server-side validation (`_validate_post_constraints` in `runner/views.py`) rejects inconsistent inputs before writing — e.g. a BRIDGING measure with a `bridging_basis` that isn't in the selected `community_strategies`, a `consensus_matrix` request with fewer than two non-ORGANIZATION strategies, an `amount` ≤ 0 for `search_channels`, an empty `project_dir` for `compare_analysis`.

### Load defaults

Click → modal calls `GET /operations/defaults/<task>/` → renders a list of every available snapshot (baseline + user files), newest first, each row showing the title, a human-readable timestamp (`YYYY-MM-DD HH:MM UTC`), and the Pulpit version that wrote it → clicking a row fetches `GET /operations/defaults/<task>/<id>/` and applies its values to the live form via JS.

Loading is purely client-side: nothing is persisted until you click Save or Run again. The baseline always appears (you can always reset to "Pulpit defaults"); user snapshots only appear if they exist.

### Write CLI command

Click → `POST /operations/write-cli-command/<task>/` runs the same `_validate_post_constraints` + `_build_args` path the Run endpoint uses, and returns the exact `python manage.py <task> --flag1 --flag2 …` string the form would launch. The string is rendered in a red preview pane below the form; the args are `shlex.quote`-d so multi-word values stay shell-safe.

The same validation rules apply: an inconsistent form returns 400 with a clear error toast instead of a preview.

The preview persists until you click **Write CLI command** again (or refresh the page).

---

## CLI semantics — every flag is explicit

Bare invocations are now no-ops:

```sh
python manage.py crawl_channels         # exits in <1 s, no Telegram traffic
python manage.py structural_analysis    # exits with "Nothing to do — …"
```

If you want the CLI to do work, pass the flags explicitly. The Operations panel does this automatically for every checkbox (using `--flag` / `--no-flag` pairs), so panel-driven runs are unaffected. The "Write CLI command" button is the easiest way to discover the right flag combination — copy what it generates and paste into a script.

Backward-compat aliases are kept for the renamed flags, so existing scripts still work:

| Canonical | Legacy alias |
|---|---|
| `--graph-2d` | `--2dgraph` |
| `--graph-3d` | `--3dgraph` |
| `--layouts-2d` | `--2dlayouts` |
| `--layouts-3d` | `--3dlayouts` |
| `--fix-holes` | `--fixholes` |
| `--fetch-recommended` | `--fetch-recommended-channels` |

---

## Editing a snapshot file by hand

You can. The loader silently strips:
- `[meta]` (never deep-merged into the live settings — it's informational).
- Legacy top-level `pulpit_version` / `generated_at` keys (pre-`[meta]` format).
- Legacy `[telegram]` blocks (moved to `.env`).
- Legacy key names (e.g. `messages.fixholes`, `layouts.two_d`) — automatically translated to their canonical form.

Re-saving a hand-edited file through the Operations panel rewrites it with the canonical key names + a fresh `[meta]` block.

---

## Wiring a new option through the system

When you add an option that the analyst should be able to tweak:

1. **Schema** — add the key + factory-empty default value to `CRAWL_DEFAULTS` / `STRUCTURAL_DEFAULTS` in `webapp_engine/config/defaults.py`, under the matching section.
2. **Settings binding** — read it from `_crawl.X.Y` / `_structural.X.Y` in `webapp_engine/settings.py` and expose it under a `CRAWL_*` / `SA_*` name.
3. **Form** — add an `<input name="…">` in `runner/templates/runner/operations.html`, with a `{% if ad.X %}checked{% endif %}` / `{% if "X" in ad.sa_X %}…` clause referencing the matching `ad` key.
4. **OperationsView ad dict** — add `"X": settings.X` in `runner/views.py`'s `OperationsView.get`.
5. **TASK_DEFAULT_SPECS** — add `(post_key, "section.key", kind)` so "Save as defaults" persists the value through the round-trip.
6. **TASK_ARG_SPECS** — add the kind that emits the matching CLI flag(s).
7. **CLI argparse** — add the flag in the management command, with `default=None` and the appropriate type/action; resolve via `_o(key, NO_OP_LITERAL)` or the equivalent helper.
8. **Bundled baseline** — if you want the option non-empty by default, add it under the matching section in the committed `.operations-{crawl,structural}` file.

The `TASK_DEFAULT_SPECS` walker (`_form_to_toml_payload` and `_toml_to_form_payload` in `runner/views.py`) drives both Save and Load. Anything in the spec round-trips automatically; anything outside the spec (export name, start/end dates, channel groups, etc.) is per-run only.
