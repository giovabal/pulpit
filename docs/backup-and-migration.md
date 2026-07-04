# Backup and migration

`export_installation.py` bundles a whole Pulpit installation — database, Telegram session, configuration, and media — into a single directory whose layout mirrors the project root. Copy that directory's contents over another Pulpit checkout and it runs with this installation's data, credentials, and crawl session, with no re-setup.

Use it to:

- **Back up** an installation before an upgrade or a risky operation.
- **Move** an installation to another machine or a fresh checkout.
- **Hand off** a project to a colleague, or archive a finished one.

---

## Usage

Run it from the project root (the folder that contains `manage.py`):

```sh
python export_installation.py DEST [--media ALL|TYPE,TYPE,...] [--dry-run] [--force]
```

`DEST` is the directory the bundle is written to. It must be **outside** the project tree.

### Examples

```sh
# Everything — database, session, configuration, and every media type
python export_installation.py ~/pulpit-backup

# Only images and stickers (skip the heavy video/audio)
python export_installation.py ~/pulpit-backup --media IMAGES,STICKERS

# Database, configuration and session only — no media at all
python export_installation.py ~/pulpit-backup --media NONE

# See how big a full export would be, without writing anything
python export_installation.py ~/pulpit-backup --dry-run
```

The output shows a per-component summary (files, size, status) and — for the media copy, which is usually the slow part — a live progress bar with transfer speed and time remaining. Video typically dominates the total size, so a `--dry-run` first is a good habit.

---

## What gets bundled

| Component | Source | In the bundle | Notes |
| :--- | :--- | :--- | :--- |
| Database | `db.sqlite3` | `db.sqlite3` | SQLite only — see [The database](#the-database) below |
| Telegram session | `<session>.session` | same path | So crawling works on the target without logging in again |
| Configuration | `configuration/` | `configuration/` | The whole directory: `.env`, `env.example`, and every `.operations-*` baseline/snapshot |
| Media | `media/<type>/` | `media/<type>/` | Only the types you select — see [Media types](#media-types) |

Everything is written at its path **relative to the project root**, which is what makes the bundle drop-in: copying its contents into another checkout puts each file exactly where Pulpit expects it.

---

## Media types

`--media` takes `ALL` (default), `NONE`, or a comma-separated list of these tokens:

| Token | Directory | Contents |
| :--- | :--- | :--- |
| `IMAGES` | `media/photos/` | Message photos |
| `VIDEO` | `media/videos/` | Message videos, GIFs, round videos |
| `AUDIO` | `media/audios/` | Message audio and voice notes |
| `STICKERS` | `media/stickers/` | Stickers (static and animated) |
| `OTHER_MEDIA` | `media/others/` | Documents and any other files |
| `PROFILE` | `media/channels/` | Channel profile pictures (avatars) |
| `ALL` | — | Every type above (the default) |
| `NONE` | — | No media — database, configuration and session only |

The database, session, and configuration are **always** bundled; `--media` only controls the media payload.

---

## Restoring on another installation

The bundle mirrors the project layout, so applying it is a plain copy followed by a migration:

```sh
cp -a /path/to/bundle/. /path/to/other/pulpit/
cd /path/to/other/pulpit
python manage.py migrate
```

`cp -a` preserves the directory structure and file timestamps. The `migrate` step is a safety net: if the target checkout is a newer Pulpit version, it brings the copied database up to the current schema. (If the versions match, it does nothing.)

> The target must be an actual Pulpit checkout — the bundle carries your **data and configuration**, not the code. See [What is not included](#what-is-not-included).

---

## The database

**SQLite (the default).** The database is copied with SQLite's `VACUUM INTO`, which writes a clean, defragmented, single-file snapshot. It is consistent even if Pulpit is running while you export (the database is in WAL mode), and it needs none of the `-wal` / `-shm` sidecar files — the bundle is one self-contained `db.sqlite3`.

**External databases (PostgreSQL, MySQL/MariaDB, Oracle).** The exporter cannot bundle a database *server*, so it skips the database with a note and bundles everything else. Dump and restore it with the database's own tools (for example `pg_dump` / `pg_restore`). The bundled `configuration/.env` already points at the right database, so once you restore the data on the target, the rest of the bundle lines up with it.

---

## What is not included

- **The code.** The target is another Pulpit *checkout* and brings its own code; only your data and configuration travel in the bundle.
- **`.system`.** This is version metadata tied to the code and belongs to the target's own checkout — bundling it would misreport the version, so it is deliberately left out.
- **Regenerable output.** The `graph/` exports and on-disk caches are not included; rebuild them with a structural-analysis run on the target.

---

## Security

The bundle contains `configuration/.env` (Telegram API keys, Django `SECRET_KEY`, database credentials) and the Telegram **session file**, which grants full access to the logged-in Telegram account. Treat the bundle like a password:

- Transfer it over a secure channel.
- Store it encrypted, and delete stray copies when you are done.
- Never commit it to a repository or upload it to a shared drive in the clear.

Anyone who obtains the bundle can act as your Telegram account and read your entire database.
