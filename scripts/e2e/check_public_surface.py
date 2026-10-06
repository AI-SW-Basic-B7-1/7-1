"""외부 HTTPS 리소스 차단과 FastAPI 포트 비노출을 확인합니다."""

import argparse
import socket
from urllib.parse import urlsplit

import httpx


BLOCKED_PATHS = (
    "/.env",
    "/.git/config",
    "/data/chatbot.db",
    "/data/chatbot.db-wal",
    "/data/chatbot.db-shm",
    "/logs/app.log",
    "/logs/server.log",
    "/db_backups/",
)


def main() -> int:
    """허용된 health·정적 파일은 열리고 민감 경로는 차단되는지 확인합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    arguments = parser.parse_args()
    parsed = urlsplit(arguments.base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        parser.error("HTTPS origin 주소가 필요합니다.")
    base_url = arguments.base_url.rstrip("/")
    with httpx.Client(timeout=10.0, follow_redirects=True, trust_env=False) as client:
        health = client.get(f"{base_url}/api/health")
        style = client.get(f"{base_url}/static/css/style.css")
        if health.status_code != 200 or health.json().get("status") != "ok":
            raise SystemExit("외부 HTTPS health 확인에 실패했습니다.")
        if style.status_code != 200:
            raise SystemExit("외부 정적 파일 응답이 정상적이지 않습니다.")
        statuses = []
        for path in BLOCKED_PATHS:
            response = client.head(f"{base_url}{path}")
            statuses.append(response.status_code)
            if response.status_code not in {403, 404}:
                raise SystemExit("민감 파일 경로가 외부에서 차단되지 않았습니다.")

    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(parsed.hostname, None, socket.AF_INET, socket.SOCK_STREAM)
    }
    if not addresses:
        raise SystemExit("테스트 도메인의 IPv4 주소를 확인하지 못했습니다.")
    reachable = False
    for address in addresses:
        try:
            with socket.create_connection((address, 8000), timeout=3):
                reachable = True
                break
        except OSError:
            continue
    if reachable:
        raise SystemExit("FastAPI 8000 포트가 외부에서 연결됩니다.")
    print(f"E2E_PUBLIC_SURFACE_VERIFIED=1 blocked_paths={len(statuses)} direct_api_port=closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
