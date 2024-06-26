import hashlib
import time
import json
from dotenv import load_dotenv, dotenv_values
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import socketio
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from openai import OpenAI
from anthropic import Anthropic
import os
import re
import asyncio
from io import BytesIO
from ChatStream import ChatStream, ChatStreamModel
from TtsStream import TtsStream
from AgentPromptHandler import AgentPromptHandler
import requests

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
dg_client = DeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
agent_prompt_handler = AgentPromptHandler()

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
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:5173",
    "http://localhost:5172",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "https://prepit-user-web.vercel.app",
    "https://app.prepit.ai",
    "https://test-app.prepit.ai",
    "https://prepit.ai",
    "https://interview.prepit.ai",
]

regex_origins = "https://.*jerryyang666s-projects\.vercel\.app"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=regex_origins,
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
audio_buffers = {}
chat_tasks = {}  # Dictionary to store active chat tasks
user_ids = {}  # Dictionary to store user IDs
thread_ids = {}  # Dictionary to store thread IDs
recording_processing_data_packets = {}  # Dictionary to store recording processing data packets

last_audio_data_received_timestamp = {}  # Dictionary to store the last audio data received timestamp


async def start_transcription(sid):
    # Create and configure the Deepgram connection
    dg_connection = dg_client.listen.live.v("1")
    options = LiveOptions(model="nova-2", language="en-US", interim_results=True, smart_format=True, endpointing='600',
                          utterance_end_ms='1000', filler_words=True)

    # Define event handlers
    def on_message(self, result, **kwargs):
        if result:
            sentence = result.channel.alternatives[0].transcript
            if sentence:
                # Run sio_server.emit in the event loop
                parsed_result = {'text': sentence, 'is_final': result.is_final, 'speech_final': result.speech_final,
                                 'start': result.start, 'duration': result.duration,
                                 'timestamp': get_unix_timestamp_ms()}
                asyncio.run(sio_server.emit('downlink_stt_result', parsed_result, room=sid))
                recording_processing_data_packets[sid]["audio_timestamps"].append(parsed_result)

    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)

    # Start the connection
    dg_connection.start(options)
    user_sessions[sid] = dg_connection


