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
    assert all(params["numOfRows"] == "5" for _, params in calls)
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
