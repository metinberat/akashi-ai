import asyncio
import os
import threading
import audioop
from pathlib import Path

import sounddevice as sd
from dotenv import load_dotenv
from google import genai
from google.genai import types


ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / "backend" / ".env")

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

SEND_RATE = 16000
RECEIVE_RATE = 24000
CHANNELS = 1
CHUNK = 1024


async def main():
    if not API_KEY:
        raise RuntimeError("Gemini API key backend/.env içinde bulunamadı.")

    client = genai.Client(
        api_key=API_KEY,
        http_options={"api_version": "v1beta"},
    )

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=(
            "You are AKASHI. "
            "You are calm, strategic, precise and confident. "
            "Speak naturally and concisely. "
            "Reply in the user's language."
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Charon"
                )
            )
        ),
    )

    print("Gemini Live bağlanıyor...")

    async with client.aio.live.connect(
        model=MODEL,
        config=config,
    ) as session:

        print("AKASHI LISTENING")

        mic_queue = asyncio.Queue()
        audio_queue = asyncio.Queue()

        speaking = threading.Event()
        turn_done = asyncio.Event()

        loop = asyncio.get_running_loop()

        def mic_callback(indata, frames, time_info, status):
            if speaking.is_set():
                 return

            data = indata.tobytes()

            loop.call_soon_threadsafe(
                 mic_queue.put_nowait,
                {
                     "data": data,
                     "mime_type": "audio/pcm",
              },
         )
            

        async def send_audio():
            while True:
                chunk = await mic_queue.get()
                await session.send_realtime_input(media=chunk)

        async def microphone():
            with sd.InputStream(
                samplerate=SEND_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK,
                callback=mic_callback,
            ):
                print("MIC OPEN")
                while True:
                    await asyncio.sleep(0.1)

        async def receive():
            while True:
                async for response in session.receive():

                    if response.data:
                        speaking.set()
                        turn_done.clear()
                        audio_queue.put_nowait(response.data)

                    if (
                         response.server_content
                        and response.server_content.turn_complete
                     ):
                        turn_done.set()

        async def playback():
            stream = sd.RawOutputStream(
                samplerate=RECEIVE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK,
            )

            stream.start()

            try:
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            audio_queue.get(),
                            timeout=0.05,
                        )

                        speaking.set()
                        chunk = audioop.mul(chunk, 2, 0.35)
                        await asyncio.to_thread(stream.write, chunk)

                    except asyncio.TimeoutError:
                        if turn_done.is_set() and audio_queue.empty():
                            speaking.clear()
                            turn_done.clear()

            finally:
                stream.stop()
                stream.close()

        await asyncio.gather(
            send_audio(),
            microphone(),
            receive(),
            playback(),
        )


if __name__ == "__main__":
    asyncio.run(main())