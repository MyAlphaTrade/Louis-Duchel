"""
AlphaTrade Global — local_store
================================

Generic SQLite-backed entity store that replaces the Base44 cloud
database. It deliberately mirrors the Base44 SDK's flexible-schema
semantics (`entities.<Type>.list/filter/get/create/update/delete`)
so the existing frontend code needs no per-entity migration: every
entity type is stored as a JSON blob in a single `entities` table.

Supported filter operators (matching what the frontend actually
uses, plus the common Mongo-style set for forward compatibility):
  - plain equality:      { field: value }
  - $gte, $lte, $gt, $lt: { field: { "$gte": value } }
  - $ne, $in:             { field: { "$ne": value } } / { "$in": [...] }
  - $or:                  { "$or": [ {..}, {..} ] }
"""

import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_SCRIPT_DIR, "alphatg_local.db")

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("""
    CREATE TABLE IF NOT EXISTS entities (
        entity_type TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        created_date TEXT NOT NULL,
        updated_date TEXT NOT NULL,
        PRIMARY KEY (entity_type, id)
    )
""")
_conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
_conn.commit()


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id():
    return secrets.token_hex(12)


def _row_to_record(row):
    entity_type, entity_id, data_json, created_date, updated_date = row
    record = json.loads(data_json)
    record["id"] = entity_id
    record["created_date"] = created_date
    record["updated_date"] = updated_date
    return record


def _match_one(record, field, cond):
    val = record.get(field)
    if isinstance(cond, dict):
        for op, opval in cond.items():
            if op == "$gte" and not (val is not None and val >= opval):
                return False
            if op == "$lte" and not (val is not None and val <= opval):
                return False
            if op == "$gt" and not (val is not None and val > opval):
                return False
            if op == "$lt" and not (val is not None and val < opval):
                return False
            if op == "$ne" and val == opval:
                return False
            if op == "$in" and val not in (opval or []):
                return False
        return True
    return val == cond


def _matches(record, query):
    for field, cond in (query or {}).items():
        if field == "$or":
            if not any(_matches(record, sub) for sub in cond):
                return False
            continue
        if not _match_one(record, field, cond):
            return False
    return True


def _sort_key(field):
    def key(record):
        val = record.get(field)
        if val is None:
            return (1, "")
        return (0, val)
    return key


def list_entities(entity_type, query=None, sort=None, limit=None):
    with _lock:
        rows = _conn.execute(
            "SELECT entity_type, id, data, created_date, updated_date FROM entities WHERE entity_type = ?",
            (entity_type,),
        ).fetchall()
    records = [_row_to_record(row) for row in rows]

    if query:
        records = [r for r in records if _matches(r, query)]

    if sort:
        field = sort[1:] if sort.startswith("-") else sort
        records.sort(key=_sort_key(field), reverse=sort.startswith("-"))
    else:
        records.sort(key=_sort_key("created_date"), reverse=True)

    if limit:
        records = records[:limit]

    return records


def get_entity(entity_type, entity_id):
    with _lock:
        row = _conn.execute(
            "SELECT entity_type, id, data, created_date, updated_date FROM entities WHERE entity_type = ? AND id = ?",
            (entity_type, entity_id),
        ).fetchone()
    return _row_to_record(row) if row else None


def create_entity(entity_type, data):
    entity_id = _new_id()
    now = _now()
    payload = {k: v for k, v in (data or {}).items() if k not in ("id", "created_date", "updated_date")}
    with _lock:
        _conn.execute(
            "INSERT INTO entities (entity_type, id, data, created_date, updated_date) VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, json.dumps(payload), now, now),
        )
        _conn.commit()
    return get_entity(entity_type, entity_id)


def update_entity(entity_type, entity_id, patch):
    existing = get_entity(entity_type, entity_id)
    if existing is None:
        return None
    merged = {k: v for k, v in existing.items() if k not in ("id", "created_date", "updated_date")}
    merged.update({k: v for k, v in (patch or {}).items() if k not in ("id", "created_date", "updated_date")})
    now = _now()
    with _lock:
        _conn.execute(
            "UPDATE entities SET data = ?, updated_date = ? WHERE entity_type = ? AND id = ?",
            (json.dumps(merged), now, entity_type, entity_id),
        )
        _conn.commit()
    return get_entity(entity_type, entity_id)


def delete_entity(entity_type, entity_id):
    with _lock:
        cur = _conn.execute(
            "DELETE FROM entities WHERE entity_type = ? AND id = ?",
            (entity_type, entity_id),
        )
        _conn.commit()
    return cur.rowcount > 0
