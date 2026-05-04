import datetime
from typing import Any

from django.db.models import F, Q

type GraphData = dict[str, list[dict[str, Any]]]
type CommunityTableData = dict[str, Any]
# CommunityTableData structure:
# {
#   "network_summary": dict,          # from _network_summary() plus "centralizations"
#   "strategies": {
#     strategy_key: [                 # ordered as in communities_data
#       {"group": tuple, "node_count": int, "metrics": dict},
#       ...
#     ]
#   }
# }


def channel_cutoff_q(channel_field: str = "channel", date_field: str = "date") -> Q:
    """Q that excludes messages past their channel's uninteresting_after date.

    Pass ``channel_field`` / ``date_field`` to adjust the ORM path when the
    Message is accessed through a related model (e.g. ``message__channel`` /
    ``message__date`` for the references through-table).
    """
    return Q(**{f"{channel_field}__uninteresting_after__isnull": True}) | Q(
        **{f"{date_field}__date__lte": F(f"{channel_field}__uninteresting_after")}
    )


def make_date_q(
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    field: str = "date",
) -> Q:
    """Build a Q filter for an inclusive date range on a DateTimeField.

    ``field`` is the ORM field name prefix (default ``"date"``), so the
    generated lookup is ``<field>__date__gte`` / ``<field>__date__lte``.
    Returns an empty Q() when both bounds are None.
    """
    q = Q()
    if start_date:
        q &= Q(**{f"{field}__date__gte": start_date})
    if end_date:
        q &= Q(**{f"{field}__date__lte": end_date})
    return q
