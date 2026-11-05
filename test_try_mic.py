import io
import wave
from unittest.mock import patch

import numpy as np

from try_mic import CHUNK, MAX_CHUNKS, RATE, utterances


def sound(rms, seconds, rng):
    return rng.normal(0, rms * 32768, int(RATE * seconds)).astype("<i2")


def listener(stream, calls, over_at=None):
    def listen(audio):
        with wave.open(io.BytesIO(audio), "rb") as wav:
            assert wav.getparams()[:3] == (1, 2, RATE)
            calls.append((stream.tell() // 2, wav.readframes(wav.getnframes())))
        return {"text": "", "over": over_at is not None and len(calls[-1][1]) >= over_at * RATE * 2,
                "commands": [], "raw": [], "ms": {"asr": 0, "decide": 0, "total": 0}}
    return listen


rng = np.random.default_rng(0)
noise, speech, soft = 0.005, 0.04, 0.012
stream = io.BytesIO(np.concatenate([sound(noise, 1, rng), sound(speech, 0.5, rng),
                                   sound(soft, 1.5, rng), sound(speech, 0.5, rng)]).tobytes())
calls = []
results = utterances(stream, listener(stream, calls, over_at=2.5))
assert next(results)["over"] is True and stream.tell() < len(stream.getvalue())
assert list(results) == []

pcm = np.concatenate([sound(noise, 1, rng), sound(speech, 0.5, rng), sound(noise, 5, rng),
                      sound(soft, 1.5, rng), sound(speech, 0.5, rng)])
stream, calls = io.BytesIO(pcm.tobytes()), []
assert list(utterances(stream, listener(stream, calls))) == []
assert not any(2.7 * RATE < position <= 6.5 * RATE for position, _ in calls)
position, audio = calls[-1]
assert int(3.95 * RATE) - 6 * CHUNK <= len(audio) // 2 <= int(3.95 * RATE)
assert audio == np.concatenate([pcm[int(0.75 * RATE):int(2.7 * RATE)], pcm[int(6.5 * RATE):position]]).tobytes()

pcm = np.concatenate([sound(noise, 1, rng), sound(speech, 40, rng)])
stream, calls = io.BytesIO(pcm.tobytes()), []
assert list(utterances(stream, listener(stream, calls))) == []
assert max(len(audio) for _, audio in calls) == MAX_CHUNKS * CHUNK * 2
assert calls[-1][0] > 40 * RATE

pcm = np.concatenate([sound(noise, 1, rng), sound(speech, 0.5, rng), sound(noise, 1, rng),
                      sound(speech, 0.5, rng), sound(noise, 1, rng)])
stream, calls = io.BytesIO(pcm.tobytes()), []
assert len(list(utterances(stream, listener(stream, calls, over_at=0.85)))) == 2

pcm = np.concatenate([sound(noise, 1, rng), sound(speech, 1.5, rng)])
stream, calls = io.BytesIO(pcm.tobytes()), []
with patch("try_mic.perf_counter", side_effect=[0, 0.51, 1, 1.51, 2, 2.51]):
    assert list(utterances(stream, listener(stream, calls))) == []
assert [len(audio) // (CHUNK * 2) for _, audio in calls] == [12, 23, 34]
print("try_mic tests passed")
