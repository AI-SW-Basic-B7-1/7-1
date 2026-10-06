"""루프백 HTTPS CONNECT 시험 요청을 지연한 뒤 닫는 임시 프록시입니다."""

import argparse
import asyncio


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, delay: float) -> None:
    """CONNECT 요청 헤더를 읽고 제한 시간보다 늦게 연결을 닫습니다."""
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
        if not header.startswith(b"CONNECT "):
            return
        await asyncio.sleep(delay)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        return
    finally:
        writer.close()
        await writer.wait_closed()


async def serve(port: int, delay: float) -> None:
    """localhost에서만 HTTPS CONNECT를 받아 시간 초과를 재현합니다."""
    server = await asyncio.start_server(
        lambda reader, writer: handle_client(reader, writer, delay),
        "127.0.0.1",
        port,
    )
    async with server:
        await server.serve_forever()


def main() -> int:
    """지정한 루프백 포트에서 제한 시간 프록시를 실행합니다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--delay", type=float, required=True)
    arguments = parser.parse_args()
    if not 1024 <= arguments.port <= 65535 or not 8.0 < arguments.delay <= 60.0:
        parser.error("포트 또는 지연 시간이 허용 범위를 벗어났습니다.")
    asyncio.run(serve(arguments.port, arguments.delay))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
