from __future__ import annotations

from typing import Any, Iterable


def index_matches_scope(
    index: dict[str, Any],
    *,
    brand_id: str | None = None,
    account_id: str | None = None,
) -> bool:
    scope = index.get("scope", {})

    if brand_id is not None and scope.get("brand_id") != brand_id:
        return False

    if account_id is not None:
        account_ids = scope.get("account_ids") or []
        if account_ids and account_id not in account_ids:
            return False

    return True


def filter_indexes_by_scope(
    indexes: Iterable[dict[str, Any]],
    *,
    brand_id: str | None = None,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        index
        for index in indexes
        if index_matches_scope(index, brand_id=brand_id, account_id=account_id)
    ]
