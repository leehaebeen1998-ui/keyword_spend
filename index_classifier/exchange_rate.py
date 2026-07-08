"""USD -> KRW 환율 조회.

버튼을 누른 시점(오늘) 기준 환율을 무료 공개 API로 조회한다.
API 조회가 실패하면(오프라인, 서비스 장애 등) 호출부에서 사용자에게
직접 환율을 입력받는 수동 입력 흐름으로 넘어갈 수 있도록 명확한
예외를 던진다. 이 모듈 자체는 수동 입력 UI를 갖지 않는다(GUI 책임).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

# 키 없이 쓸 수 있는 무료 환율 API. ECB 기준 환율을 매 영업일 갱신한다.
_FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest?from=USD&to=KRW"
# 1차 API가 막혀 있을 때를 대비한 대체 API(키 불필요).
_FALLBACK_URL = "https://open.er-api.com/v6/latest/USD"

_REQUEST_TIMEOUT_SEC = 10


class ExchangeRateError(RuntimeError):
    """환율 조회에 실패했을 때 발생한다."""


def fetch_usd_krw_rate(*, timeout: float = _REQUEST_TIMEOUT_SEC) -> float:
    """오늘 기준 USD -> KRW 환율을 조회한다.

    Frankfurter API를 먼저 시도하고, 실패하면 open.er-api.com으로
    한 번 더 시도한다. 둘 다 실패하면 ExchangeRateError를 던진다.
    """
    errors: list[str] = []

    try:
        return _fetch_from_frankfurter(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 원인 무관하게 다음 소스로 폴백
        errors.append(f"frankfurter: {exc}")

    try:
        return _fetch_from_er_api(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"open.er-api: {exc}")

    raise ExchangeRateError(
        "환율 자동 조회에 실패했습니다. 인터넷 연결을 확인하거나 환율을 직접 입력해 주세요.\n"
        + "\n".join(errors)
    )


def _fetch_from_frankfurter(*, timeout: float) -> float:
    payload = _get_json(_FRANKFURTER_URL, timeout=timeout)
    rate = payload.get("rates", {}).get("KRW")
    return _validate_rate(rate)


def _fetch_from_er_api(*, timeout: float) -> float:
    payload = _get_json(_FALLBACK_URL, timeout=timeout)
    rate = payload.get("rates", {}).get("KRW")
    return _validate_rate(rate)


def _get_json(url: str, *, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "keyword-spend-processor/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _validate_rate(rate: object) -> float:
    value = float(rate)  # type: ignore[arg-type]
    if value <= 0:
        raise ValueError(f"invalid rate value: {rate}")
    return value


# KRW로 취급해 변환을 건너뛸 통화 코드 표기(공백/대소문자 무시하고 비교).
KRW_CODES = {"KRW", "원", "₩", ""}


def needs_conversion(currency_code: str | None) -> bool:
    """raw 파일의 통화 코드가 KRW가 아니어서 환율 변환이 필요한지 판단한다."""
    normalized = str(currency_code or "").strip().upper()
    return normalized not in KRW_CODES
