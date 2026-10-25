"""Tests for the Turso persistence branch (queue item Q follow-up).

pact/persistence.py gained a Turso branch on 2026-10-24: when
TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set, deals, ledger events,
reputation, and webhook ids live in a Turso cloud database instead of
the local SQLite file, so a Render spin-down cannot wipe them. Without
those two variables the local file is used exactly as before.

These tests prove the branch without a cloud account: the libsql client
accepts a local file URL, so the Turso code path runs against a throwaway
local file and the same SQL is exercised. The fallback and the
PACT_DB_PATH precedence rule are pinned too, because a misread there
would send test or local runs to the cloud by accident.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# PACT_DB_PATH must be unset for the Turso branch to engage at all.
os.environ.pop("PACT_DB_PATH", None)

from pact import persistence, store

failures = []


def check(cond, label, detail=None):
    if cond:
        print(f"  ok: {label}")
    else:
        print(f"  FAIL: {label} :: {detail}")
        failures.append(label)


def reset_env():
    os.environ.pop("TURSO_DATABASE_URL", None)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    os.environ.pop("PACT_DB_PATH", None)
    persistence._active_path = None


def main():
    tmp = Path(tempfile.mkdtemp())
    turso_file = tmp / "turso-test.db"

    print("TEST 1 config gating: both vars, or neither, or one alone")
    reset_env()
    check(persistence._turso_config() is None, "no vars -> no Turso",
          persistence._turso_config())
    os.environ["TURSO_DATABASE_URL"] = "file:" + str(turso_file)
    check(persistence._turso_config() is None, "url alone -> no Turso",
          persistence._turso_config())
    os.environ["TURSO_AUTH_TOKEN"] = "dummy-token-for-local-file"
    cfg = persistence._turso_config()
    check(cfg is not None and cfg[0] == "file:" + str(turso_file),
          "url plus token -> Turso config", cfg)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    check(persistence._turso_config() is None, "token alone -> no Turso",
          persistence._turso_config())
    os.environ["TURSO_AUTH_TOKEN"] = "dummy-token-for-local-file"

    print("TEST 2 PACT_DB_PATH wins over Turso")
    sqlite_file = tmp / "local.db"
    os.environ["PACT_DB_PATH"] = str(sqlite_file)
    check(persistence._turso_config() is None,
          "PACT_DB_PATH set -> Turso ignored",
          persistence._turso_config())
    os.environ.pop("PACT_DB_PATH", None)

    print("TEST 3 round trip through the Turso branch (local libsql file)")
    store.DEALS.clear()
    store.GLOBAL_EVENTS.clear()
    store.DEALS["pact-test-turso-1"] = {
        "id": "pact-test-turso-1",
        "scenario": "logo_brand_kit",
        "state": "released",
        "price_cents": 22217,
    }
    store.GLOBAL_EVENTS.append(
        {"seq": 1, "type": "deal_created", "deal_id": "pact-test-turso-1"})
    store.claim_webhook_event("evt-turso-test-1")
    persistence.init_db()
    check(turso_file.exists(), "Turso branch created the libsql file",
          str(turso_file))
    check(not sqlite_file.exists(),
          "local SQLite file never touched while Turso is set",
          str(sqlite_file))
    persistence.save_all()
    persistence.probe()
    store.DEALS.clear()
    store.GLOBAL_EVENTS.clear()
    store.restore_webhook_seen([])
    persistence.load_all()
    check(store.DEALS.get("pact-test-turso-1", {}).get("state")
          == "released", "deal survives a Turso round trip",
          store.DEALS.get("pact-test-turso-1"))
    check(store.DEALS.get("pact-test-turso-1", {}).get("price_cents")
          == 22217, "integer cents survive the round trip",
          store.DEALS.get("pact-test-turso-1"))
    check(any(e.get("type") == "deal_created" for e in store.GLOBAL_EVENTS),
          "ledger event survives the round trip",
          store.GLOBAL_EVENTS)
    seen = store.snapshot_webhook_seen()
    check(any(row[0] == "evt-turso-test-1" for row in seen),
          "webhook seen id survives the round trip", seen)

    print("TEST 4 restart against the same Turso file loads the same deal")
    store.DEALS.clear()
    store.GLOBAL_EVENTS.clear()
    store.restore_webhook_seen([])
    persistence._active_path = None
    persistence.load_all()
    check(store.DEALS.get("pact-test-turso-1", {}).get("state")
          == "released", "deal loads back after a fresh init",
          store.DEALS.get("pact-test-turso-1"))

    reset_env()
    print()
    if failures:
        print(f"FAILED: {len(failures)} checks: {failures}")
        sys.exit(1)
    print("ALL TURSO PERSISTENCE CHECKS PASSED")


if __name__ == "__main__":
    main()
