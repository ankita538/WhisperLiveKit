from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from whisperlivekit import (
    TranscriptionEngine,
    AudioProcessor,
    get_inline_ui_html,
    parse_args,
)
import asyncio
import logging
import json
import torch  # Required for GPU cleanup

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

args = parse_args()
transcription_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    transcription_engine = TranscriptionEngine(
        **vars(args),
    )
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def get():
    return HTMLResponse(get_inline_ui_html())


async def handle_websocket_results(websocket, results_generator):
    """Consumes results from the audio processor and sends them via WebSocket."""
    try:
        async for response in results_generator:
            try:
                await websocket.send_json(response.to_dict())
            except Exception as e:
                # Client likely disconnected while we were sending results; stop
                # the results loop silently to avoid tracebacks in the server logs.
                logger.info(f"WebSocket send failed (client disconnected?): {e}")
                return
        # when the results_generator finishes it means all audio has been processed
        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        try:
            await websocket.send_json({"type": "ready_to_stop"})
        except Exception as e:
            logger.info(f"WebSocket send failed while sending ready_to_stop: {e}")
    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected while handling results (client likely closed connection)."
        )
    except Exception as e:
        msg = str(e)
        if isinstance(e, RuntimeError) and (
            "Unexpected ASGI message" in msg or "after sending 'websocket.close'" in msg
        ):
            logger.info(f"WebSocket results handler ended: {msg}")
        else:
            logger.exception(f"Error in WebSocket results handler: {e}")


@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live ASR."""
    await websocket.accept()
    logger.info("WebSocket connection opened.")
    audio_processor = None

    try:
        # 1. Accept either a config request or the initial start message.
        selected_lang = None
        while True:
            init_msg = await websocket.receive_json()
            # If client only wants server configuration, reply and continue waiting for start
            if init_msg.get("type") == "config":
                try:
                    use_audio_worklet = bool(
                        getattr(transcription_engine.args, "pcm_input", False)
                    )
                except Exception:
                    use_audio_worklet = False
                await websocket.send_json(
                    {"type": "config", "useAudioWorklet": use_audio_worklet}
                )
                continue

            # Expect the start command to actually begin a session
            if init_msg.get("command") == "start":
                selected_lang = init_msg.get("language", transcription_engine.args.lan)
                logger.info(
                    f"Starting transcription with language: {selected_lang or 'auto'}"
                )
                break

            # Unknown initial message: close with invalid data code
            logger.error(
                "First meaningful message must be a 'start' command or 'config' request"
            )
            await websocket.close(code=1003)
            return

        # 2. Initialize audio processor with the selected language
        audio_processor = AudioProcessor(
            transcription_engine=transcription_engine, lan=selected_lang
        )

        # 3. Create tasks for processing audio and handling results
        results_generator = await audio_processor.create_tasks()
        websocket_task = asyncio.create_task(
            handle_websocket_results(websocket, results_generator)
        )

        # 4. Main loop for processing audio
        while True:
            try:
                message = await websocket.receive()

                # Binary frames carry the bytes in the 'bytes' key
                if message.get("bytes") is not None:
                    await audio_processor.process_audio(message["bytes"])
                    continue

                # Text frames are provided in the 'text' key; parse JSON if possible
                if message.get("text") is not None:
                    raw = message.get("text")
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = {}

                    # allow runtime config queries
                    if data.get("type") == "config":
                        try:
                            use_audio_worklet = bool(
                                getattr(transcription_engine.args, "pcm_input", False)
                            )
                        except Exception:
                            use_audio_worklet = False
                        await websocket.send_json(
                            {"type": "config", "useAudioWorklet": use_audio_worklet}
                        )
                        continue

                    if data.get("command") == "stop":
                        logger.info("Received stop command from client")
                        break

            except WebSocketDisconnect:
                logger.info("Client disconnected")
                break
            except Exception as e:
                msg = str(e)
                if (
                    isinstance(e, RuntimeError)
                    and 'Cannot call "receive" once a disconnect message has been received'
                    in msg
                ):
                    logger.info(
                        "WebSocket receive called after disconnect; ending loop."
                    )
                    break
                logger.error(f"Error processing message: {e}")
                break

    except Exception as e:
        logger.exception(f"Error in WebSocket handler: {e}")
    finally:
        # Cleanup
        if audio_processor:
            await audio_processor.cleanup()
        if "websocket_task" in locals():
            websocket_task.cancel()
            try:
                await websocket_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error during WebSocket task cleanup: {e}")

        logger.info("WebSocket connection closed")


# --- AudioProcessor cleanup modifications ---
async def audio_processor_cleanup(self):
    logger.info("Starting cleanup of AudioProcessor resources.")
    self.is_stopping = True

    # Clear any queued items
    if hasattr(self, "transcription_queue"):
        while not self.transcription_queue.empty():
            try:
                self.transcription_queue.get_nowait()
                self.transcription_queue.task_done()
            except asyncio.QueueEmpty:
                break

    # GPU memory cleanup
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


# Patch the AudioProcessor class with the new cleanup
AudioProcessor.cleanup = audio_processor_cleanup


def main():
    """Entry point for the CLI command."""
    import uvicorn

    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server:app",
        "host": args.host,
        "port": args.port,
        "reload": False,
        "log_level": "info",
        "lifespan": "on",
    }

    ssl_kwargs = {}
    if args.ssl_certfile or args.ssl_keyfile:
        if not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError(
                "Both --ssl-certfile and --ssl-keyfile must be specified together."
            )
        ssl_kwargs = {
            "ssl_certfile": args.ssl_certfile,
            "ssl_keyfile": args.ssl_keyfile,
        }

    if ssl_kwargs:
        uvicorn_kwargs = {**uvicorn_kwargs, **ssl_kwargs}
    if args.forwarded_allow_ips:
        uvicorn_kwargs = {
            **uvicorn_kwargs,
            "forwarded_allow_ips": args.forwarded_allow_ips,
        }

    uvicorn.run(**uvicorn_kwargs)


if __name__ == "__main__":
    main()
