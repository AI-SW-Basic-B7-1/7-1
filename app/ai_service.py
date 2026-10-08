"""Gemini API를 이용한 AI 응답 생성 모듈."""

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.logger import chat_logger

from app.pet_service import AREA_CODES, CONTENT_TYPE_IDS, matches_region_name

class AITimeoutError(Exception):
    """AI API가 제한 시간 안에 응답하지 못한 경우의 예외."""


class AIServiceError(Exception):
    """AI API 호출에 실패한 경우의 예외."""


PARAMETER_SYSTEM_INSTRUCTION = """
너는 반려동물 동반여행 검색 조건을 분석하는 역할이다.

사용자의 현재 질문과 이전 대화 기록을 보고
KorPetTourService2 API 검색에 필요한 목적지 조건을 추출한다.

반드시 아래 JSON 형식으로만 응답한다.

{
  "areaCode": 숫자 또는 null,
  "contentTypeId": 숫자 또는 null,
  "sigunguName": 목적지 시군구 이름 문자열 또는 null
}

[지역 코드]
서울=1
인천=2
대전=3
대구=4
광주=5
부산=6
울산=7
세종=8
경기도=31
강원도=32
충청북도=33
충청남도=34
경상북도=35
경상남도=36
전라북도=37
전라남도=38
제주도=39

[관광 타입]
관광지=12
문화시설=14
행사/공연/축제=15
레포츠=28
숙박=32
쇼핑=38
음식점=39

사용자가 강릉, 춘천처럼 특정 시/군을 말하면
해당 광역 지역으로 판단한다.
예: 강릉 → 강원도 → 32

출발지와 목적지를 구분하고 검색 지역에는 목적지만 사용한다.
예: 서울에서 강릉 식당 추천 → areaCode=32, contentTypeId=39, sigunguName="강릉"
목적지 시군구가 명확하면 sigunguName에 그 이름을 넣는다.
현재 질문이나 이전 사용자 질문에 명시된 목적지 시군구만 사용하고 장소명에서 시군구를 추정하지 않는다.
광역 지역만 지정되거나 시군구가 여러 개이면 sigunguName은 null이다.
현재 질문에 광역 지역이 새로 명시되면 이전 시군구를 재사용하지 않는다.
"다른 식당 추천"처럼 같은 여행의 후속 질문일 때만 이전 목적지 시군구를 이어서 사용한다.
출발지만 확인되고 목적지가 불명확하면 areaCode와 sigunguName은 null이다.
현재 목적지가 확인되면 이전 대화의 지역으로 덮어쓰지 않는다.

현재 질문에 지역이나 관광 타입이 직접 나오지 않더라도
이전 대화에서 명확하게 확인할 수 있다면 그 값을 사용한다.

대화 기록으로도 판단할 수 없거나 애매하면 null을 사용한다.

다른 설명이나 Markdown은 절대 출력하지 않는다.
""".strip()


NO_PARAMETER_SYSTEM_INSTRUCTION = """
너는 KorPetTourService2 기반 반려동물 여행 안내 챗봇이다.

현재 질문을 KorPetTourService2로 조회하기 위한
지역 또는 관광 타입 정보를 충분히 확인하지 못했다.

절대로 관광 정보를 추측하거나 지어내지 않는다.

사용자의 현재 질문과 이전 대화를 고려하여
조회에 필요한 지역과 관광 타입을 자연스럽게 다시 질문한다.

예:
"어느 지역인지와 관광지, 숙박, 음식점 중 어떤 장소를 찾으시는지 알려주세요."

반드시 한국어로 답한다.
최종 답변은 기존 항목 형식을 유지하고, 굵게 표시하는 Markdown 장식은 사용하지 않는다.
""".strip()


NO_RESULT_SYSTEM_INSTRUCTION = """
너는 KorPetTourService2 기반 반려동물 여행 안내 챗봇이다.

KorPetTourService2에 실제로 조회했지만
조건에 맞는 데이터가 존재하지 않았다.

절대로 다른 여행 데이터나 일반적인 지식을 이용해서
장소를 추천하지 않는다.

사용자에게 해당 조건의 데이터를 찾지 못했다고
자연스럽게 알려준다.

반드시 한국어로 답한다.
최종 답변은 기존 답변 형식을 유지하고, 굵게 표시하는 Markdown 장식은 사용하지 않는다.
""".strip()


