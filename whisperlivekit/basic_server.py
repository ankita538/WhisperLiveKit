from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from whisperlivekit import TranscriptionEngine, AudioProcessor, get_inline_ui_html, parse_args
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
            await websocket.send_json(response.to_dict())
        # when the results_generator finishes it means all audio has been processed
        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected while handling results (client likely closed connection).")
    except Exception as e:
        logger.exception(f"Error in WebSocket results handler: {e}")


@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for live ASR.
    - Receives initial JSON with selected language.
    - Streams audio bytes for transcription.
    - Sends ASR results back to the client in real time.
    """
    await websocket.accept()
    logger.info("WebSocket connection opened.")

    # 1️⃣ Receive initial command with language
    try:
        init_msg = await websocket.receive_json()
        selected_lang = init_msg.get("lan", transcription_engine.args.lan)
        logger.info(f"Client selected language: {selected_lang}")
    except Exception as e:
        selected_lang = transcription_engine.args.lan
        logger.warning(f"Failed to get initial language from client, defaulting to {selected_lang}: {e}")

    # 2️⃣ Create AudioProcessor with session-specific language
    audio_processor = AudioProcessor(transcription_engine=transcription_engine, lan=selected_lang)

    # 3️⃣ Start results handler in the background
    results_generator = audio_processor.create_tasks()
    websocket_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))

    try:
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                logger.info("Client disconnected.")
                break
            except RuntimeError as e:
                # Happens if receive is called after disconnect
                if "Cannot call \"receive\" once a disconnect message has been received" in str(e):
                    logger.info("Client already disconnected, breaking loop.")
                    break
                else:
                    raise

            # 4️⃣ Handle JSON commands (e.g., start/stop)
            if msg["type"] in ("json", "text"):
                data = msg.get("json") or {}
                command = data.get("command")
                if command == "start":
                    logger.info(f"Received start command from client: {data}")
                    # Already initialized AudioProcessor with language
                    continue
                elif command == "stop":
                    logger.info("Received stop command from client.")
                    break
                continue

            # 5️⃣ Handle audio bytes
            elif msg["type"] == "bytes":
                await audio_processor.process_audio(msg["bytes"])

    except Exception as e:
        logger.exception(f"Unexpected error in WebSocket endpoint main loop: {e}")
    finally:
        logger.info("Cleaning up WebSocket session...")
        if not websocket_task.done():
            websocket_task.cancel()
        try:
            await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket results handler task cancelled.")
        except Exception as e:
            logger.warning(f"Exception while awaiting websocket_task completion: {e}")

        await audio_processor.cleanup()
        logger.info("WebSocket session cleaned up successfully.")

def main():
    """Entry point for the CLI command."""
    import uvicorn
    
    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server:app",
        "host":args.host, 
        "port":args.port, 
        "reload": False,
        "log_level": "info",
        "lifespan": "on",
    }
    
    ssl_kwargs = {}
    if args.ssl_certfile or args.ssl_keyfile:
        if not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError("Both --ssl-certfile and --ssl-keyfile must be specified together.")
        ssl_kwargs = {
            "ssl_certfile": args.ssl_certfile,
            "ssl_keyfile": args.ssl_keyfile
        }

    if ssl_kwargs:
        uvicorn_kwargs = {**uvicorn_kwargs, **ssl_kwargs}
    if args.forwarded_allow_ips:
        uvicorn_kwargs = { **uvicorn_kwargs, "forwarded_allow_ips" : args.forwarded_allow_ips }

    uvicorn.run(**uvicorn_kwargs)

if __name__ == "__main__":
    main()
