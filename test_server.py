import io
import json
import wave
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace
from unittest.mock import patch

import server


for text, expected in (
    ("빨강이 앞으로 두칸가 오버", ("빨강이 앞으로 두칸가", True)),
    ("빨강이 가오버 파랑이", ("빨강이 가", True)),
    ("파랑이 돌아오브", ("파랑이 돌아", True)),
    ("빨강이 가 오바", ("빨강이 가", True)),
    ("빨강이 가.", ("빨강이 가.", False)),
    ("오버", ("", True)),
    ("빨강이 가.,?!… 오버 오버", ("빨강이 가", True)),
):
    assert server.split_over(text) == expected


def wav_bytes(samples, rate=16000, channels=1, width=2):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((channels, width, rate, 0, "NONE", ""))
        wav.writeframes(samples)
    return buffer.getvalue()


pcm = server.np.array([-32768, -16384, 0, 16384, 32767], dtype="<i2")
server.np.testing.assert_array_equal(server.decode_audio(wav_bytes(pcm.tobytes())), pcm.astype("float32") / 32768)
stereo = server.np.array([[-32768, 32767], [16384, 0]], dtype="<i2")
server.np.testing.assert_array_equal(server.decode_audio(wav_bytes(stereo.tobytes(), channels=2)), [-1 / 65536, 0.25])
server.np.testing.assert_array_equal(server.decode_audio(wav_bytes(pcm.tobytes(), rate=32000)), [-1, 0])
server.np.testing.assert_array_equal(server.decode_audio(wav_bytes(pcm[:2].tobytes(), rate=8000)), [-1, -0.75, -0.5, -0.5])
assert len(server.decode_audio(wav_bytes(b"\0\0" * (16000 * 60)))) == 16000 * 60
for invalid in (
    wav_bytes(b"\0\0", width=1), wav_bytes(b"\0" * 6, width=3),
    wav_bytes(b"\0" * 6, channels=3), wav_bytes(b""),
    b"RIFF" + (16).to_bytes(4, "little") + b"WAVEJUNK" + (1000).to_bytes(4, "little"),
    wav_bytes(pcm.tobytes())[:-1], wav_bytes(b"\0\0" * (8000 * 60 + 1), rate=8000),
):
    try:
        server.decode_audio(invalid)
    except server.BadAudio:
        pass
    else:
        raise AssertionError("unsupported or malformed WAV accepted")
with patch.object(server.np, "interp", return_value=server.np.array([float("nan")], dtype="float32")):
    try:
        server.decode_audio(wav_bytes(pcm.tobytes(), rate=8000))
    except server.BadAudio:
        pass
    else:
        raise AssertionError("non-finite samples accepted")


audio = (Path(__file__).parent / "asr_test/recordings/01.wav").read_bytes()
lock = Lock()


def transcribe(**kwargs):
    assert lock.locked() and kwargs["language"] == "ko" and kwargs["use_itn"] is False
    return [{"text": "<|ko|><|NEUTRAL|>빨강이 앞으로 두칸가<|Speech|>"}]


def transcribe_over(**kwargs):
    result = transcribe(**kwargs)
    result[0]["text"] = "<|ko|>빨강이 앞으로 두칸가 오버<|Speech|>"
    return result


def decide(states, questions, batch_size):
    assert lock.locked() and questions == server.pipeline.QUESTIONS and batch_size == 4
    assert states == ["⟦빨강이⟧ 앞으로 2칸가", "빨강이 ⟦앞으로 2칸가⟧"]
    values = [{"robot": "red", "action": "none", "direction": "none"},
              {"robot": "none", "action": "Move", "direction": "Front"}]
    return [{"answers": {q: {"choice": v} for q, v in row.items()}} for row in values]


models = (SimpleNamespace(generate=transcribe),
          SimpleNamespace(predict_batch=decide, device=SimpleNamespace(type="cpu")))
result = server.process_audio(audio, models, lock)
assert result["text"] == "빨강이 앞으로 두칸가"
assert result["over"] is False
assert result["raw"] == ['Select("red")', 'Move("Front", 2)']
assert result["commands"] == [{"op": "Select", "id": "red"}, {"op": "Move", "direction": "Front", "amount": 2}]
assert set(result["ms"]) == {"asr", "decide", "total"} and all(t >= 0 for t in result["ms"].values())
with patch.object(models[1], "predict_batch") as predict:
    partial = server.process_audio(audio, models, lock, partial=True)
    predict.assert_not_called()
assert partial["text"] == result["text"] and partial["over"] is False
assert partial["commands"] == partial["raw"] == [] and partial["ms"]["decide"] == 0
assert set(partial["ms"]) == {"asr", "decide", "total"} and all(t >= 0 for t in partial["ms"].values())
with patch.object(models[0], "generate", side_effect=transcribe_over):
    for partial in (False, True):
        heard = server.process_audio(audio, models, lock, partial=partial)
        assert heard["over"] is True and heard["text"] == result["text"]
        assert heard["commands"] == result["commands"] and heard["raw"] == result["raw"]
for raw, expected in [
    ('Rotate("Left", 30)', {"op": "Rotate", "way": "Left", "amount": 30}),
    ('Move("Back", -1)', {"op": "Move", "direction": "Back", "amount": -1}),
    ("Interact()", {"op": "Interact"}), ("ResetGame()", {"op": "ResetGame"}), ("ExitGame()", {"op": "ExitGame"}),
]:
    assert server.command_object(raw) == expected
for invalid in (b"", b"not audio", b"x" * (server.MAX_BYTES + 1)):
    try:
        server.decode_audio(invalid)
    except server.BadAudio:
        pass
    else:
        raise AssertionError("invalid audio accepted")
buffer = io.BytesIO()
with wave.open(buffer, "wb") as wav:
    wav.setparams((1, 2, server.SAMPLE_RATE, 0, "NONE", ""))
    wav.writeframes(b"\0\0" * (server.SAMPLE_RATE * 60 + 1))

with ThreadingHTTPServer(("127.0.0.1", 0), server.Handler) as http:
    http.models, http.model_lock = models, lock
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", http.server_port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    try:
        assert request("GET", "/health") == (200, {"ok": True})
        status, body = request("POST", "/command", audio)
        assert status == 200 and body["commands"] == result["commands"]
        assert body["over"] is False
        status, body = request("POST", "/listen", audio)
        assert status == 200 and body["over"] is False and body["commands"] == []
        with patch.object(models[0], "generate", side_effect=transcribe_over):
            status, body = request("POST", "/listen", audio)
            assert status == 200 and body["over"] is True and body["commands"] == result["commands"]
        assert request("POST", "/listen", b"not audio")[0] == 400
        assert request("POST", "/command", b"not audio")[0] == 400
        assert request("POST", "/command", buffer.getvalue())[0] == 400
        assert request("POST", "/command", b"", {"Content-Length": str(server.MAX_BYTES + 1)})[0] == 400
        assert request("POST", "/command", b"", {"Content-Length": "bad"})[0] == 400
        assert request("GET", "/missing")[0] == request("POST", "/missing")[0] == 404
        with patch.object(server, "process_audio", side_effect=RuntimeError("model failed")):
            assert request("POST", "/command", audio) == (500, {"error": "model failed"})
            assert request("POST", "/listen", audio) == (500, {"error": "model failed"})
    finally:
        http.shutdown()
        thread.join()

print("server tests passed (CPU)")
