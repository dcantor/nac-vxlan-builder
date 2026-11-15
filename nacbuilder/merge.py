"""Deep merge for NaC data (dicts merge by key, lists concatenate without exact duplicates)."""

import copy


def merge(a, b, prefer_b: bool = True):
    """Merge b into a, returning a new value. On scalar conflicts b wins unless prefer_b=False."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = copy.deepcopy(a)
        for k, v in b.items():
            out[k] = merge(out[k], v, prefer_b) if k in out else copy.deepcopy(v)
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = copy.deepcopy(a)
        out += [copy.deepcopy(x) for x in b if x not in a]
        return out
    return copy.deepcopy(b if prefer_b else a)


def keep(generated, extra):
    """Add preserved `extra` settings to `generated` without overriding anything generated."""
    return merge(generated, extra or {}, prefer_b=False) if extra else generated