DATA_SYSTEM_INSTRUCTION = """
너는 KorPetTourService2 기반 반려동물 여행 안내 챗봇이다.

아래 제공된 데이터만 근거로 답변한다.

중요 규칙:
1. 제공된 데이터에 없는 장소나 정보를 만들지 않는다.
2. 반려동물 동반 가능 여부를 임의로 판단하지 않는다.
3. 데이터에 값이 없으면 "정보가 확인되지 않습니다"라고 안내한다.
4. 일반적인 인터넷 지식이나 학습된 관광 정보를 추가하지 않는다.
5. 사용자가 질문한 내용을 최근 대화 문맥과 연결해서 자연스럽게 답한다.
6. 장소명과 주소는 제공된 데이터의 값을 사용한다.
7. 여러 장소가 있다면 각각 구분해서 보여준다.
8. 반드시 한국어로 답한다.
9. 동반 가능 동물, 동반 시 필요사항, 기타 동반 정보를 함께 읽고 조건을 안내한다.
10. 상세 조건이 없으면 시설에 확인이 필요하다고 안내하며 동반 불가로 단정하지 않는다.
11. 동반유형코드의 의미를 추측하지 않는다. 시설이나 비치 품목만으로 동반 가능을 확정하지 않는다.
12. 소개정보와 반려동물 상세 조건이 상충하면 상충 사실을 알리고 시설 확인을 권한다.
13. 기존 항목 형식과 답변 내용은 유지하고, 굵게 표시하는 Markdown 장식은 사용하지 않는다.
14. 사용자가 지정한 지역·동반 조건과 다르거나 확인되지 않은 장소를 그 조건에 맞는 것으로 단정하지 않는다.
""".strip()


async def _generate_gemini_text(
    contents: list[dict[str, Any]],
    system_instruction: str | None = None,
) -> str:
    """Gemini generateContent API를 실제로 호출합니다."""

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{settings.GEMINI_MODEL}:generateContent"
    )

    headers = {
        "x-goog-api-key": settings.GEMINI_API_KEY,
        "Content-Type": "application/json",
    }

    request_body: dict[str, Any] = {
        "contents": contents,
    }

    if system_instruction:
        request_body["systemInstruction"] = {
            "parts": [
                {
                    "text": system_instruction,
                }
            ]
        }

    try:
        async with httpx.AsyncClient(
            timeout=settings.AI_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()

    except httpx.TimeoutException as exc:
        raise AITimeoutError(
            "Gemini API 요청이 시간 초과되었습니다."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"Gemini API 오류: HTTP {exc.response.status_code}"
        ) from exc

    except httpx.RequestError as exc:
        raise AIServiceError(
            "Gemini API 네트워크 요청에 실패했습니다."
        ) from exc

    try:
        data = response.json()

        answer = data["candidates"][0]["content"]["parts"][0]["text"]

    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIServiceError(
            "Gemini 응답 형식이 올바르지 않습니다."
        ) from exc

    if not isinstance(answer, str):
        raise AIServiceError(
            "Gemini 응답 형식이 올바르지 않습니다."
        )

    if not answer.strip():
        raise AIServiceError(
            "Gemini 응답이 비어 있습니다."
        )

    usage = data.get("usageMetadata", {})
    if isinstance(usage, dict):
        counts = [usage.get(name, 0) for name in (
            "promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount",
        )]
        if (
            "promptTokenCount" in usage and "candidatesTokenCount" in usage
            and all(type(value) is int and value >= 0 for value in counts)
        ):
            chat_logger.info(
                "ai_token_usage model=%s phase=%s prompt_tokens=%s output_tokens=%s thoughts_tokens=%s",
                settings.GEMINI_MODEL,
                "parameters" if system_instruction == PARAMETER_SYSTEM_INSTRUCTION else "answer",
                *counts,
            )

    return answer.strip()


def _build_history_contents(
    history: list,
) -> list[dict[str, Any]]:
    """기존 대화 이력을 Gemini contents 형식으로 변환합니다."""

    contents = []

    for chat in history:
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": chat["question"],
                    }
                ],
            }
        )

        contents.append(
            {
                "role": "model",
                "parts": [
                    {
                        "text": chat["response"],
                    }
                ],
            }
        )

    return contents


async def generate_chat_response(
    question: str,
    history: list,
    system_instruction: str | None = None,
    extra_context: str | None = None,
) -> str:
    """사용자 질문에 대한 최종 Gemini 응답을 생성합니다."""

    contents = _build_history_contents(history)

    if extra_context:
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "[KorPetTourService2 조회 결과]\n"
                            f"{extra_context}"
                        ),
                    }
                ],
            }
        )

    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": question,
                }
            ],
        }
    )

    return await _generate_gemini_text(
        contents=contents,
        system_instruction=system_instruction,
    )


