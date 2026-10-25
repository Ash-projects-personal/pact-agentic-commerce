"""SQLite persistence for the Pact store.

The app keeps DEALS, AGENTS, and GLOBAL_EVENTS as the working in-memory
dicts in pact.store (the tests and experiments poke those directly and
their assertions must keep working). This module serializes that working
state to SQLite so a server restart or a Render sleep cycle never wipes a
deal a judge is testing.

Layout: deals(id TEXT PK, data TEXT), agents(id TEXT PK, data TEXT),
global_events(seq INTEGER PK AUTOINCREMENT, data TEXT),
webhook_seen_ids(seq INTEGER PK AUTOINCREMENT, event_id TEXT UNIQUE,
seen_at TEXT, signature_verification TEXT). Deals and agents
are JSON blobs; nested mutations are covered because save_all serializes
the whole working state after every HTTP response.

Database path comes from PACT_DB_PATH, defaulting to data/pact.db under
the project root. Callers that use the store as a library (experiments)
get no persistence; that is fine because experiments are throwaway runs.

Turso (2026-10-24): when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are
set, the same tables live in a Turso cloud database instead of the local
file, through the libsql client, whose API mirrors sqlite3 for every call
this module makes. That is what keeps deals alive on Render: the free
instance spins down after 15 minutes idle and restarts with an empty
ephemeral filesystem, so a local SQLite file is wiped on every restart.
With Turso configured, a restart or redeploy loads the same deals back.
Without those two variables the local SQLite file is used exactly as
before, so local runs and the test suite need no cloud account.
"""

import itertools
import json
import os
import sqlite3
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_db_lock = threading.Lock()
_active_path = None


def _turso_config():
    """Turso connection settings, or None when not configured.

    An explicitly set PACT_DB_PATH always wins, so tests and local
    scratch servers that point at a temp file never touch the cloud
    database by accident.
    """
    if os.environ.get("PACT_DB_PATH", "").strip():
        return None
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if url and token:
        return url, token
    return None


def db_path():
    """Path to the SQLite file, from env or the local default."""
    configured = os.environ.get("PACT_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    return _PROJECT_ROOT / "data" / "pact.db"


def init_db(path=None):
    """Create the directory and tables. Safe to call more than once."""
    global _active_path
    turso = _turso_config()
    if turso is None:
        path = Path(path) if path is not None else db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        # No local file when Turso is configured; the tables live in
        # the cloud database.
        path = None
    conn = _connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS deals "
            "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agents "
            "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS global_events "
            "(seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS webhook_seen_ids "
            "(seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT NOT NULL UNIQUE, seen_at TEXT NOT NULL, "
            "signature_verification TEXT)"
        )
        conn.commit()
    finally:
        conn.close()
    _active_path = path
    return path


def _connect():
    turso = _turso_config()
    if turso is not None:
        try:
            import libsql_experimental as libsql
        except ImportError:
            try:
                import libsql
            except ImportError as exc:
                raise RuntimeError(
                    "TURSO_DATABASE_URL is set but no libsql package is "
                    "installed. Install it from requirements.txt."
                ) from exc
        url, token = turso
        return libsql.connect(url, auth_token=token)
    return sqlite3.connect(str(_active_path if _active_path is not None
                               else db_path()))


def save_all():
    """Serialize the whole working store to SQLite. Errors raise."""
    from . import store  # lazy import: store never imports persistence

    with _db_lock:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM deals")
            cur.executemany(
                "INSERT OR REPLACE INTO deals (id, data) VALUES (?, ?)",
                [(did, json.dumps(deal))
                 for did, deal in store.DEALS.items()],
            )
            cur.execute("DELETE FROM agents")
            cur.executemany(
                "INSERT OR REPLACE INTO agents (id, data) VALUES (?, ?)",
                [(aid, json.dumps(agent))
                 for aid, agent in store.AGENTS.items()],
            )
            cur.execute("DELETE FROM global_events")
            cur.executemany(
                "INSERT INTO global_events (data) VALUES (?)",
                [(json.dumps(entry),)
                 for entry in store.GLOBAL_EVENTS],
            )
            cur.execute("DELETE FROM webhook_seen_ids")
            cur.executemany(
                "INSERT INTO webhook_seen_ids "
                "(event_id, seen_at, signature_verification) "
                "VALUES (?, ?, ?)",
                store.snapshot_webhook_seen(),
            )
            conn.commit()
        finally:
            conn.close()


def load_all():
    """Load persisted state into the working store.

    On a fresh database the in-memory defaults are kept and the deal id
    counter stays at 1. Otherwise deals and global events are replaced
    wholesale, agents are merged (code roster wins, persisted reputation
    and deal counts overlay), and the legacy deal id counter is reseeded
    from the max numeric deal-NNNN id so nothing breaks on old snapshots.
    New deal ids are random pact- ids (queue item W), which never parse
    as integers and are skipped by the seeding loop below.
    """
    from . import store

    init_db()
    with _db_lock:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, data FROM deals")
            deals = {did: json.loads(data) for did, data in cur.fetchall()}
            cur.execute("SELECT id, data FROM agents")
            agents = {aid: json.loads(data) for aid, data in cur.fetchall()}
            cur.execute("SELECT data FROM global_events ORDER BY seq")
            events = [json.loads(data) for (data,) in cur.fetchall()]
            cur.execute(
                "SELECT event_id, seen_at, signature_verification "
                "FROM webhook_seen_ids ORDER BY seq"
            )
            seen_ids = cur.fetchall()
        finally:
            conn.close()

    if deals or agents or events or seen_ids:
        store.DEALS.clear()
        store.DEALS.update(deals)
        # Merge agents, not wholesale replace: the code's agent roster
        # is the base, and the persisted snapshot only overlays the
        # mutable stats (reputation, deals). A wholesale replace drops
        # agents the code added after the snapshot was written, which
        # broke /api/scenarios the first time a scenario was added
        # after deals existed (item R). Persisted-only agents are kept
        # so no history is lost.
        for aid, agent in agents.items():
            if aid in store.AGENTS:
                for key in ("reputation", "deals"):
                    if key in agent:
                        store.AGENTS[aid][key] = agent[key]
            else:
                store.AGENTS[aid] = agent
        store.GLOBAL_EVENTS.clear()
        store.GLOBAL_EVENTS.extend(events)
        # Seen webhook ids load wholesale on their own key: they are
        # orthogonal to deals and agents, so a schema addition here never
        # disturbs the agent-roster merge above (item R lesson).
        store.restore_webhook_seen(seen_ids)
        max_id = 0
        for did in deals:
            try:
                max_id = max(max_id, int(str(did).split("-")[-1]))
            except (ValueError, IndexError):
                continue
        store._deal_counter = itertools.count(max_id + 1)


def probe():
    """A real tiny write/read probe. Raises on any database failure."""
    init_db()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS ready_probe "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        cur.execute(
            "INSERT OR REPLACE INTO ready_probe (key, value) "
            "VALUES ('ping', 'pong')"
        )
        cur.execute("SELECT value FROM ready_probe WHERE key = 'ping'")
        row = cur.fetchone()
        if row is None or row[0] != "pong":
            raise RuntimeError("database probe read back the wrong value")
        conn.commit()
    finally:
        conn.close()
