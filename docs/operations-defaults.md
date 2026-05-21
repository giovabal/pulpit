# Operations defaults & configuration

This page describes how the Operations panel, the CLI, and the saved snapshot files relate, and what the **Save as defaults**, **Load defaults**, and **Write CLI command** buttons actually do.

The short version: every analyst-tunable option flows through one of three layers — `.env`, the `.operations-*` snapshot files, or the live form — and each layer has a single responsibility. The Operations panel reads the snapshot files to pre-populate the form; the CLI reads only the explicit flags you pass. There is no longer a silent settings-fallback chain.

For the exhaustive per-setting tables (every key, type, and built-in default) see the [Configuration reference](configuration.md).

---

## The three layers

1. **`configuration/.env`** — credentials and deployment infrastructure: Telegram API keys + client tuning, database, secret key, `WEB_ACCESS`, locale, project identity. Read once at startup by `python-decouple`; restart the server after editing. Comments must live on their own line — `python-decouple` does not strip inline `#` comments.
2. **`configuration/.operations-{crawl,structural}`** — bundled "Pulpit defaults" TOML baselines that pre-populate the Operations-panel forms. Each opens with a `[meta]` block (`title`, `pulpit_version`, `generated_at`) and is committed in git so a fresh checkout already has working form defaults. Only the Operations panel reads these — the CLI does not consult them. When a file is missing or omits a key, the loader fills in from the factory-empty defaults in `webapp_engine/config/defaults.py` (everything off, every list empty).
3. **`configuration/.operations-{stem}-{timestamp}`** — gitignored timestamped snapshots written by **Save as defaults**. They never overwrite the baseline and never affect startup pre-population; they're loaded on demand when the user picks one from the **Load defaults** picker. Each snapshot's `[meta]` block records the title (max 120 chars; required), the Pulpit version, and the UTC timestamp.

For the per-key reference of each TOML section, see [Configuration reference](configuration.md).

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

---

## Why two formats?

`.env` uses dotenv (`KEY=value`) because that's the universal convention for environment variables — Docker Compose's `env_file`, CI/CD secret injectors, IDE runtime configs, and `direnv` all read it natively. Pulpit's `.env` carries exactly what the convention serves: credentials and per-deployment switches.

The `.operations-*` files use TOML because their schema is hierarchical (per-section), typed (booleans, integers, floats, strings, lists), and benefits from comment preservation across rewrites (`tomlkit`). TOML is the modern Python project-config standard (`pyproject.toml`). YAML's indentation-sensitive type inference would be a hand-edit hazard; JSON disallows comments; INI loses both types and comments on rewrite; Python config files are an execution-time security hole.

The split mirrors the audience: `.env` is sysadmin / deployment territory; `.operations-*` is analyst territory. They have different update cadences and different sets of consumers, and keeping them in their respective natural formats avoids forcing one user group to learn the other's idiom.
