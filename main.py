import json
from dotenv import load_dotenv, dotenv_values
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
import os
import asyncio

DEV_PREFIX = "/dev"
PROD_PREFIX = "/prod"
CURRENT_VERSION_PREFIX = "/v1"

# try loading from .env file (only when running locally)
try:
    config = dotenv_values(".env")
except FileNotFoundError:
    config = {}
# load secrets from /run/secrets/ (only when running in docker)
load_dotenv(dotenv_path="/run/secrets/prepit-secret")
load_dotenv()
dg_client = DeepgramClient(api_key="e787517287be850e46fbb7de34398eaf81999655")

sio_server = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=[],
)

sio_app = socketio.ASGIApp(
    socketio_server=sio_server,
    socketio_path='/',
)

#  app = FastAPI(docs_url=f"{PREFIX}/docs", redoc_url=f"{PREFIX}/redoc", openapi_url=f"{PREFIX}/openapi.json")
#  use the following for production
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

origins = [
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "https://jerryyang666.github.io",
    "https://os-computational-economics.github.io",
    "http://localhost:63342",
    "https://file.jerryang.org",
    "https://coding.coursey.ai",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(f"{CURRENT_VERSION_PREFIX}{DEV_PREFIX}/live", app=sio_app)
app.mount(f"{CURRENT_VERSION_PREFIX}{PROD_PREFIX}/live", app=sio_app)

load_dotenv()
runner_access_token = '123'
# User sessions dictionary to store Deepgram connections
user_sessions = {}
transcription_tasks = {}


async def start_transcription(sid):
    # Create and configure the Deepgram connection
    dg_connection = dg_client.listen.live.v("1")
    options = LiveOptions(model="nova-2", language="en-US", interim_results=True, smart_format=True, endpointing='700',
                          utterance_end_ms='1000', filler_words=True)

    # Define event handlers
    def on_message(self, result, **kwargs):
        print("Received message from Deepgram:", result)
        if result:
            sentence = result.channel.alternatives[0].transcript
            if sentence:
                # Run sio_server.emit in the event loop
                asyncio.run(sio_server.emit('downlink_stt_result', {'text': sentence, 'is_final': result.is_final,
                                                                    'speech_final': result.speech_final}, room=sid))

    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)

    # Start the connection
    dg_connection.start(options)
    user_sessions[sid] = dg_connection


@sio_server.event
async def connect(sid, environ, auth):
    access_token = auth.get("token")
    if access_token != runner_access_token:
        await sio_server.disconnect(sid)
        print("invalid access token")
        return
    print("Client connected:", sid)
    # Schedule start_transcription to run on the event loop
    transcription_tasks[sid] = asyncio.create_task(start_transcription(sid))
    return True


@sio_server.event
async def message(sid, data):
    print(sid, data)
    await sio_server.emit("response", data + "112")
    return True


@sio_server.event
async def uplink_stt_audio(sid, audio_data):
    # This event will be triggered by the frontend to send audio data to Deepgram
    print("Received audio data from client:", sid)
    if sid in user_sessions:
        user_sessions[sid].send(audio_data)


@sio_server.event
async def disconnect(sid):
    print("Client disconnected:", sid)
    if sid in user_sessions:
        user_sessions[sid].finish()  # Close the Deepgram connection
        del user_sessions[sid]  # Remove the session from the dictionary
    if sid in transcription_tasks:
        transcription_tasks[sid].cancel()
        del transcription_tasks[sid]
    return True


@app.get("/")
async def root():
    return {"message": "Hello World"}
