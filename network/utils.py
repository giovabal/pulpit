import datetime
from typing import Any

from django.db.models import Q

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
