"""실행별 JUnit과 운영 결과가 모든 필수 시나리오를 포함하는지 확인합니다."""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


REQUIRED_SCENARIOS = {
    "A01", "A02", "A03", "A04", "A05", "F01", "F02", "F03", "F04", "F05",
    "I01", "I02", "I03", "I04", "N01", "N02", "N03", "N04", "O01",
    "R01", "R02", "R03", "R04", "V01", "V02",
}
REQUIRED_OPERATIONS = {"O02", "O03", "O04", "O05", "O06", "O07", "O08"}


def report_scenarios(report_path: Path) -> tuple[set[str], int, int, int]:
    """JUnit 하나에서 시나리오·실패·스킵·수집 수를 읽습니다."""
    root = ET.parse(report_path).getroot()
    cases = root.findall(".//testcase")
    scenarios = {
        scenario
        for case in cases
        for prop in case.findall("./properties/property")
        if prop.attrib.get("name") == "e2e_scenario"
        for scenario in prop.attrib.get("value", "").split(",")
        if scenario
    }
    failures = sum(len(case.findall("failure")) + len(case.findall("error")) for case in cases)
    skipped = sum(len(case.findall("skipped")) for case in cases)
    return scenarios, len(cases), failures, skipped


def main() -> int:
    """모든 단계 결과를 집계하고 실제 누락 ID만 표시합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir", type=Path)
    arguments = parser.parse_args()
    reports = sorted(arguments.report_dir.glob("*.xml"))
    if not reports:
        print("JUnit 보고서가 없습니다.", file=sys.stderr)
        return 2
    counts: Counter[str] = Counter()
    total_cases = total_failures = total_skipped = 0
    try:
        for path in reports:
            scenarios, collected, failed, skipped = report_scenarios(path)
            if collected == 0:
                print("빈 JUnit 보고서가 있습니다.", file=sys.stderr)
                return 1
            counts.update(scenarios)
            total_cases += collected
            total_failures += failed
            total_skipped += skipped
    except (OSError, ET.ParseError):
        print("JUnit 보고서를 읽을 수 없습니다.", file=sys.stderr)
        return 2

    missing = sorted(REQUIRED_SCENARIOS - counts.keys())
    operations_path = arguments.report_dir / "operations.jsonl"
    operations: dict[str, str] = {}
    try:
        for line in operations_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if not isinstance(item, dict) or item.get("scenario_id") not in REQUIRED_OPERATIONS:
                raise ValueError
            operations[item["scenario_id"]] = item.get("status", "")
    except (OSError, json.JSONDecodeError, ValueError):
        print("운영 시나리오 증거를 읽을 수 없습니다.", file=sys.stderr)
        return 2

    missing_operations = sorted(REQUIRED_OPERATIONS - operations.keys())
    incomplete_operations = sorted(
        scenario for scenario, status in operations.items() if status != "passed"
    )
    print(
        "E2E_RUN_REPORTS "
        f"reports={len(reports)} collected={total_cases} failures={total_failures} "
        f"skipped={total_skipped} missing={len(missing)} "
        f"missing_operations={len(missing_operations)} "
        f"incomplete_operations={len(incomplete_operations)} "
        f"F05_recoveries={counts['F05']}"
    )
    if missing or missing_operations or incomplete_operations or total_failures or total_skipped or counts["F05"] < 6:
        print(
            "필수 결과가 누락되었거나 통과하지 않았습니다: "
            f"scenarios={','.join(missing) or 'none'} "
            f"operations={','.join(missing_operations) or 'none'} "
            f"incomplete={','.join(incomplete_operations) or 'none'}",
            file=sys.stderr,
        )
        return 1
    print("E2E_OVERALL=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
