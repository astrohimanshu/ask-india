"""Forward a TCP port from one address to another (used to expose the host's Ollama to kind).

uv run scripts/tcp_forward.py <listen_host> <listen_port> <target_host> <target_port>
"""

from __future__ import annotations

import asyncio
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()


async def handle(
    client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, target: tuple[str, int]
) -> None:
    try:
        server_r, server_w = await asyncio.open_connection(*target)
    except OSError:
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, server_w), pipe(server_r, client_w))


async def main() -> None:
    listen_host, listen_port, target_host, target_port = sys.argv[1:5]
    target = (target_host, int(target_port))
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, target), listen_host, int(listen_port)
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