def generate_dynamic_auth_code():
    step = 30  # dynamic auth token 30 seconds window
    salt = "prepit_jerry_salt"  # Salt for the dynamic auth token
    time_step = int(time.time() // step)
    time_based_key = str(time_step) + salt  # Combine time step with salt
    return hashlib.sha256(time_based_key.encode()).hexdigest()


def get_unix_timestamp_ms() -> int:
    """
    Get the current Unix timestamp in milliseconds.
    :return: The current Unix timestamp in milliseconds.
    """
    return int(time.time() * 1000)


@sio_server.event
async def connect(sid, environ, auth):
    access_token = auth.get("token")
    print("checking interview ID: ", access_token)
    if check_uuid_format(access_token):
        # send a post request to the backend to check if the interview ID is valid
        # the post body should be {thread_id: str, dynamic_auth_code: str}
        response = requests.post("https://api.prepit-ai.com/v1/prod/admin/threads/validate_id",
                                 json={"thread_id": access_token,
                                       "dynamic_auth_code": generate_dynamic_auth_code()})
        if response.status_code == 200:
            agent_id = response.json().get("data").get("agent_id")
            user_id = response.json().get("data").get("user_id")
            user_ids[sid] = user_id
            thread_ids[sid] = access_token
            recording_processing_data_packets[sid] = {
                "thread_id": access_token,
                "ws_conn_sid": sid,
                "ws_conn_started": get_unix_timestamp_ms(),
                "audio_started": False,
                "audio_timestamps": [],
                "audio_pause_timestamps": [],
                "user_msg_timestamps": {},
            }  # Initialize the data packet
            print("agent_id:", agent_id)
            await sio_server.emit("downlink_interview_id_check_success", room=sid, data={"agent_id": agent_id})
            print("valid interview ID:", access_token)
        else:
            await sio_server.emit("downlink_interview_id_check_fail", room=sid)
            await sio_server.disconnect(sid)
            print("invalid interview ID:", access_token)
            return False
        agent_prompt_handler.cache_agent_all_steps(agent_id)
        print("Client connected:", sid)
        # Schedule start_transcription to run on the event loop
        transcription_tasks[sid] = asyncio.create_task(start_transcription(sid))

        # Initialize an in-memory buffer for audio data
        audio_buffers[sid] = BytesIO()

        return True
    return False


def check_uuid_format(uuid: str) -> bool:
    """
    Checks if the UUID is in the correct format.
    :param uuid: The UUID to check.
    :return: True if the UUID is in the correct format, False otherwise.
    """
    return re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", uuid) is not None


@sio_server.event
async def message(sid, data):
    print(sid, data)
    await sio_server.emit("response", data + "112")
    return True


@sio_server.event
async def uplink_stt_audio(sid, audio_data):
    # This event will be triggered by the frontend to send audio data to Deepgram
    print("Received audio data from client:", sid, "audio_data length:", len(audio_data))
    if sid in user_sessions:
        user_sessions[sid].send(audio_data)
        if sid in recording_processing_data_packets and not recording_processing_data_packets[sid]["audio_started"]:
            recording_processing_data_packets[sid]["audio_started"] = True
            recording_processing_data_packets[sid]["audio_started_at"] = get_unix_timestamp_ms()
        last_audio = last_audio_data_received_timestamp.get(sid, 0)
        time_now = get_unix_timestamp_ms()
        last_audio_data_received_timestamp[sid] = time_now
        if last_audio != 0 and time_now - last_audio > 1500:
            recording_processing_data_packets[sid]["audio_pause_timestamps"].append([last_audio, time_now])

        # Append the audio data to the in-memory buffer
        if sid in audio_buffers:
            audio_buffers[sid].write(audio_data)


@sio_server.event
async def uplink_chat_message(sid, message_data):
    print("Received chat message from client:", sid, message_data)

    chat_stream_model = ChatStreamModel(
        dynamic_auth_code=message_data['dynamic_auth_code'],
        messages=message_data['messages'],
        current_step=message_data['current_step'],
        agent_id=message_data['agent_id'],
        provider=message_data['provider'],
        thread_id=message_data['thread_id']
    )
    chat_stream = ChatStream(sio_server, openai_client, anthropic_client)
    user_msg_timestamp = chat_stream.user_message_timestamp
    user_msg_id = message_data['thread_id'][:8] + '#' + str(user_msg_timestamp)
    recording_processing_data_packets[sid]["user_msg_timestamps"][user_msg_timestamp] = user_msg_id
    user_id = user_ids[sid] if sid in user_ids else "0"

    # Run stream_chat as an independent task
    task = asyncio.create_task(
        chat_stream.stream_chat(chat_stream_model, chat_stream_model.provider, chat_stream_model.current_step,
                                chat_stream_model.agent_id, sid, user_id))
    chat_tasks[sid] = task

    # Add a callback to remove the task from the dictionary once it is done
    task.add_done_callback(lambda t: chat_tasks.pop(sid, None))

    return True


@sio_server.event
async def uplink_keep_alive(sid):
    print("Received keep alive from client:", sid)
    if sid in user_sessions:
        user_sessions[sid].send('{ "type": "KeepAlive" }')


@sio_server.event
async def disconnect(sid):
    print("Client disconnected:", sid)
    audio_file_folder = "volume_cache/interviewee_recordings"
    if sid in user_sessions:
        user_sessions[sid].finish()  # Close the Deepgram connection
        del user_sessions[sid]  # Remove the session from the dictionary
    if sid in transcription_tasks:
        transcription_tasks[sid].cancel()
        del transcription_tasks[sid]
    if sid in user_ids:
        del user_ids[sid]
    if sid in last_audio_data_received_timestamp:
        del last_audio_data_received_timestamp[sid]

    if sid in audio_buffers and audio_buffers[sid].getbuffer().nbytes > 0:
        # check if the folder exists
        if not os.path.exists(audio_file_folder):
            os.makedirs(audio_file_folder)
        # get the current thread id and concatenate it with the sid
        recording_id = thread_ids[sid][0:8] + "_" + sid
        # Write the buffer to a file
        with open(f"{audio_file_folder}/{recording_id}.wav", "wb") as audio_file:
            audio_file.write(audio_buffers[sid].getvalue())

        if sid in recording_processing_data_packets:
            recording_processing_data_packets[sid]["ws_conn_finished"] = get_unix_timestamp_ms()
            recording_processing_data_packets[sid]["recording_id"] = recording_id
            # Save the recording processing data packet to a json file
            with open(f"{audio_file_folder}/{recording_id}.json", "w") as data_file:
                json.dump(recording_processing_data_packets[sid], data_file)
            del recording_processing_data_packets[sid]
        del audio_buffers[sid]
        del thread_ids[sid]

    if sid in chat_tasks:
        chat_tasks[sid].cancel()
        del chat_tasks[sid]
    return True


def delete_file_after_delay(file_path: str, delay: float):
    """
    Deletes the specified file after a delay.
    :param file_path: The path to the file to delete.
    :param delay: The delay before deletion, in seconds.
    """
    time.sleep(delay)
    if os.path.isfile(file_path):
        os.remove(file_path)


@app.get(f"{CURRENT_VERSION_PREFIX}{DEV_PREFIX}/tts")
@app.get(f"{CURRENT_VERSION_PREFIX}{PROD_PREFIX}/tts")
async def get_tts_file(tts_session_id: str, chunk_id: str, background_tasks: BackgroundTasks):
    """
    ENDPOINT: /v1/dev/tts
    serves the TTS audio file for the specified session id and chunk id.
    :param tts_session_id:
    :param chunk_id:
    :param background_tasks:
    :return:
    """
    file_location = f"{TtsStream.TTS_AUDIO_CACHE_FOLDER}/{tts_session_id}_{chunk_id}.mp3"
    if os.path.isfile(file_location):
        # Add the delete_file_after_delay function as a background task
        background_tasks.add_task(delete_file_after_delay, file_location, 60)  # 60 seconds delay
        return FileResponse(path=file_location, media_type="audio/mpeg")
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.get(f"{CURRENT_VERSION_PREFIX}{DEV_PREFIX}/ping")
@app.get(f"{CURRENT_VERSION_PREFIX}{PROD_PREFIX}/ping")
async def ping():
    return {"message": "Hello World"}
