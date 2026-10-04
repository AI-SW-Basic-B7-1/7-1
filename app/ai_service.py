"""Gemini API를 이용한 AI 응답 생성 모듈."""

import json
import re
from typing import Any

import httpx

from app.config import settings

from app.pet_service import AREA_CODES, CONTENT_TYPE_IDS

class AITimeoutError(Exception):
    """AI API가 제한 시간 안에 응답하지 못한 경우의 예외."""


class AIServiceError(Exception):
    """AI API 호출에 실패한 경우의 예외."""


PARAMETER_SYSTEM_INSTRUCTION = """
너는 반려동물 동반여행 검색 조건을 분석하는 역할이다.

사용자의 현재 질문과 이전 대화 기록을 보고
KorPetTourService2 API 검색에 필요한 두 값을 추출한다.

반드시 아래 JSON 형식으로만 응답한다.

{
  "areaCode": 숫자 또는 null,
  "contentTypeId": 숫자 또는 null
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
경기도=9
강원도=10
충청북도=11
충청남도=12
경상북도=13
경상남도=14
전라북도=15
전라남도=16
제주도=17

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
예: 강릉 → 강원도 → 10

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
) -> dict[str, int | None]:
    """
    Gemini 1차 호출.

    사용자 질문 및 최근 대화에서
    areaCode와 contentTypeId를 추출합니다.
    """

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

    return {
        "areaCode": area_code,
        "contentTypeId": content_type_id,
    }