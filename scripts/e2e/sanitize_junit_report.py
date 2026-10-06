"""JUnit XML의 자격 증명·원시 출력·불필요한 속성을 정리합니다."""

import argparse
import ast
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)(AIza)[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(password|username|access_token|api_key|secret_key)(['\"]?\s*[:=]\s*['\"]?)([^\s,'\"}]+)"),
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FAILURE_LOCATION_PATTERN = re.compile(
    r'(?m)^\s*File\s+["\'][^"\']*(?P<path>tests[\\/]e2e[\\/][A-Za-z0-9_.-]+\.py)["\']\s*,\s*line\s+(?P<line>\d+)\s*,\s*in\s+(?P<function>test_[A-Za-z0-9_]+)\s*$'
)
PYTEST_FAILURE_LOCATION_PATTERN = re.compile(
    r'(?m)^\s*(?P<path>tests[\\/]e2e[\\/][A-Za-z0-9_.-]+\.py):(?P<line>\d+):\s*[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\s*$'
)


def redact(value: str, secrets: list[str]) -> str:
    """알려진 자격 증명과 토큰 형태를 문자열에서 가립니다."""
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = PATTERNS[0].sub("Bearer [REDACTED]", value)
    value = PATTERNS[1].sub("[JWT REDACTED]", value)
    value = PATTERNS[2].sub(r"\1[REDACTED]", value)
    return PATTERNS[3].sub(r"\1\2[REDACTED]", value)


def _validated_failure_location(path: str, line: str, test_name: str) -> tuple[str, str] | None:
    """저장소 테스트 파일과 테스트 함수 안의 유효한 줄 번호인지 확인합니다."""
    normalized_path = path.replace("\\", "/")
    if not re.fullmatch(r"tests/e2e/[A-Za-z0-9_.-]+\.py", normalized_path):
        return None
    expected_function = test_name.split("[", 1)[0]
    if not re.fullmatch(r"test_[A-Za-z0-9_]+", expected_function):
        return None
    try:
        line_number = int(line)
        source_path = (REPOSITORY_ROOT / normalized_path).resolve()
        source_path.relative_to(REPOSITORY_ROOT)
        source = source_path.read_text(encoding="utf-8")
        syntax_tree = ast.parse(source)
    except (OSError, RuntimeError, SyntaxError, ValueError):
        return None
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == expected_function
        and node.lineno <= line_number <= getattr(node, "end_lineno", node.lineno)
        for node in ast.walk(syntax_tree)
    ):
        return None
    return normalized_path, str(line_number)


def _failure_location(detail: str, test_name: str) -> tuple[str, str] | None:
    """Python traceback 또는 pytest 실패 위치에서 검증된 위치만 추출합니다."""
    expected_function = test_name.split("[", 1)[0]
    for pattern in (FAILURE_LOCATION_PATTERN, PYTEST_FAILURE_LOCATION_PATTERN):
        for match in pattern.finditer(detail):
            function = match.groupdict().get("function")
            if function and function != expected_function:
                continue
            location = _validated_failure_location(
                match.group("path"), match.group("line"), test_name
            )
            if location:
                return location
    return None


def sanitize_report(path: Path, secrets: list[str]) -> int:
    """JUnit 결과의 비밀값을 지우고 시나리오 속성만 보존합니다."""
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        replace_with_safe_failure_report(path)
        raise
    root = tree.getroot()
    for parent in root.iter():
        for child in list(parent):
            if child.tag in {"system-out", "system-err"}:
                parent.remove(child)
        for child in parent.findall("properties"):
            for prop in list(child):
                if prop.attrib.get("name") != "e2e_scenario":
                    child.remove(prop)
    for testcase in root.iter("testcase"):
        for node in (*testcase.findall("failure"), *testcase.findall("error")):
            detail = node.attrib.get("message", "") + "\n" + (node.text or "")
            last_line = next((line.strip() for line in reversed(detail.splitlines()) if line.strip()), "")
            exception = re.match(r"(?:E\s+)?([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))(?::|$)", last_line)
            node.attrib["message"] = exception.group(1).rsplit(".", 1)[-1] if exception else "실패 상세 보호됨"
            location = _validated_failure_location(
                node.attrib.get("source_file", ""),
                node.attrib.get("source_line", ""),
                testcase.attrib.get("name", ""),
            ) or _failure_location(detail, testcase.attrib.get("name", ""))
            if location:
                node.attrib["source_file"], node.attrib["source_line"] = location
            else:
                node.attrib.pop("source_file", None)
                node.attrib.pop("source_line", None)
            node.text = "실패 세부 내용은 민감정보 보호를 위해 제거했습니다."
            if location:
                node.text += f" 검증 위치: {location[0]}:{location[1]}"
            for child in list(node):
                node.remove(child)
    for node in root.iter():
        if node.text:
            node.text = redact(node.text, secrets)
        if node.tail:
            node.tail = redact(node.tail, secrets)
        for name, value in list(node.attrib.items()):
            node.attrib[name] = redact(value, secrets)
    replace_report(path, tree)
    return sum(1 for node in root.iter() if node.tag in {"failure", "error"})


def replace_report(path: Path, tree: ET.ElementTree) -> None:
    """완성된 보고서만 임시 파일을 통해 원본과 교체합니다."""
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        tree.write(temporary_path, encoding="utf-8", xml_declaration=True)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def replace_with_safe_failure_report(path: Path) -> None:
    """읽을 수 없는 원본 보고서를 안전한 실패 표식으로 바꿉니다."""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", name="e2e-report-sanitization", tests="1", errors="1")
    case = ET.SubElement(suite, "testcase", name="e2e-report-sanitization")
    ET.SubElement(case, "error", message="JUnit 정리 실패").text = (
        "원본 보고서는 민감정보 보호를 위해 제거되었습니다."
    )
    replace_report(path, ET.ElementTree(root))


def main() -> int:
    """JUnit 보고서를 정리하고 원문 출력 없이 처리 결과를 표시합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    arguments = parser.parse_args()
    secrets = [
        os.environ.get("E2E_ACCOUNT_USERNAME", ""),
        os.environ.get("E2E_ACCOUNT_PASSWORD", ""),
        os.environ.get("GEMINI_API_KEY", ""),
    ]
    try:
        failures = sanitize_report(arguments.report, secrets)
    except (OSError, ET.ParseError):
        print("JUnit 보고서를 정리하지 못했습니다.", file=sys.stderr)
        return 2
    print(f"E2E_JUNIT_SANITIZED=1 failures={failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
