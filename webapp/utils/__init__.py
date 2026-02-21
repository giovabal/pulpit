from pprint import pprint

from .colors import *  # noqa


def _get_dict(obj):
    if hasattr(obj, "__dict__"):
        return {k: _get_dict(v) for k, v in obj.__dict__.items() if not callable(v) and not k.startswith("_")}
    else:
        return obj


def print_dict(obj):
    pprint(_get_dict(obj))
