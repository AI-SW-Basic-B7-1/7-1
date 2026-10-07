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
    "경기도": 31,
    "강원도": 32,
    "충청북도": 33,
    "충청남도": 34,
    "경상북도": 35,
    "경상남도": 36,
    "전라북도": 37,
    "전라남도": 38,
    "제주도": 39,
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

# 소개정보의 필드명은 관광 유형별로 다릅니다.
INTRO_FIELDS = {
    "12": ("infocenter", "usetime", "restdate", "parking", "chkpet"),
    "14": ("infocenterculture", "usetimeculture", "restdateculture", "parkingculture", "chkpetculture"),
    "15": ("sponsor1tel", "playtime", "", "", ""),
    "28": ("infocenterleports", "usetimeleports", "restdateleports", "parkingleports", "chkpetleports"),
    "32": ("infocenterlodging", "checkintime", "", "parkinglodging", ""),
    "38": ("infocentershopping", "opentime", "restdateshopping", "parkingshopping", "chkpetshopping"),
    "39": ("infocenterfood", "opentimefood", "restdatefood", "parkingfood", ""),
}
PET_FIELDS = {
    "acmpyPsblCpam": "동반 가능 동물",
    "acmpyNeedMtr": "동반 시 필요사항",
    "etcAcmpyInfo": "기타 동반 정보",
    "relaAcdntRiskMtr": "관련 사고 대비사항",
    "relaPosesFclty": "관련 구비 시설",
    "relaFrnshPrdlst": "관련 비치 품목",
    "relaPurcPrdlst": "관련 구매 품목",
    "relaRntlPrdlst": "관련 렌탈 품목",
    "acmpyTypeCd": "동반유형코드(원문, 의미 추정 금지)",
}


class PetTourAPITimeoutError(Exception):
    """KorPetTourService2 응답이 제한 시간 안에 오지 않은 경우."""


class PetTourServiceError(Exception):
    """KorPetTourService2 호출에 실패한 경우."""


def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """공공데이터 API 응답에서 item 목록을 추출합니다."""

    response = data.get("response", {})
    body = response.get("body")

    if not isinstance(body, dict):
        raise PetTourServiceError("관광정보 응답 본문 형식이 올바르지 않습니다.")

    items = body.get("items", {})

    # 조회 결과가 없으면 items가 빈 문자열로 내려올 수 있음
    if not items:
        return []

    if not isinstance(items, dict):
        raise PetTourServiceError("관광정보 목록 형식이 올바르지 않습니다.")

    item = items.get("item", [])

    if not item:
        return []

    if isinstance(item, dict):
        return [item]

    if isinstance(item, list) and all(isinstance(entry, dict) for entry in item):
        return item

    raise PetTourServiceError("관광정보 항목 형식이 올바르지 않습니다.")


async def _request(
    endpoint: str,
    params: dict[str, Any],
    *,
    allow_no_data: bool = False,
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

    if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
        raise PetTourServiceError("관광정보 응답 구조가 올바르지 않습니다.")
    header = data["response"].get("header")
    if not isinstance(header, dict) or "resultCode" not in header:
        raise PetTourServiceError("관광정보 응답 상태가 누락되었습니다.")
    result_code = str(header["resultCode"])
    result_message = header.get("resultMsg", "")

    if allow_no_data and result_code == "03":
        return {"response": {"body": {"items": ""}}}

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


async def detail_pet_tour(content_id: str) -> dict[str, Any]:
    """동반 조건을 조회하며 정상적인 정보 부재만 빈 딕셔너리로 반환합니다."""
    data = await _request(
        f"{BASE_URL}/detailPetTour2",
        {"contentId": content_id},
        allow_no_data=True,
    )
    items = _extract_items(data)
    return items[0] if items else {}


async def _get_place_details(
    content_id: str, content_type: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """장소별 소개정보와 동반 조건을 조회합니다."""
    intro = await detail_intro(content_id, content_type)
    pet = await detail_pet_tour(content_id)
    return intro, pet


async def get_pet_tour_data(
    area_code: int,
    content_type_id: int,
) -> list[dict[str, Any]]:
    """
    지역별 목록에 소개정보와 반려동물 상세정보를 연결합니다.
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
            _get_place_details(
                str(content_id),
                str(content_type),
            )
        )

    if not tasks:
        return []

    detail_results = await asyncio.gather(
        *tasks,
    )

    results = []

    for base_item, (detail_result, pet_result) in zip(
        valid_items,
        detail_results,
    ):

        if detail_result is None:
            raise PetTourServiceError(
                "KorPetTourService2 상세정보를 조회하지 못했습니다."
            )

        results.append(
            {
                "contentid": base_item.get("contentid"),
                "contenttypeid": base_item.get("contenttypeid"),
                "title": base_item.get("title"),
                "addr1": base_item.get("addr1"),
                "addr2": base_item.get("addr2"),
                "detail": detail_result,
                "pet_detail": pet_result,
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
        pet = result.get("pet_detail", {})
        content_type = str(result.get("contenttypeid", ""))
        fields = INTRO_FIELDS.get(content_type, ("",) * 5)
        labels = ("문의 및 안내", "입실 시간" if content_type == "32" else "이용 시간", "쉬는 날", "주차 정보", "소개정보의 동반 안내")
        intro_lines = [
            f"{label}: {detail[field]}"
            for label, field in zip(labels, fields)
            if field and str(detail.get(field) or "").strip()
        ]
        if content_type == "12":
            for field, label in {
                "opendate": "개장일", "expguide": "체험 안내",
                "expagerange": "체험 가능 연령", "accomcount": "수용 인원",
                "useseason": "이용 시기", "chkbabycarriage": "유모차 대여",
                "chkcreditcard": "신용카드",
            }.items():
                if str(detail.get(field) or "").strip():
                    intro_lines.append(f"{label}: {detail[field]}")
        pet_lines = [
            f"{label}: {pet[field]}"
            for field, label in PET_FIELDS.items()
            if str(pet.get(field) or "").strip()
        ]
        if not pet_lines:
            pet_lines = ["반려동물 상세 조건: 제공된 정보 없음. 시설에 확인 필요(동반 불가를 뜻하지 않음)."]

        lines.append(
            f"""
[관광정보 {index}]
콘텐츠 ID: {result.get("contentid", "")}
관광타입 ID: {result.get("contenttypeid", "")}
장소명: {result.get("title", "")}
주소: {result.get("addr1", "")} {result.get("addr2", "")}

{chr(10).join(intro_lines)}
{chr(10).join(pet_lines)}
""".strip()
        )

    return "\n\n".join(lines)
