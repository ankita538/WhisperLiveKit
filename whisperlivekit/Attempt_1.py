from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from whisperlivekit import TranscriptionEngine, AudioProcessor, get_inline_ui_html, parse_args
import asyncio
import logging

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ----------------------------
# Parse args and global engine
# ----------------------------
args = parse_args()
transcription_engine = None

# ----------------------------
# Lifespan context to init engine
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):    
    global transcription_engine
    transcription_engine = TranscriptionEngine(
        **vars(args),
    )
    yield

# ----------------------------
# FastAPI app setup
# ----------------------------
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
    """Return inline HTML UI"""
    return HTMLResponse(get_inline_ui_html())

# ----------------------------
# WebSocket result sender
# ----------------------------
async def handle_websocket_results(websocket: WebSocket, results_generator):
    """Consume results from AudioProcessor and send via WebSocket."""
    try:
        async for response in results_generator:
            await websocket.send_json(response.to_dict())
        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected while handling results.")
    except Exception as e:
        logger.exception(f"Error in WebSocket results handler: {e}")

# ----------------------------
# WebSocket endpoint
# ----------------------------
@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine
    await websocket.accept()
    logger.info("WebSocket connection opened.")

    try:
        # Send initial config to client
        await websocket.send_json({"type": "config", "useAudioWorklet": bool(args.pcm_input)})

        # Wait for client to send start command with language
        msg = await websocket.receive_json()
        if msg.get("command") == "start":
            client_lan = msg.get("lan", transcription_engine.args.lan)
        else:
            client_lan = transcription_engine.args.lan

        logger.info(f"Client selected language: {client_lan}")

        # Create session-specific AudioProcessor
        audio_processor = AudioProcessor(transcription_engine=transcription_engine, lan=client_lan)

        # Start processing tasks and results generator
        results_generator = await audio_processor.create_tasks()
        websocket_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))

        # Main loop: receive audio bytes
        while True:
            msg = await websocket.receive()

            # JSON messages (could handle pause/stop/etc)
            if msg["type"] == "json":
                data = msg["json"]
                if data.get("command") == "stop":
                    logger.info("Client requested stop")
                    break  # exit loop
                continue

            # Audio bytes
            elif msg["type"] == "bytes":
                await audio_processor.process_audio(msg["bytes"])

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client.")
    except Exception as e:
        logger.error(f"Unexpected error in websocket_endpoint: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up WebSocket endpoint...")
        if 'websocket_task' in locals() and not websocket_task.done():
            websocket_task.cancel()
        try:
            if 'websocket_task' in locals():
                await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket results handler task was cancelled.")
        except Exception as e:
            logger.warning(f"Exception while awaiting websocket_task completion: {e}")
        
        if 'audio_processor' in locals():
            await audio_processor.cleanup()
        logger.info("WebSocket endpoint cleaned up successfully.")

# ----------------------------
# CLI entry point
# ----------------------------
def main():
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
