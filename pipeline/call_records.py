"""Retain bounded provider-call provenance outside the public frontend."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from config import redact_secrets, write_json_atomic

_ACTIVE: ContextVar[dict | None] = ContextVar("provider_record", default=None)


def response_data(response) -> dict:
    data = response.json()
    record = _ACTIVE.get()
    if record is not None:
        record["responses"].append(
            {"http_status": getattr(response, "status_code", None), "body": data}
        )
    return data


@contextmanager
def recording(path: Path, metadata: dict):
    record = {**metadata, "started_at": datetime.now(UTC).isoformat(), "responses": []}
    record["_meta"] = {"script": "call_records.py", "timestamp": record["started_at"]}
    token = _ACTIVE.set(record)
    try:
        yield record
    except Exception as error:
        record["error"] = redact_secrets(str(error))
        raise
    finally:
        _ACTIVE.reset(token)
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_json_atomic(
            path, json.loads(redact_secrets(json.dumps(record, ensure_ascii=False)))
        )
