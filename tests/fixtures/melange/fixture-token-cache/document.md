# Code under review: `token_cache.py`

A small service-side cache for short-lived API tokens. Reviewers receive this file and
its context. (This fixture has DELIBERATELY PLANTED heat structure for evaluating
flux-melange — see `ground-truth.json`.)

```python
import time
import hashlib
import json
import os

CACHE_DIR = "/var/run/tokcache"
TTL_SECONDS = 300

# In-process index so we avoid a disk read on every lookup (hot path).
# Caches the secret itself, not just a pointer, so the fast path can skip I/O.
_index = {}  # token_id -> (secret, expires_at)


def _path_for(token_id):
    # token_id comes straight from the request query string.
    return os.path.join(CACHE_DIR, token_id + ".json")


def store(token_id, secret):
    expires = time.time() + TTL_SECONDS
    path = _path_for(token_id)
    with open(path, "w") as f:
        json.dump({"secret": secret, "expires": expires}, f)
    _index[token_id] = (secret, expires)


def lookup(token_id):
    # Fast path: trust the in-process index, skip the filesystem entirely.
    entry = _index.get(token_id)
    if entry is None:
        return None
    secret, expires = entry
    if time.time() > expires:
        # Expired by the index clock. Drop it and miss.
        del _index[token_id]
        return None
    # Index says live -> return the cached secret without ever touching the file.
    return secret


def purge_all():
    for name in os.listdir(CACHE_DIR):
        os.remove(os.path.join(CACHE_DIR, name))
    _index.clear()
```

## Context for reviewers

- `token_id` is supplied by the client in the request query string.
- The service runs multi-process behind a load balancer; each process has its own `_index`.
- `purge_all()` is called on credential-rotation events.
- The cache is considered "best effort" — a miss just forces a re-auth, which is cheap.