async def extract_pet_tour_parameters(
    question: str,
    history: list,
) -> dict[str, int | str | None]:
    """
    현재 질문의 명확한 지역·유형은 직접 판별하고 나머지는 Gemini에 맡깁니다.
    """

    local_parameters = _extract_local_parameters(question)
    if local_parameters is not None:
        return local_parameters

    contents = _build_history_contents(history)

    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": question,
                }
            ],
        }
    )

    raw_answer = await _generate_gemini_text(
        contents=contents,
        system_instruction=PARAMETER_SYSTEM_INSTRUCTION,
    )

    cleaned = raw_answer.strip()

    # 혹시 Gemini가 ```json ... ``` 형태로 반환하는 경우 제거
    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1

        json_text = cleaned[start:end]

        result = json.loads(json_text)

    except (ValueError, json.JSONDecodeError) as exc:
        raise AIServiceError(
            "Gemini의 검색 조건 분석 결과를 읽을 수 없습니다."
        ) from exc

    if not isinstance(result, dict):
        raise AIServiceError(
            "Gemini의 검색 조건 분석 결과 형식이 올바르지 않습니다."
        )

    area_code = result.get("areaCode")
    content_type_id = result.get("contentTypeId")

    try:
        if area_code is not None:
            if isinstance(area_code, bool):
                raise ValueError

            area_code = int(area_code)

        if content_type_id is not None:
            if isinstance(content_type_id, bool):
                raise ValueError

            content_type_id = int(content_type_id)

    except (TypeError, ValueError) as exc:
        raise AIServiceError(
            "Gemini가 반환한 검색 조건 형식이 올바르지 않습니다."
        ) from exc


    if (
        area_code is not None
        and area_code not in AREA_CODES.values()
    ):
        raise AIServiceError(
            f"허용되지 않는 areaCode입니다: {area_code}"
        )

    if (
        content_type_id is not None
        and content_type_id not in CONTENT_TYPE_IDS.values()
    ):
        raise AIServiceError(
            "허용되지 않는 contentTypeId입니다: "
            f"{content_type_id}"
        )

    parameters: dict[str, int | str | None] = {
        "areaCode": area_code,
        "contentTypeId": content_type_id,
    }
    sigungu_name = result.get("sigunguName")
    if sigungu_name is not None:
        if (
            not isinstance(sigungu_name, str)
            or not 2 <= len(sigungu_name.strip()) <= 20
            or not re.fullmatch(r"[가-힣]+(?: [가-힣]+)?", sigungu_name.strip())
        ):
            raise AIServiceError("Gemini가 반환한 시군구 이름 형식이 올바르지 않습니다.")
        if area_code is None:
            raise AIServiceError("시군구 검색에는 목적지 지역 코드가 필요합니다.")
        parameters["sigunguName"] = sigungu_name.strip()
    return parameters


def _extract_local_parameters(question: str) -> dict[str, int] | None:
    """광역 지역과 단일 관광 유형이 모두 명시된 경우에만 AI 분석을 생략합니다."""
    regions = {code for name, code in AREA_CODES.items() if matches_region_name(question, name)}
    aliases = {**CONTENT_TYPE_IDS, "식당": 39, "카페": 39, "숙소": 32, "호텔": 32}
    types = {code for name, code in aliases.items() if matches_region_name(question, name)}
    # 모르는 지명이나 이동 표현이 있으면 출발지를 목적지로 추측하지 않습니다.
    simple_words = (
        *AREA_CODES, *aliases,
        "에서", "에", "의", "으로", "로", "과", "와", "은", "는", "을", "를",
        "추천해주세요", "추천해줘", "추천", "알려주세요", "알려줘", "찾아줘", "찾아주세요",
        "좀", "부탁해", "갈", "만한", "좋은", "곳", "장소",
        "반려동물", "반려견", "강아지", "함께", "동반", "가능한",
    )
    simple_question = re.fullmatch(
        r"(?:\s|[?,.!]|" + "|".join(re.escape(word) for word in simple_words) + r")+",
        question,
    )
    mentioned_regions = {code for name, code in AREA_CODES.items() if name in question}
    if simple_question and len(regions) == 1 and regions == mentioned_regions and len(types) == 1:
        return {"areaCode": regions.pop(), "contentTypeId": types.pop()}
    return None
