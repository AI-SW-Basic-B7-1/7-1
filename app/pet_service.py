"""한국관광공사 KorPetTourService2 연동 모듈."""

import asyncio
from typing import Any

import httpx

from app.config import settings


BASE_URL = (
    "https://apis.data.go.kr/B551011/KorPetTourService2"
)

AREA_CODES = {
    "서울": 1,
    "인천": 2,
    "대전": 3,
    "대구": 4,
    "광주": 5,
    "부산": 6,
    "울산": 7,
    "세종": 8,
    "경기도": 9,
    "강원도": 10,
    "충청북도": 11,
    "충청남도": 12,
    "경상북도": 13,
    "경상남도": 14,
    "전라북도": 15,
    "전라남도": 16,
    "제주도": 17,
}

CONTENT_TYPE_IDS = {
    "관광지": 12,
    "문화시설": 14,
    "행사": 15,
    "공연": 15,
    "축제": 15,
    "레포츠": 28,
    "숙박": 32,
    "쇼핑": 38,
    "음식점": 39,
}


class PetTourAPITimeoutError(Exception):
    """KorPetTourService2 응답이 제한 시간 안에 오지 않은 경우."""


class PetTourServiceError(Exception):
    """KorPetTourService2 호출에 실패한 경우."""


def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """공공데이터 API 응답에서 item 목록을 추출합니다."""

    response = data.get("response", {})
    body = response.get("body", {})

    if not isinstance(body, dict):
        return []

    items = body.get("items", {})

    # 조회 결과가 없으면 items가 빈 문자열로 내려올 수 있음
    if not items:
        return []

    if not isinstance(items, dict):
        return []

    item = items.get("item", [])

    if not item:
        return []

    if isinstance(item, dict):
        return [item]

    if isinstance(item, list):
        return item

    return []


async def _request(
    endpoint: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """KorPetTourService2 API를 비동기로 호출합니다."""

    if not settings.KOR_PET_TOUR_SERVICE_KEY:
        raise PetTourServiceError(
            "KOR_PET_TOUR_SERVICE_KEY가 설정되지 않았습니다."
        )

    request_params = {
        "serviceKey": settings.KOR_PET_TOUR_SERVICE_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "MobileOS": "ETC",
        "MobileApp": "AppTest",
        "_type": "json",
        **params,
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.PET_TOUR_API_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(
                endpoint,
                params=request_params,
            )
            response.raise_for_status()

    except httpx.TimeoutException:
        raise PetTourAPITimeoutError(
            "KorPetTourService2 API 요청이 시간 초과되었습니다."
        ) from None

    except httpx.HTTPStatusError as exc:
        raise PetTourServiceError(
            "KorPetTourService2 API HTTP 오류: "
            f"{exc.response.status_code}"
        ) from None

    except httpx.RequestError:
        raise PetTourServiceError(
            "KorPetTourService2 API 네트워크 요청에 실패했습니다."
        ) from None

    try:
        data = response.json()
    except ValueError as exc:
        raise PetTourServiceError(
            "KorPetTourService2 응답 형식이 올바르지 않습니다."
        ) from exc

    header = data.get("response", {}).get("header", {})
    result_code = str(header.get("resultCode", "0000"))
    result_message = header.get("resultMsg", "")

    if result_code not in {"0000", "00"}:
        raise PetTourServiceError(
            "KorPetTourService2 API 오류: "
            f"{result_code} {result_message}"
        )

    return data


async def area_based_list(
    area_code: int,
    content_type_id: int,
) -> list[dict[str, Any]]:
    """지역 및 관광타입 기준으로 관광정보를 조회합니다."""

    if area_code not in AREA_CODES.values():
        raise ValueError(f"지원하지 않는 areaCode입니다: {area_code}")

    if content_type_id not in CONTENT_TYPE_IDS.values():
        raise ValueError(
            "지원하지 않는 contentTypeId입니다: "
            f"{content_type_id}"
        )

    endpoint = f"{BASE_URL}/areaBasedList2"

    data = await _request(
        endpoint,
        {
            "arrange": "C",
            "areaCode": area_code,
            "contentTypeId": content_type_id,
        },
    )

    return _extract_items(data)


async def detail_intro(
    content_id: str,
    content_type_id: str,
) -> dict[str, Any] | None:
    """특정 관광 콘텐츠의 소개정보를 조회합니다."""

    endpoint = f"{BASE_URL}/detailIntro2"

    data = await _request(
        endpoint,
        {
            "contentId": content_id,
            "contentTypeId": content_type_id,
        },
    )

    items = _extract_items(data)

    if not items:
        return None

    return items[0]


async def get_pet_tour_data(
    area_code: int,
    content_type_id: int,
) -> list[dict[str, Any]]:
    """
    areaBasedList2 → detailIntro2 순서로
    PetTour 데이터를 조회합니다.
    """

    area_items = await area_based_list(
        area_code,
        content_type_id,
    )

    if not area_items:
        return []

    tasks = []

    valid_items = []

    for item in area_items:
        content_id = item.get("contentid")
        content_type = item.get("contenttypeid")

        if not content_id or not content_type:
            continue

        valid_items.append(item)

        tasks.append(
            detail_intro(
                str(content_id),
                str(content_type),
            )
        )

    if not tasks:
        return []

    detail_results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    results = []

    for base_item, detail_result in zip(
        valid_items,
        detail_results,
    ):
        if isinstance(detail_result, Exception):
            continue

        if detail_result is None:
            continue

        results.append(
            {
                "contentid": base_item.get("contentid"),
                "contenttypeid": base_item.get("contenttypeid"),
                "title": base_item.get("title"),
                "addr1": base_item.get("addr1"),
                "addr2": base_item.get("addr2"),
                "detail": detail_result,
            }
        )

    return results


def build_pet_tour_context(
    results: list[dict[str, Any]],
) -> str:
    """Open API 결과를 Gemini에 전달할 문자열로 변환합니다."""

    if not results:
        return "KorPetTourService2 조회 결과가 없습니다."

    lines = []

    for index, result in enumerate(results, start=1):
        detail = result.get("detail", {})

        lines.append(
            f"""
[관광정보 {index}]
콘텐츠 ID: {result.get("contentid", "")}
관광타입 ID: {result.get("contenttypeid", "")}
장소명: {result.get("title", "")}
주소: {result.get("addr1", "")} {result.get("addr2", "")}

문의 및 안내: {detail.get("infocenter", "")}
개장일: {detail.get("opendate", "")}
쉬는 날: {detail.get("restdate", "")}
체험 안내: {detail.get("expguide", "")}
체험 가능 연령: {detail.get("expagerange", "")}
수용 인원: {detail.get("accomcount", "")}
이용 시기: {detail.get("useseason", "")}
이용 시간: {detail.get("usetime", "")}
주차 정보: {detail.get("parking", "")}
유모차 대여: {detail.get("chkbabycarriage", "")}
반려동물 동반: {detail.get("chkpet", "")}
신용카드: {detail.get("chkcreditcard", "")}
""".strip()
        )

    return "\n\n".join(lines)