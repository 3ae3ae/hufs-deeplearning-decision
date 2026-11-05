import argparse
import io
import json
import os
import re
import struct
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from time import perf_counter

import numpy as np
import torch

import pipeline


MAX_BYTES = 10_000_000
SAMPLE_RATE = 16000
MAX_SECONDS = 60
DEVICES = ("auto", "cpu", "mps", "cuda")


# 인식기는 "오버"를 "오브"로 적기도 하고, 실제 발음은 "오바"인 경우가 많다. 띄어쓰기를 빼먹으므로("돌아오버") 앞뒤 경계는 보지 않는다. '오버' 뒤는 다음 말의 시작이거나 잡음이라 버린다
OVER = re.compile("오[버브바]")


def split_over(text):
    match = OVER.search(text)
    if match is None:
        return text, False
    return re.sub(r"[\s.,?!…]+$", "", text[:match.start()]), True


class BadAudio(ValueError):
    pass


def choose_device(device):
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def synchronize(device):
    if device == "cuda":
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


def load_models(model_dir, device="auto"):
    if not (Path(model_dir) / "model.safetensors").is_file():
        raise FileNotFoundError(f"모델 파일이 없습니다: {model_dir}")
    import laya
    from funasr import AutoModel

    device = choose_device(device)
    asr = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf", device=device, ncpu=os.cpu_count(),
                    disable_update=True, disable_pbar=True, disable_log=True)
    agent = laya.load(str(Path(model_dir).resolve()), device=device)
    if next(asr.model.parameters()).device.type != device or agent.device.type != device:
        raise RuntimeError(f"모델이 요청한 {device}에 로드되지 않았습니다.")
    with torch.inference_mode():
        asr.generate(input=np.zeros(SAMPLE_RATE, dtype=np.float32), cache={}, language="ko", use_itn=False)
        states = [state for _, state in pipeline.windows("빨강이 앞으로 2칸 가")]
        agent.predict_batch(states, pipeline.QUESTIONS, batch_size=4)
        synchronize(device)
    return asr, agent


def decode_audio(audio):
    if not 0 < len(audio) <= MAX_BYTES:
        raise BadAudio("오디오는 0바이트 초과, 10 MB 이하여야 합니다.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            channels, width, rate, frames, compression, _ = wav.getparams()
            if channels not in (1, 2) or width != 2 or compression != "NONE" or rate <= 0 or frames == 0:
                raise BadAudio("16비트 PCM 모노 또는 스테레오 WAV가 필요합니다.")
            if frames > rate * MAX_SECONDS:
                raise BadAudio("오디오는 60초 이하여야 합니다.")
            raw = wav.readframes(frames + 1)
    except (wave.Error, EOFError, struct.error, RuntimeError) as exc:
        raise BadAudio("WAV 오디오를 디코딩할 수 없습니다.") from exc
    if len(raw) != frames * channels * width:
        raise BadAudio("WAV 오디오가 잘렸거나 샘플 길이가 잘못되었습니다.")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32).reshape(-1, channels).mean(axis=1) / 32768
    if rate != SAMPLE_RATE:
        count = max(1, round(frames * SAMPLE_RATE / rate))
        samples = np.interp(np.arange(count) * (rate / SAMPLE_RATE), np.arange(frames), samples).astype(np.float32)
    if len(samples) > SAMPLE_RATE * MAX_SECONDS:
        raise BadAudio("오디오는 60초 이하여야 합니다.")
    if not np.isfinite(samples).all():
        raise BadAudio("오디오에 유효하지 않은 샘플이 있습니다.")
    return samples


def command_object(command):
    fields = {"Select": ("id",), "Move": ("direction", "amount"), "Rotate": ("way", "amount"),
              "Interact": (), "ResetGame": (), "ExitGame": ()}
    op, arguments = command[:-1].split("(", 1)
    return {"op": op, **dict(zip(fields[op], json.loads("[" + arguments + "]"), strict=True))}


def process_audio(audio, models, lock, partial=False):
    began = perf_counter()
    samples = decode_audio(audio)
    asr, agent = models
    with lock, torch.inference_mode():
        synchronize(agent.device.type)
        start_asr = perf_counter()
        result = asr.generate(input=samples, cache={}, language="ko", use_itn=False)
        text = re.sub(r"<\|.*?\|>", "", result[0]["text"]).strip()
        text, over = split_over(text)
        synchronize(agent.device.type)
        end_asr = perf_counter()
        if partial and not over:
            return {"text": text, "over": False, "commands": [], "raw": [],
                    "ms": {"asr": round((end_asr - start_asr) * 1000, 2), "decide": 0,
                           "total": round((end_asr - began) * 1000, 2)}}
        windows = pipeline.windows(pipeline.normalize_numbers(text))
        predictions = agent.predict_batch([state for _, state in windows], pipeline.QUESTIONS, batch_size=4)
        segments = [(segment, *(prediction["answers"][q]["choice"] for q in ("robot", "action", "direction")))
                    for (segment, _), prediction in zip(windows, predictions, strict=True)]
        raw = pipeline.assemble(segments)
        commands = [command_object(command) for command in raw]
        synchronize(agent.device.type)
        end = perf_counter()
    return {"text": text, "over": over, "commands": commands, "raw": raw,
            "ms": {"asr": round((end_asr - start_asr) * 1000, 2),
                   "decide": round((end - end_asr) * 1000, 2), "total": round((end - began) * 1000, 2)}}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200, {"ok": True}) if self.path == "/health" else self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/command", "/listen"):
            self.reply(404, {"error": "Not found"})
            return
        try:
            self.connection.settimeout(30)
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or self.headers.get("Transfer-Encoding"):
                raise BadAudio("Content-Length가 하나 필요합니다. 청크 전송은 지원하지 않습니다.")
            try:
                length = int(lengths[0])
            except ValueError as exc:
                raise BadAudio("Content-Length가 유효하지 않습니다.") from exc
            if not 0 < length <= MAX_BYTES:
                raise BadAudio("오디오는 0바이트 초과, 10 MB 이하여야 합니다.")
            try:
                audio = self.rfile.read(length)
            except TimeoutError as exc:
                raise BadAudio("오디오 본문 수신 시간 초과") from exc
            if len(audio) != length:
                raise BadAudio("오디오 본문이 Content-Length보다 짧습니다.")
            # /listen: 녹음 중간에 '오버'가 나왔는지 본다. 나왔을 때만 명령까지 만든다
            result = process_audio(audio, self.server.models, self.server.model_lock, partial=self.path == "/listen")
        except BadAudio as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(500, {"error": str(exc)})
        else:
            self.reply(200, result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    # 기본은 이 컴퓨터에서만 접속 가능. 게임이 다른 PC에서 돌면 --host 0.0.0.0
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device", choices=DEVICES, default="auto")
    args = parser.parse_args()
    models = load_models(args.model, args.device)
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.models, server.model_lock = models, Lock()
        print(f"ready: http://{args.host}:{server.server_port} ({models[1].device.type})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
