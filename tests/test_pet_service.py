"""반려동물 상세 조회와 AI 문맥 전달을 외부 통신 없이 검증합니다."""

import httpx
import pytest

from app import pet_service


@pytest.fixture
def anyio_backend():
    """프로젝트의 비동기 실행 환경을 사용합니다."""
    return "asyncio"


@pytest.fixture
def api_stub(monkeypatch):
    """공식 응답 구조의 대역을 제공하고 호출 경로를 수집합니다."""
    calls = []
    pet_service._response_cache.clear()
    responses = {
        "areaBasedList2": [{"contentid": "123", "contenttypeid": "39", "title": "테스트 음식점"}],
        "detailIntro2": [{"infocenterfood": "02-000-0000", "opentimefood": "10:00~18:00"}],
        "detailPetTour2": [{"acmpyPsblCpam": "소형견", "acmpyNeedMtr": "이동장 필수", "etcAcmpyInfo": "테라스만 이용"}],
    }

    def handler(request):
        """엔드포인트별 응답과 오류를 재현합니다."""
        endpoint = request.url.path.rsplit("/", 1)[-1]
        calls.append((endpoint, dict(request.url.params)))
        value = responses[endpoint]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, dict):
            return httpx.Response(200, json=value)
        return httpx.Response(200, json={"response": {
            "header": {"resultCode": "0000"},
            "body": {"items": {"item": value}},
        }})

    client = httpx.AsyncClient
    monkeypatch.setattr(pet_service.settings, "KOR_PET_TOUR_SERVICE_KEY", "test-only-key")
    monkeypatch.setattr(pet_service.httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    return responses, calls


@pytest.mark.anyio
async def test_pet_conditions_reach_context_without_chkpet(api_stub):
    """음식점에 관광지용 필드가 없어도 동반 조건이 전달됩니다."""
    _, calls = api_stub
    results = await pet_service.get_pet_tour_data(1, 39)
    context = pet_service.build_pet_tour_context(results)
    for text in ("소형견", "이동장 필수", "테라스만 이용", "02-000-0000", "10:00~18:00"):
        assert text in context
    assert "제공된 정보 없음" not in context
    assert calls[0][1]["numOfRows"] == "20"
    assert all(params["numOfRows"] == "5" for _, params in calls[1:])
    endpoint, params = calls[-1]
    assert endpoint == "detailPetTour2"
    assert params["contentId"] == "123"
    assert "contentTypeId" not in params


@pytest.mark.anyio
@pytest.mark.parametrize("value", [[], {"response": {"header": {"resultCode": "03"}}}])
async def test_missing_pet_detail_keeps_place(api_stub, value):
    """정상적인 상세 정보 부재는 장소 없음이나 동반 불가로 변환하지 않습니다."""
    responses, _ = api_stub
    responses["detailPetTour2"] = value
    results = await pet_service.get_pet_tour_data(1, 39)
    assert len(results) == 1
    context = pet_service.build_pet_tour_context(results)
    assert "테스트 음식점" in context
    assert "시설에 확인 필요" in context


@pytest.mark.anyio
@pytest.mark.parametrize("value,error", [
    ({"response": {"header": {"resultCode": "30"}}}, pet_service.PetTourServiceError),
    (httpx.ReadTimeout("시간 초과"), pet_service.PetTourAPITimeoutError),
    ({"unexpected": "응답"}, pet_service.PetTourServiceError),
    ({"response": {"header": {"resultCode": "0000"}, "body": {"items": {"item": [42]}}}}, pet_service.PetTourServiceError),
])
async def test_pet_failure_is_not_empty_data(api_stub, value, error):
    """인증·시간 초과·응답 오류를 정보 없음으로 숨기지 않습니다."""
    responses, _ = api_stub
    responses["detailPetTour2"] = value
    with pytest.raises(error):
        await pet_service.get_pet_tour_data(1, 39)


@pytest.mark.anyio
async def test_empty_search_does_not_call_details(api_stub):
    """목록이 비어 있으면 상세 API를 호출하지 않습니다."""
    responses, calls = api_stub
    responses["areaBasedList2"] = []
    assert await pet_service.get_pet_tour_data(6, 12) == []
    assert len(calls) == 1


@pytest.mark.parametrize("kind,field", [("12", "chkpet"), ("14", "chkpetculture"), ("28", "chkpetleports"), ("38", "chkpetshopping")])
def test_intro_pet_fields_by_type(kind, field):
    """관광 유형별 기존 동반 안내와 상세 조건을 모두 보존합니다."""
    context = pet_service.build_pet_tour_context([{
        "contenttypeid": kind, "detail": {field: "불가"},
        "pet_detail": {"acmpyNeedMtr": "시설 문의", "acmpyTypeCd": "1"},
    }])
    assert "소개정보의 동반 안내: 불가" in context
    assert "동반 시 필요사항: 시설 문의" in context
    assert "동반유형코드(원문, 의미 추정 금지): 1" in context


def test_lodging_contact_and_checkin():
    """숙박 문의와 입실 시간을 관광지 필드와 구분합니다."""
    context = pet_service.build_pet_tour_context([{
        "contenttypeid": "32", "detail": {"infocenterlodging": "숙소 문의", "checkintime": "15:00"},
        "pet_detail": {"acmpyPsblCpam": "반려견"},
    }])
    assert "문의 및 안내: 숙소 문의" in context
    assert "입실 시간: 15:00" in context


@pytest.mark.anyio
async def test_wider_pool_limits_details_and_reuses_public_data(api_stub, monkeypatch):
    """20개 후보를 조회해도 상세 호출과 전달은 5개이며 캐시를 재사용합니다."""
    responses, calls = api_stub
    responses["areaBasedList2"] = [
        {"contentid": str(index), "contenttypeid": "39", "title": f"음식점{index}"}
        for index in range(1, 21)
    ]
    monkeypatch.setattr(pet_service.random, "sample", lambda population, k: population[:k])
    first = await pet_service.get_pet_tour_data(1, 39)
    assert len(first) == 5
    assert len(calls) == 11
    second = await pet_service.get_pet_tour_data(1, 39)
    assert second == first
    assert len(calls) == 11
    second[0]["pet_detail"]["acmpyNeedMtr"] = "오염된 값"
    third = await pet_service.get_pet_tour_data(1, 39)
    assert third[0]["pet_detail"]["acmpyNeedMtr"] == "이동장 필수"


@pytest.mark.anyio
async def test_sigungu_filter_and_other_places_keep_call_budget(api_stub, monkeypatch):
    """강릉·춘천을 공식 코드로 구분하고 추가 추천에서 최근 장소를 제외합니다."""
    responses, calls = api_stub
    responses["areaCode2"] = [{"name": "강릉시", "code": "1"}, {"name": "춘천시", "code": "13"}]
    responses["areaBasedList2"] = [
        {"contentid": str(index), "contenttypeid": "39", "title": f"음식점{index}"}
        for index in range(1, 21)
    ]
    monkeypatch.setattr(pet_service.random, "sample", lambda population, k: population[:k])
    first = await pet_service.get_pet_tour_data(32, 39, question="강릉에서 식당 추천", sigungu_name="강릉")
    assert len(calls) == 12
    assert calls[1][1]["sigunguCode"] == "1"
    history = [{"question": "강릉에서 식당 추천", "response": pet_service.build_pet_tour_context(first)}]
    second = await pet_service.get_pet_tour_data(32, 39, question="다른 식당 추천", history=history, sigungu_name="강릉")
    assert {item["contentid"] for item in first}.isdisjoint(item["contentid"] for item in second)
    assert len(calls) == 22
    await pet_service.get_pet_tour_data(32, 39, question="춘천에서 식당 추천", history=history, sigungu_name="춘천")
    assert next(params for endpoint, params in reversed(calls) if endpoint == "areaBasedList2")["sigunguCode"] == "13"


@pytest.mark.anyio
async def test_cache_expiry_and_key_change_do_not_hide_errors(api_stub, monkeypatch):
    """기한 만료와 인증키 변경 후에는 재조회하고 외부 오류는 캐시하지 않습니다."""
    responses, calls = api_stub
    clock = [0]
    monkeypatch.setattr(pet_service, "monotonic", lambda: clock[0])
    await pet_service.get_pet_tour_data(1, 39)
    assert len(calls) == 3
    clock[0] = pet_service.CACHE_TTL_SECONDS
    await pet_service.get_pet_tour_data(1, 39)
    assert len(calls) == 6
    monkeypatch.setattr(pet_service.settings, "KOR_PET_TOUR_SERVICE_KEY", "changed-test-key")
    responses["areaBasedList2"] = {"response": {"header": {"resultCode": "30"}}}
    for _ in range(2):
        with pytest.raises(pet_service.PetTourServiceError):
            await pet_service.get_pet_tour_data(1, 39)
    assert len(calls) == 8


@pytest.mark.anyio
async def test_cache_separates_searches_and_bounds_storage(api_stub, monkeypatch):
    """지역·유형별 캐시를 분리하고 최대 저장 개수를 초과하지 않습니다."""
    _, calls = api_stub
    monkeypatch.setattr(pet_service, "CACHE_MAX_ENTRIES", 2)
    await pet_service.area_based_list(1, 39)
    await pet_service.area_based_list(6, 39)
    await pet_service.area_based_list(6, 12)
    assert len(calls) == 3
    assert len(pet_service._response_cache) == 2
    await pet_service.area_based_list(1, 39)
    assert len(calls) == 4


@pytest.mark.parametrize("name,expected", [
    ("강릉", 1), ("강릉시", 1), ("춘천", 13), ("없는시군구", None), (None, None),
])
@pytest.mark.anyio
async def test_only_explicit_destination_district_is_resolved(api_stub, name, expected):
    """분석된 목적지 시군구만 공식 코드와 비교하고 누락되면 조회하지 않습니다."""
    responses, calls = api_stub
    responses["areaCode2"] = [{"name": "강릉시", "code": "1"}, {"name": "춘천시", "code": "13"}]
    assert await pet_service._resolve_sigungu_code(32, name) == expected
    assert len(calls) == (1 if name else 0)


def test_selection_preserves_followup_and_deduplicates(monkeypatch):
    """상세 조건 후속 질문은 기존 장소를 우선하며 중복·누락 ID를 제거합니다."""
    items = [{"contentid": str(index), "contenttypeid": "39", "title": f"장소{index}"} for index in range(1, 21)]
    items[1] = dict(items[0])
    items[2] = {"title": "잘못된 항목"}
    monkeypatch.setattr(pet_service.random, "sample", lambda population, k: population[:k])
    history = [{"question": "지역 추천", "response": "장소16, 장소17, 장소18, 장소19, 장소20"}]
    selected = pet_service.select_pet_tour_candidates(items, "그중 동반 조건을 알려줘", history)
    assert {item["contentid"] for item in selected} == {str(index) for index in range(16, 21)}


@pytest.mark.anyio
async def test_invalid_response_and_missing_key_never_use_cache(api_stub, monkeypatch):
    """잘못된 본문은 캐시하지 않으며 인증키가 제거되면 기존 캐시도 사용하지 않습니다."""
    responses, calls = api_stub
    responses["areaBasedList2"] = {"response": {"header": {"resultCode": "0000"}, "body": {"items": {"item": [42]}}}}
    for _ in range(2):
        with pytest.raises(pet_service.PetTourServiceError):
            await pet_service.area_based_list(1, 39)
    assert len(calls) == 2
    responses["areaBasedList2"] = []
    await pet_service.area_based_list(1, 39)
    monkeypatch.setattr(pet_service.settings, "KOR_PET_TOUR_SERVICE_KEY", "")
    with pytest.raises(pet_service.PetTourServiceError, match="설정되지"):
        await pet_service.area_based_list(1, 39)


def test_alternatives_with_exhausted_pool_remain_source_backed():
    """후보를 모두 본 경우에도 새로운 장소를 만들어내지 않습니다."""
    items = [{"contentid": "1", "contenttypeid": "39", "title": "유일한 식당"}]
    history = [{"question": "추천", "response": "유일한 식당"}]
    assert pet_service.select_pet_tour_candidates(items, "다른 식당 추천", history) == items


@pytest.mark.anyio
async def test_invalid_codes_are_rejected_before_network(api_stub):
    """형식이 잘못된 검색 코드는 외부 요청 전에 거부합니다."""
    _, calls = api_stub
    for area_code, content_type in ((999, 39), (True, 39), (1, 999)):
        with pytest.raises(ValueError):
            await pet_service.get_pet_tour_data(area_code, content_type, question="식당 추천")
    with pytest.raises(ValueError):
        await pet_service.area_based_list(1, 39, sigungu_code=-1)
    assert calls == []


@pytest.mark.anyio
async def test_same_pool_tour_calls_match_cost_model(api_stub, monkeypatch):
    """같은 후보군을 모두 순환해도 실제 대역 호출이 모델 상한 42회를 넘지 않습니다."""
    responses, calls = api_stub
    responses["areaCode2"] = [{"name": "강릉시", "code": "1"}]
    responses["areaBasedList2"] = [
        {"contentid": str(index), "contenttypeid": "39", "title": f"식당{index}"}
        for index in range(1, 21)
    ]
    monkeypatch.setattr(pet_service.random, "sample", lambda population, k: population[:k])
    history = []
    for _ in range(10):
        result = await pet_service.get_pet_tour_data(32, 39, question="강릉 다른 식당 추천", history=history[-5:], sigungu_name="강릉")
        history.append({"question": "강릉 다른 식당 추천", "response": pet_service.build_pet_tour_context(result)})
    assert len(calls) == 42


@pytest.mark.anyio
async def test_province_only_skips_unavailable_district_api(api_stub):
    """시군구 없는 현재 질문은 이전 시군구나 지역 코드 API 장애에 영향받지 않습니다."""
    responses, calls = api_stub
    responses["areaCode2"] = httpx.ReadTimeout("지역 코드 장애")
    result = await pet_service.get_pet_tour_data(
        1, 39, question="서울 식당 추천",
        history=[{"question": "강릉 식당 추천", "response": "이전 식당"}],
    )
    assert len(result) == 1
    assert "areaCode2" not in [endpoint for endpoint, _ in calls]


@pytest.mark.parametrize("value", [
    httpx.ReadTimeout("지역 코드 시간 초과"), httpx.ConnectError("지역 코드 연결 실패"),
    {"response": {"header": {"resultCode": "30"}}}, {"unexpected": "잘못된 응답"},
    [{"name": "강릉시", "code": True}], [],
])
@pytest.mark.anyio
async def test_district_failure_uses_only_destination_addresses(api_stub, value):
    """시군구 조회 실패·미확인 시 다른 도시나 주소 없는 장소를 추천하지 않습니다."""
    responses, calls = api_stub
    responses["areaCode2"] = value
    responses["areaBasedList2"] = [
        {"contentid": "1", "contenttypeid": "39", "title": "강릉 식당", "addr1": "강원특별자치도 강릉시 중앙로 1"},
        {"contentid": "2", "contenttypeid": "39", "title": "춘천 식당", "addr1": "강원특별자치도 춘천시 중앙로 1"},
        {"contentid": "3", "contenttypeid": "39", "title": "강릉 이름의 식당", "addr1": ""},
        {"contentid": "4", "contenttypeid": "39", "title": "강릉로 식당", "addr1": "강원특별자치도 춘천시 강릉로 1"},
    ]
    result = await pet_service.get_pet_tour_data(32, 39, question="서울에서 강릉 식당 추천", sigungu_name="강릉")
    assert [item["contentid"] for item in result] == ["1"]
    assert len(calls) == 4
    assert "sigunguCode" not in calls[1][1]
    assert all(params["contentId"] == "1" for endpoint, params in calls if endpoint.startswith("detail"))


@pytest.mark.anyio
async def test_failed_district_lookup_is_retried_and_can_recover(api_stub):
    """실패는 캐시하지 않고 다음 요청의 정상 코드 조회를 사용할 수 있습니다."""
    responses, calls = api_stub
    responses["areaCode2"] = httpx.ReadTimeout("일시 장애")
    responses["areaBasedList2"] = [{"contentid": "1", "contenttypeid": "39", "title": "주소 불명 식당"}]
    assert await pet_service.get_pet_tour_data(32, 39, sigungu_name="강릉") == []
    assert len(calls) == 2
    responses["areaCode2"] = [{"name": "강릉시", "code": "1"}]
    result = await pet_service.get_pet_tour_data(32, 39, sigungu_name="강릉")
    assert len(result) == 1
    assert [endpoint for endpoint, _ in calls].count("areaCode2") == 2
    assert calls[3][1]["sigunguCode"] == "1"


@pytest.mark.parametrize("value,error", [
    (httpx.ReadTimeout("필수 조회 시간 초과"), pet_service.PetTourAPITimeoutError),
    (httpx.ConnectError("필수 조회 실패"), pet_service.PetTourServiceError),
])
@pytest.mark.parametrize("endpoint", ["areaBasedList2", "detailPetTour2"])
@pytest.mark.anyio
async def test_primary_api_failures_are_not_hidden_by_district_fallback(api_stub, value, error, endpoint):
    """시군구 대체 경로에서도 장소 목록·상세 조회 오류는 기존 예외로 전달합니다."""
    responses, _ = api_stub
    responses["areaCode2"] = httpx.ReadTimeout("시군구 시간 초과")
    responses["areaBasedList2"] = [{"contentid": "1", "contenttypeid": "39", "title": "강릉 식당", "addr1": "강원특별자치도 강릉시 중앙로 1"}]
    responses[endpoint] = value
    with pytest.raises(error):
        await pet_service.get_pet_tour_data(32, 39, sigungu_name="강릉")


@pytest.mark.parametrize("address,name,expected", [
    ("강원특별자치도 양구군 중앙로 1", "양구", True),
    ("강원특별자치도 강릉시 중앙로 1", "강릉시", True),
    ("강원특별자치도 춘천시 강릉로 1", "강릉", False),
    ("경기도 광주시 중앙로 1", "광주", True),
])
def test_fallback_address_requires_an_administrative_name(address, name, expected):
    """접미사가 이름의 일부인 양구와 다른 도시의 유사 도로명을 구분합니다."""
    assert pet_service._address_matches_sigungu(address, name) is expected
