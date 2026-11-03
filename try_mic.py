"""마이크로 말하면 인식한 문장과 명령을 터미널에 찍는다 (Unity 없이 시험용).

사용법: uv run python try_mic.py [마이크] [장치]     예) uv run python try_mic.py :1 cpu
마이크 번호 확인: ffmpeg -f avfoundation -list_devices true -i ""
말 감지는 Unity 패키지와 같다: 소리 크기 0.02 이상이면 시작, 1.2초 조용하면 끝.
"""
import io
import subprocess
import sys
import wave
from threading import Lock

import numpy as np

import server

RATE, CHUNK = 16000, 800  # 50ms 단위로 소리 크기를 본다
START_LEVEL, SILENCE_CHUNKS, PREROLL_CHUNKS = 0.02, 24, 6


def utterances(stream):
    """stream(16kHz 모노 16비트)에서 말 한 덩어리씩 잘라 WAV 바이트로 돌려준다."""
    preroll, recording, quiet, noise = [], None, 0, None
    while (data := stream.read(CHUNK * 2)) and len(data) == CHUNK * 2:
        rms = np.sqrt(np.mean((np.frombuffer(data, "<i2") / 32768.0) ** 2))
        if recording is None:
            preroll = (preroll + [data])[-PREROLL_CHUNKS:]
            if rms >= START_LEVEL:
                recording, quiet = preroll, 0
                print("듣는 중…", flush=True)
            else:
                noise = rms if noise is None else 0.95 * noise + 0.05 * rms
            continue
        recording.append(data)
        # 말하는 중에는 방 잡음의 2배만 넘어도 계속 말하는 것으로 본다: 작게 말한 "아 아니다"에서 끊기지 않게
        quiet = 0 if rms >= min(START_LEVEL, max(2 * (noise or 0), 0.003)) else quiet + 1
        if quiet >= SILENCE_CHUNKS:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as out:
                out.setnchannels(1), out.setsampwidth(2), out.setframerate(RATE)
                out.writeframes(b"".join(recording))
            yield buffer.getvalue()
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
        for audio in utterances(ffmpeg.stdout):
            result = server.process_audio(audio, models, lock)
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
