from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_index(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def save_index(index: dict[str, Any], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as file:
        json.dump(index, file, ensure_ascii=False, indent=2)
        file.write("\n")


def append_user_correction(
    index: dict[str, Any],
    *,
    category: str,
    evidence: dict[str, Any],
    correction_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    updated = deepcopy(index)
    updated.setdefault("user_corrections", [])
    updated["user_corrections"].append(
        {
            "id": correction_id or f"correction-{uuid.uuid4().hex}",
            "category": category,
            "evidence": evidence,
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        }
    )
    return updated
