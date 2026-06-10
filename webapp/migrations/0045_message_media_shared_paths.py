"""Move message media to telegram_id-keyed shared paths.

Before this migration the upload path was ``channels/<user>/message/<msg.telegram_id>.<ext>``,
keyed on the recipient Message. That schema couldn't represent a forwarded photo
(same Telegram photo.id appearing under multiple Message rows) — the lookup in
``from_telegram_object`` deduped on telegram_id alone, so a forward's recovery
silently overwrote the original message's file and never gave the forwarded
Message its own MessagePicture row.

After this migration:
  - Identity is (telegram_id, message): each Message that references a photo can
    have its own row.
  - The on-disk path is keyed on telegram_id alone (e.g. ``photos/<id>.<ext>``),
    so every row that shares a photo points to the SAME file on disk — no
    storage duplication.

Data step moves every existing file to its new path and rewrites the FileField
value. The migration is idempotent (rows already at the new path are skipped),
``atomic=False`` so an interrupted run can be resumed without rolling back, and
prints progress to stderr (silenced under the test runner, where the step
re-runs on every DB build with nothing to migrate) — the move is fast (atomic
rename on the same filesystem) but the per-row UPDATE makes a full run take
order ~minutes on a 700k-row dataset.
"""

from __future__ import annotations

import os
import sys

from django.conf import settings
from django.db import migrations, models

_MODEL_PATHS: tuple[tuple[str, str, str], ...] = (
    # (model_name, file_field, new_path_prefix)
    ("MessagePicture", "picture", "photos"),
    ("MessageVideo", "video", "videos"),
    ("MessageAudio", "audio", "audios"),
    ("MessageSticker", "sticker", "stickers"),
    ("MessageOtherMedia", "media_file", "others"),
)


def _progress(message: str) -> None:
    """Print migration progress to stderr, but stay silent under the test
    runner: this data step re-runs on every test DB build with nothing to
    migrate, so the output is pure noise there. ``settings.TESTING`` is set in
    settings.py when running ``manage.py test``."""
    if getattr(settings, "TESTING", False):
        return
    print(message, file=sys.stderr, flush=True)


def _migrate_model(apps, model_name: str, file_field: str, prefix: str) -> None:
    Model = apps.get_model("webapp", model_name)
    media_root = str(settings.MEDIA_ROOT)
    # Only rows that actually have a stored filename can be migrated. ``picture
    # IS NULL`` is impossible here (FileField stores ''), but ``= ''`` skips
    # ``messagepicture__isnull=True`` zombies that never had a file.
    qs = Model.objects.exclude(**{file_field: ""})
    total = qs.count()
    if total == 0:
        _progress(f"  {model_name}: nothing to migrate")
        return
    _progress(f"  {model_name}: {total} row(s) to consider")
    migrated = 0
    already = 0
    missing = 0
    for obj in qs.iterator(chunk_size=1000):
        current = getattr(obj, file_field).name
        if not current:
            continue
        if current.startswith(prefix + "/"):
            already += 1
            continue
        _root, ext = os.path.splitext(current)
        if not ext:
            ext = ".bin"
        new_path = f"{prefix}/{obj.telegram_id}{ext}"
        old_full = os.path.join(media_root, current)
        new_full = os.path.join(media_root, new_path)
        os.makedirs(os.path.dirname(new_full), exist_ok=True)
        if os.path.exists(old_full):
            if not os.path.exists(new_full):
                # Atomic on the same filesystem. Cross-fs would raise OSError —
                # we don't expect that here because the rename stays under
                # MEDIA_ROOT, but we'd rather surface it than silently swallow.
                os.rename(old_full, new_full)
        else:
            missing += 1
        setattr(obj, file_field, new_path)
        obj.save(update_fields=[file_field])
        migrated += 1
        if migrated % 10000 == 0:
            _progress(f"    {model_name}: {migrated}/{total} processed ({missing} files missing on disk)")
    _progress(f"  {model_name}: {migrated} migrated, {already} already at new path, {missing} missing source files")


def move_files_to_shared_paths(apps, schema_editor) -> None:
    _progress("Moving message media to telegram_id-keyed paths…")
    for model_name, file_field, prefix in _MODEL_PATHS:
        _migrate_model(apps, model_name, file_field, prefix)


def noop_reverse(apps, schema_editor) -> None:
    # The reverse mapping (new path → original per-message path) requires a
    # JOIN to the Message + Channel rows for the channel directory, which the
    # forward migration loses access to. A real rollback would need to be done
    # offline from a backup; we won't fake it here.
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("webapp", "0044_message_total_reactions"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="messagepicture",
            constraint=models.UniqueConstraint(fields=("telegram_id", "message"), name="messagepicture_tid_msg_uniq"),
        ),
        migrations.AddConstraint(
            model_name="messagevideo",
            constraint=models.UniqueConstraint(fields=("telegram_id", "message"), name="messagevideo_tid_msg_uniq"),
        ),
        migrations.AddConstraint(
            model_name="messageaudio",
            constraint=models.UniqueConstraint(fields=("telegram_id", "message"), name="messageaudio_tid_msg_uniq"),
        ),
        migrations.AddConstraint(
            model_name="messagesticker",
            constraint=models.UniqueConstraint(fields=("telegram_id", "message"), name="messagesticker_tid_msg_uniq"),
        ),
        migrations.AddConstraint(
            model_name="messageothermedia",
            constraint=models.UniqueConstraint(
                fields=("telegram_id", "message"), name="messageothermedia_tid_msg_uniq"
            ),
        ),
        migrations.RunPython(move_files_to_shared_paths, noop_reverse),
    ]
