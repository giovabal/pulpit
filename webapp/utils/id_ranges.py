from django.db.models import Q


def parse_id_ranges(value: str) -> Q:
    """Parse a comma-separated list of positive-integer IDs and ranges into a Django Q object.

    Supported tokens (whitespace around tokens and within ranges is ignored):
        N       — exact match: id = N
        N-M     — inclusive range: id >= N and id <= M
        -N      — upper bound: id <= N
        N-      — lower bound: id >= N

    Multiple tokens are OR-ed together.

    Raises ValueError for malformed tokens or an empty/blank input.
    """
    conditions: list[Q] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            if token.startswith("-"):
                # Upper bound: -N
                n = int(token[1:].strip())
                if n < 1:
                    raise ValueError(f"ID must be a positive integer, got {n!r}")
                conditions.append(Q(id__lte=n))
            elif token.endswith("-"):
                # Lower bound: N-
                n = int(token[:-1].strip())
                if n < 1:
                    raise ValueError(f"ID must be a positive integer, got {n!r}")
                conditions.append(Q(id__gte=n))
            elif "-" in token:
                # Range: N-M
                lo_str, hi_str = token.split("-", 1)
                lo, hi = int(lo_str.strip()), int(hi_str.strip())
                if lo < 1 or hi < 1:
                    raise ValueError(f"IDs must be positive integers, got {token!r}")
                if lo > hi:
                    raise ValueError(f"Invalid range {token!r}: lower bound {lo} > upper bound {hi}")
                conditions.append(Q(id__gte=lo, id__lte=hi))
            else:
                # Exact match: N
                n = int(token)
                if n < 1:
                    raise ValueError(f"ID must be a positive integer, got {n!r}")
                conditions.append(Q(id=n))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Invalid ID range token {token!r}") from exc

    if not conditions:
        raise ValueError(f"No valid ID ranges found in {value!r}")

    result = conditions[0]
    for cond in conditions[1:]:
        result |= cond
    return result
