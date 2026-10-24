"""Abuse limits (queue item Z).

Deal creation carries two sliding-window rate caps: one per client
address and one global. The negotiation and delivery endpoints carry a
request-body size cap. Every cap is env-driven with demo-friendly
defaults, and a configured value of 0 or less disables that cap. The
counters live in memory, so a restart clears them. This is demo-grade
protection against accidental floods, not a distributed rate limiter.

Over-limit responses use the clean error envelope from pact/errors.py:
{"error": {"code", "message", "correlation_id"}}. The 429 carries a
Retry-After header with the whole seconds until the oldest entry in
the tripped window expires.
"""

import json
import logging
import math
import os
import time
import uuid
from threading import Lock

from fastapi.responses import JSONResponse

from .errors import ERROR_CODES

log = logging.getLogger("pact.abuse_limits")

# The clock is a module attribute so tests can poke it: set
# abuse_limits._now = lambda: T to fake time passing without sleeping.
_now = time.monotonic

_counters = {"per_ip": {}, "global": []}
_counters_lock = Lock()

# Request path suffixes that take a caller payload and get the size
# cap. Checked in the middleware before the route handler runs, so an
# oversized body is rejected before any parsing or state work.
_SIZED_PATH_SUFFIXES = ("/negotiate/run", "/deliver")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def rate_limit_config():
    """Read the caps from the environment on every call.

    Read at request time (not at import) so tests and operators can
    change them without restarting the process. A value of 0 or less
    disables that cap.
    """
    return {
        "per_ip": _env_int("PACT_MAX_DEALS_PER_MINUTE_PER_IP", 30),
        "global": _env_int("PACT_MAX_DEALS_PER_MINUTE_GLOBAL", 120),
        "window_seconds": _env_float("PACT_RATE_WINDOW_SECONDS", 60),
        "max_request_bytes": _env_int("PACT_MAX_REQUEST_BYTES", 65536),
    }


def reset_counters():
    """Clear every rate window. Tests call this between sections; a
    restart does the same thing for free."""
    with _counters_lock:
        _counters["per_ip"].clear()
        _counters["global"].clear()


def _prune(entries, cutoff):
    return [t for t in entries if t > cutoff]


def _limit_response(code, retry_after=None):
    status, message = ERROR_CODES[code]
    correlation_id = uuid.uuid4().hex
    log.warning(json.dumps({
        "code": code,
        "message": message,
        "correlation_id": correlation_id,
    }))
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        status_code=status,
        content={"error": {
            "code": code,
            "message": message,
            "correlation_id": correlation_id,
        }},
        headers=headers,
    )


def client_key(request):
    """Client address used for the per-IP rate window."""
    client = request.client
    return client.host if client and client.host else "unknown"


def check_rate_limit(key):
    """Apply the deal-creation rate caps for one client address.

    Returns None when the call is allowed (and records it in both
    windows). Returns a 429 JSONResponse with the clean error envelope
    and a Retry-After header when either cap is exceeded. Denied calls
    are not recorded, so a refused burst does not extend its own
    penalty.
    """
    cfg = rate_limit_config()
    window = cfg["window_seconds"]
    now = _now()
    cutoff = now - window
    with _counters_lock:
        ip_entries = _prune(_counters["per_ip"].get(key, []), cutoff)
        global_entries = _prune(_counters["global"], cutoff)
        tripped = None
        if cfg["per_ip"] > 0 and len(ip_entries) >= cfg["per_ip"]:
            tripped = ip_entries
        elif cfg["global"] > 0 and len(global_entries) >= cfg["global"]:
            tripped = global_entries
        if tripped is None:
            _counters["per_ip"][key] = ip_entries + [now]
            _counters["global"] = global_entries + [now]
            return None
        retry_after = max(1, math.ceil(min(tripped) + window - now))
        return _limit_response("RATE_LIMITED", retry_after=retry_after)


def check_payload_size(request):
    """Apply the request-body size cap to one request.

    Returns None when the body is within the cap or the length is
    unknown. Returns a 413 JSONResponse with the clean error envelope
    when Content-Length exceeds the cap.
    """
    limit = rate_limit_config()["max_request_bytes"]
    if limit <= 0:
        return None
    length = request.headers.get("content-length")
    if length is None:
        return None
    try:
        size = int(length)
    except (TypeError, ValueError):
        return None
    if size > limit:
        return _limit_response("PAYLOAD_TOO_LARGE")
    return None


def sized_path(path):
    """True for the endpoints that carry the payload size cap."""
    return path.endswith(_SIZED_PATH_SUFFIXES)
