"""JUnit XML에서 필수 E2E 사례와 실패·스킵 여부를 확인합니다."""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def validate_report(report_path: Path, required_cases: set[str]) -> tuple[bool, dict[str, int]]:
    """필수 사례가 수집되고 전부 통과했는지 검사합니다."""
    if not report_path.is_file():
        return False, {"collected": 0, "failed": 0, "skipped": 0, "missing": len(required_cases)}
    root = ET.parse(report_path).getroot()
    cases = root.findall(".//testcase")
    observed_cases = {
        scenario
        for case in cases
        for property_node in case.findall("./properties/property")
        if property_node.attrib.get("name") == "e2e_scenario"
        for scenario in property_node.attrib.get("value", "").split(",")
        if scenario
    }
    failed = sum(len(case.findall("failure")) + len(case.findall("error")) for case in cases)
    skipped = sum(len(case.findall("skipped")) for case in cases)
    summary = {
        "collected": len(cases),
        "failed": failed,
        "skipped": skipped,
        "missing": len(required_cases - observed_cases),
    }
    valid = bool(cases) and failed == 0 and skipped == 0 and summary["missing"] == 0
    return valid, summary


def main() -> int:
    """보고서를 확인하고 비밀값 없는 숫자 요약만 출력합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--required", nargs="*", default=[])
    arguments = parser.parse_args()
    try:
        valid, summary = validate_report(arguments.report, set(arguments.required))
    except (ET.ParseError, OSError):
        print("JUnit 보고서를 읽을 수 없습니다.", file=sys.stderr)
        return 2
    print("E2E_REPORT " + " ".join(f"{key}={value}" for key, value in sorted(summary.items())))
    if not valid:
        print("필수 E2E 사례에 누락·실패·스킵이 있습니다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
