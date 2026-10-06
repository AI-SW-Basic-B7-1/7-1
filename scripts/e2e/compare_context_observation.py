"""실제 Gemini 요청의 문맥 해시를 DB 기반 기대값과 비교합니다."""

import argparse
import json
import re
import sys
from pathlib import Path


HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


def read_context(path: Path) -> list[dict[str, str]]:
    """해시와 역할만 있는 JSON 문맥 목록을 읽고 형식을 확인합니다."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("문맥 목록 형식이 올바르지 않습니다.")
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"role", "sha256"}
            or item.get("role") not in {"user", "model"}
            or not isinstance(item.get("sha256"), str)
            or not HASH_PATTERN.fullmatch(item["sha256"])
        ):
            raise ValueError("문맥 항목 형식이 올바르지 않습니다.")
    return value


def main() -> int:
    """두 문맥 해시를 일치 여부와 항목 수로만 보고합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("observed", type=Path)
    arguments = parser.parse_args()
    try:
        expected = read_context(arguments.expected)
        observed = read_context(arguments.observed)
    except (OSError, json.JSONDecodeError, ValueError):
        print("문맥 관측 자료를 읽거나 검증하지 못했습니다.", file=sys.stderr)
        return 2
    matched = expected == observed and len(expected) == 11
    print(f"E2E_CONTEXT_MATCHED={int(matched)} roles={len(observed)}")
    if not matched:
        print("실제 전송 문맥과 최근 다섯 쌍 기대값이 다릅니다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
