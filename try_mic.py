"""마이크로 말하면 인식한 문장과 명령을 터미널에 찍는다 (Unity 없이 시험용).

사용법: uv run python try_mic.py [마이크] [장치]     예) uv run python try_mic.py :1 cpu
마이크 번호 확인: ffmpeg -f avfoundation -list_devices true -i ""
말 감지는 Unity 패키지와 같다: 소리 크기 0.02 이상이면 듣기 시작, "오버"가 들리면 바로 변환. 무음으로는 끝내지 않고, 말 사이의 무음은 1.2초까지만 남기고 잘라 낸다.
"""
import io
import subprocess
import sys
import wave
from math import ceil
from threading import Lock
from time import perf_counter

import numpy as np

import server

RATE, CHUNK = 16000, 800  # 50ms 단위로 소리 크기를 본다
START_LEVEL, SILENCE_CHUNKS, PREROLL_CHUNKS = 0.02, 24, 6
PARTIAL_CHUNKS, MAX_CHUNKS = 6, 600


def utterances(stream, listen):
    preroll, recording, quiet, noise = [], None, 0, None
    chunks_since_last_call, duration = 0, 0
    while (data := stream.read(CHUNK * 2)) and len(data) == CHUNK * 2:
        rms = np.sqrt(np.mean((np.frombuffer(data, "<i2") / 32768.0) ** 2))
        if recording is None:
            preroll = (preroll + [data])[-PREROLL_CHUNKS:]
            if rms >= START_LEVEL:
                recording, quiet = preroll, 0
                chunks_since_last_call = 0
                print("듣는 중…", flush=True)
            else:
                noise = rms if noise is None else 0.95 * noise + 0.05 * rms
            continue
        # 말하는 중에는 방 잡음의 2배만 넘어도 계속 말하는 것으로 본다: 작게 말한 "아 아니다"에서 끊기지 않게
        speaking = rms >= min(START_LEVEL, max(2 * (noise or 0), 0.003))
        # 오래 생각해도 녹음이 끊기지 않게 하되, 긴 무음은 잘라 내 다시 인식할 소리를 짧게 유지한다
        if not speaking and quiet >= SILENCE_CHUNKS:
            continue
        recording.append(data)
        # '오버' 없이 30초 넘게 말하면 오래된 소리부터 버린다
        recording = recording[-MAX_CHUNKS:]
        chunks_since_last_call += 1
        quiet = 0 if speaking else quiet + 1
        # 인식이 느린 장치(CPU)에서 밀리지 않게, 인식에 걸린 시간보다 짧은 간격으로는 다시 묻지 않는다
        if chunks_since_last_call < max(PARTIAL_CHUNKS, ceil(duration / 0.05)):
            continue
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1), out.setsampwidth(2), out.setframerate(RATE)
            out.writeframes(b"".join(recording))
        audio = buffer.getvalue()
        began = perf_counter()
        result = listen(audio)
        duration = perf_counter() - began
        chunks_since_last_call = 0
        if result["over"]:
            yield result
            recording, preroll = None, []


def main():
    mic = sys.argv[1] if len(sys.argv) > 1 else ":1"  # 이 맥에서 확인한 마이크 번호
    device = sys.argv[2] if len(sys.argv) > 2 else "auto"
    if device not in server.DEVICES:
        sys.exit(f"장치는 {', '.join(server.DEVICES)} 중 하나여야 합니다.")
    print("모델 불러오는 중…", flush=True)
    models, lock = server.load_models("models/laya-commands", device), Lock()
    ffmpeg = subprocess.Popen(["ffmpeg", "-v", "error", "-f", "avfoundation", "-i", mic,
                               "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE)
    print(f"준비되었습니다 ({models[1].device.type}). 말씀하십시오 (종료: Ctrl+C)\n", flush=True)
    try:
        for result in utterances(ffmpeg.stdout, lambda audio: server.process_audio(audio, models, lock, partial=True)):
            print(f"인식: {result['text']}")
            for command in result["raw"]:
                print(f"  {command}")
            print(f"  ({result['ms']['total']:.0f}ms)\n", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        ffmpeg.terminate()


if __name__ == "__main__":
    main()
