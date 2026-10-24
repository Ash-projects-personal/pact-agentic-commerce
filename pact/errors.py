"""Clean error surfaces (queue item X).

No API error response may contain a raw PayPal response body, a stack
trace, or an internal exception string. Upstream failures are mapped to
a small set of clean codes, each with a human sentence. The full
upstream detail is written only into the audit ledger event on the deal
and the server log, under a correlation id that the error response
carries, so the failure can be traced without the response ever
carrying the raw payload. Token-like values in upstream bodies are
redacted before they reach the ledger or the log.
"""

import json
import logging
import re
import uuid

from fastapi.responses import JSONResponse

log = logging.getLogger("pact.upstream")

# The full code set. One code per money failure mode, plus the abuse
# limit codes (queue item Z), plus a generic upstream code for anything
# unexpected. The message is the only thing a caller ever sees; it
# names what happened in plain words and what the caller can do next.
ERROR_CODES = {
    "ORDER_CREATION_FAILED": (
        502,
        "The PayPal order could not be created. No money moved. "
        "The deal is unchanged and the call can be retried.",
    ),
    "CAPTURE_FAILED": (
        502,
        "PayPal did not complete the capture. No money was captured. "
        "The deal keeps its state and the step can be retried.",
    ),
    "ORDER_READ_FAILED": (
        502,
        "The order could not be read back from PayPal. The step did not "
        "complete and can be retried.",
    ),
    "PAYOUT_FAILED": (
        502,
        "PayPal did not start the payout. No money moved. The deal stays "
        "in the verifying state so a later call resumes the leg.",
    ),
    "REFUND_FAILED": (
        502,
        "PayPal did not issue the refund. No money moved. The deal stays "
        "in the verifying state so a later call resumes the leg.",
    ),
    "MARKET_GROUNDING_FAILED": (
        502,
        "Market data for the procurement deal could not be fetched. "
        "No deal was created.",
    ),
    "UPSTREAM_UNAVAILABLE": (
        502,
        "The payment service did not answer as expected. Nothing was "
        "settled on this attempt. Retry the call.",
    ),
    "RATE_LIMITED": (
        429,
        "Too many deals created. Wait a moment and try again.",
    ),
    "PAYLOAD_TOO_LARGE": (
        413,
        "This request is larger than the limit. Send a smaller payload "
        "and try again.",
    ),
    "INTERNAL_ERROR": (
        500,
        "Something went wrong on our side. Nothing was settled on this "
        "attempt.",
    ),
}


# Values that must never reach a ledger event, a server log line, or a
# response, even when they ride inside an upstream error body.
_REDACT_PATTERNS = [
    (re.compile(
        r'(?i)("(?:access_token|refresh_token|client_secret|secret|password'
        r'|api_key|apikey|token)"\s*:\s*")([^"]+)'), r"\1[redacted]"),
    (re.compile(
        r"(?i)\b(?:access_token|refresh_token|client_secret|secret|password"
        r"|api_key)\s*=\s*([^\s,&}]+)"), "[redacted]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [redacted]"),
]


def redact_upstream(text):
    """Strip token-like values from an upstream error body."""
    if not text:
        return ""
    out = str(text)
    for pattern, replacement in _REDACT_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def build_error_response(deal, code, exc=None, *, where="",
                         event_type="upstream_error", message=None):
    """Build the clean error response for an upstream failure.

    Writes one structured line to the server log and one ledger event
    on the deal, both carrying the full (redacted) upstream detail
    under the same correlation id the response carries. The response
    itself carries only the code, the human sentence, and the id.
    Returns (JSONResponse, correlation_id).
    """
    from .store import add_event

    correlation_id = uuid.uuid4().hex
    status, default_message = ERROR_CODES[code]
    human = message or default_message
    detail = redact_upstream(exc) if exc is not None else ""
    log.error(json.dumps({
        "correlation_id": correlation_id,
        "code": code,
        "where": where,
        "event_type": event_type,
        "upstream_detail": detail,
    }))
    if deal is not None:
        add_event(deal, event_type, "system", human, {
            "code": code,
            "correlation_id": correlation_id,
            "where": where,
            "upstream_detail": detail,
        })
    response = JSONResponse(
        status_code=status,
        content={"error": {
            "code": code,
            "message": human,
            "correlation_id": correlation_id,
        }},
    )
    return response, correlation_id


class UpstreamFailure(Exception):
    """Carries a finished clean error out of a helper.

    Helpers like _capture_both cannot return an HTTP response to their
    caller, so they raise this once the error is fully recorded. The
    endpoint catches it and returns .response.
    """

    def __init__(self, code, correlation_id, response):
        super().__init__(code)
        self.code = code
        self.correlation_id = correlation_id
        self.response = response


def raise_upstream(deal, code, exc=None, *, where="",
                   event_type="upstream_error", message=None):
    """Record the failure and raise it as an UpstreamFailure."""
    response, correlation_id = build_error_response(
        deal, code, exc, where=where, event_type=event_type,
        message=message)
    raise UpstreamFailure(code, correlation_id, response)
