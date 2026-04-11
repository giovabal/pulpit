# delete_unused_messages.py
#
# Deletes messages that belong to channels outside the active crawl scope:
# neither marked interesting nor referenced (forwarded-from) by interesting channels.
#
# When to use:
#   - After un-marking organisations/channels as interesting, to reclaim disk space.
#   - Before running VACUUM on the SQLite database for best space recovery.
#   - Safe to run at any time; the crawler will re-fetch nothing that was deleted
#     because those channels are no longer crawled anyway.
#
# How to run:
#   python manage.py shell < scripts/delete_unused_messages.py
#
# Follow up with:
#   sqlite3 db.sqlite3 "VACUUM;"

from webapp.models import Channel, Message

interesting_ids = set(Channel.objects.interesting().values_list("id", flat=True))
referenced_ids = set(
    Channel.objects.interesting()
    .exclude(message_set__forwarded_from__isnull=True)
    .values_list("message_set__forwarded_from_id", flat=True)
    .distinct()
)
keep_ids = interesting_ids | referenced_ids
qs = Message.objects.exclude(channel_id__in=keep_ids)
print(f"Messages to delete: {qs.count()}")
deleted, _ = qs.delete()
print(f"Deleted: {deleted}")
