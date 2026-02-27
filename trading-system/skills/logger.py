from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def get_logger(logs_dir: str, name: str = "orchestrator"):
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    file_handler = logging.FileHandler(Path(logs_dir) / f"{name}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def append_event(db_path: str, event_type: str, payload):
    timestamp = datetime.now(timezone.utc).isoformat()
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (event_type, payload, created_at)
            VALUES (?, ?, ?)
            """,
            (event_type, serialized, timestamp),
        )
        conn.commit()
    finally:
        conn.close()

