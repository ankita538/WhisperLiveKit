"""Simple PCM WebSocket client: stream raw s16le PCM to /asr endpoint.

Usage:
  python scripts/pcm_ws_client.py <pcm_path> <language> [--host ws://localhost:8000/asr] [--chunk-size 4096] [--delay 0]

Sends a JSON start command: {"command":"start","pcm":true,"language":LANG}
Then streams raw PCM binary frames in chunks, then sends an empty bytes message to indicate EOF.
Prints JSON messages received from the server.
"""

import asyncio
import sys
import json
import argparse
import os
import time

import websockets


async def run(pcm_path, language, uri, chunk_size, delay):
    # Allow '-' to indicate reading raw PCM from stdin for live piping
    read_from_stdin = pcm_path == "-"

    if not read_from_stdin and not os.path.exists(pcm_path):
        print(f"PCM file not found: {pcm_path}")
        return

    async with websockets.connect(uri, max_size=None) as ws:
        print("Connected to", uri)

        # Request config probe (optional)
        await ws.send(json.dumps({"type": "config"}))
        try:
            reply = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print("CONFIG REPLY:", reply)
        except asyncio.TimeoutError:
            pass

        start_msg = {"command": "start", "pcm": True, "language": language}
        await ws.send(json.dumps(start_msg))
        print("Sent start", start_msg)

        # Stream the PCM file or stdin pipe
        if read_from_stdin:
            print(
                "Reading raw PCM from stdin. Pipe raw s16le 16k mono into this script."
            )
            loop = asyncio.get_event_loop()

            # Read synchronously from stdin in a thread to avoid blocking
            # the event loop.
            def stdin_reader():
                while True:
                    data = sys.stdin.buffer.read(chunk_size)
                    if not data:
                        return
                    asyncio.run_coroutine_threadsafe(ws.send(data), loop).result()
                    if delay and delay > 0:
                        time.sleep(delay)

            from threading import Thread

            t = Thread(target=stdin_reader, daemon=True)
            t.start()
            # Wait for the thread to finish (i.e. EOF on stdin)
            t.join()
        else:
            with open(pcm_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    await ws.send(chunk)
                    if delay and delay > 0:
                        await asyncio.sleep(delay)

        # send empty blob to indicate EOF
        await ws.send(b"")
        print("Sent EOF (empty blob)")

        # Send explicit stop command so the server can finalize deterministically
        stop_msg = {"command": "stop"}
        try:
            await ws.send(json.dumps(stop_msg))
            print("Sent stop command")
        except Exception:
            # if the connection is already closed, we'll fall through to recv handling
            print("Failed to send stop command (connection may be closed)")

        # Receive messages until server closes or timeout
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                try:
                    parsed = json.loads(msg)
                    print("RECV JSON:", json.dumps(parsed, ensure_ascii=False))
                except Exception:
                    # binary or non-json
                    print(
                        "RECV (non-json):",
                        type(msg),
                        len(msg) if hasattr(msg, "__len__") else None,
                    )
        except asyncio.TimeoutError:
            print("No more messages (timeout). Exiting.")
        except websockets.exceptions.ConnectionClosedOK:
            print("Connection closed by server.")
        except websockets.exceptions.ConnectionClosedError as e:
            print("Connection closed with error:", e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pcm_path")
    parser.add_argument("language")
    parser.add_argument("--host", default="ws://localhost:8000/asr")
    parser.add_argument("--chunk-size", type=int, default=4096)
    parser.add_argument(
        "--delay", type=float, default=0.0, help="seconds to wait between chunks"
    )
    args = parser.parse_args()

    asyncio.run(
        run(args.pcm_path, args.language, args.host, args.chunk_size, args.delay)
    )


if __name__ == "__main__":
    main()
