"""설정된 키로 Jev 연결과 응답 형식을 직접 확인합니다."""

import asyncio
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.jev_service import JevServiceError, judge_answer


async def main() -> int:
    """실제 Jev API에 예시 한 건을 보내고 민감정보 없이 결과를 출력합니다."""
    if not settings.TYPESAFE_API_KEY:
        print("JEV connection       MISSING API KEY")
        return 2

    started_at = perf_counter()
    try:
        decision = await judge_answer(
            "반려견과 국내여행 전에 확인할 사항은?",
            [],
            "동반 가능 여부와 크기 제한, 이동 규정을 방문 전 확인해 주세요.",
        )
    except JevServiceError as exc:
        print(f"JEV connection       FAILED ({exc.error_type})")
        return 1

    print("JEV connection       OK")
    print(f"requested model      {settings.JEV_MODEL}")
    print(f"resolved model       {decision.model}")
    print(f"API latency          {round((perf_counter() - started_at) * 1000)} ms")
    print(f"decision             {decision.action}")
    print(f"confidence           {decision.confidence:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
