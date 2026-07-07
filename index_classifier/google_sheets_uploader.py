from __future__ import annotations

import base64
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def upload_csv_to_google_sheet(
    *,
    csv_path: str | Path,
    spreadsheet: str,
    sheet_name: str,
    credentials_path: str | Path,
    mode: str = "replace",
) -> dict[str, Any]:
    spreadsheet_id = parse_spreadsheet_id(spreadsheet)
    if not spreadsheet_id:
        raise ValueError("구글 스프레드시트 URL 또는 ID를 입력해 주세요.")
    if not sheet_name:
        raise ValueError("업로드할 시트명을 입력해 주세요.")

    values = _load_csv_values(csv_path)
    if not values:
        raise ValueError("업로드할 CSV 데이터가 없습니다.")

    token = _service_account_access_token(credentials_path)
    _ensure_sheet(spreadsheet_id, sheet_name, token)
    range_name = f"{_quote_sheet_name(sheet_name)}!A1"

    normalized_mode = str(mode or "replace").casefold()
    if normalized_mode == "append":
        response = _request_json(
            "POST",
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{urllib.parse.quote(range_name, safe='')}:"
            "append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS",
            token,
            {"values": values},
        )
    else:
        _request_json(
            "POST",
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{urllib.parse.quote(_quote_sheet_name(sheet_name), safe='')}:clear",
            token,
            {},
        )
        response = _request_json(
            "PUT",
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{urllib.parse.quote(range_name, safe='')}?valueInputOption=USER_ENTERED",
            token,
            {"values": values},
        )
    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "mode": "append" if normalized_mode == "append" else "replace",
        "rows": len(values),
        "columns": max((len(row) for row in values), default=0),
        "response": response,
    }


def parse_spreadsheet_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "/spreadsheets/d/" in text:
        return text.split("/spreadsheets/d/", 1)[1].split("/", 1)[0]
    if "docs.google.com" in text and "/d/" in text:
        return text.split("/d/", 1)[1].split("/", 1)[0]
    return text


def _load_csv_values(path: str | Path) -> list[list[Any]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        return [row for row in csv.reader(file)]


def _service_account_access_token(credentials_path: str | Path) -> str:
    credentials = json.loads(Path(credentials_path).read_text(encoding="utf-8-sig"))
    token_uri = credentials.get("token_uri") or "https://oauth2.googleapis.com/token"
    now = int(time.time())
    claims = {
        "iss": credentials["client_email"],
        "scope": SHEETS_SCOPE,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = _encode_jwt({"alg": "RS256", "typ": "JWT"}, claims, credentials["private_key"])
    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Google token response missing access_token: {payload}")
    return str(token)


def _encode_jwt(header: dict[str, Any], claims: dict[str, Any], private_key_pem: str) -> str:
    header_part = _base64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    claims_part = _base64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{claims_part}".encode("ascii")
    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_part}.{claims_part}.{_base64url(signature)}"


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _ensure_sheet(spreadsheet_id: str, sheet_name: str, token: str) -> None:
    metadata = _request_json(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields=sheets.properties.title",
        token,
    )
    titles = {
        str(sheet.get("properties", {}).get("title") or "")
        for sheet in metadata.get("sheets", [])
        if isinstance(sheet, dict)
    }
    if sheet_name in titles:
        return
    _request_json(
        "POST",
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
        token,
        {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
    )


def _request_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read().decode("utf-8")
    return json.loads(content) if content else {}


def _quote_sheet_name(sheet_name: str) -> str:
    return "'" + str(sheet_name).replace("'", "''") + "'"
