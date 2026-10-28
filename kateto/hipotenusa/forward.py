from __future__ import annotations

import asyncio


async def forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def proxy_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int) -> None:
    try:
        remote_reader, remote_writer = await asyncio.open_connection(host, port)
    except OSError:
        writer.close()
        await writer.wait_closed()
        return
    await asyncio.gather(forward(reader, remote_writer), forward(remote_reader, writer))
