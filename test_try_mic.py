import io

import numpy as np

from try_mic import utterances


def sound(rms, seconds, rng):
    return rng.normal(0, rms * 32768, int(16000 * seconds)).astype("<i2")


rng = np.random.default_rng(0)
noise, speech, soft = 0.005, 0.04, 0.012  # soft: 기준 0.02보다 작지만 잡음의 2배보다 큰 작은 말소리
stream = np.concatenate([sound(noise, 1, rng), sound(speech, 0.5, rng), sound(soft, 1.5, rng),
                         sound(speech, 0.5, rng), sound(noise, 2, rng)])
assert len(list(utterances(io.BytesIO(stream.tobytes())))) == 1
# 조용해지면 끝난다
stream = np.concatenate([sound(noise, 1, rng), sound(speech, 0.5, rng), sound(noise, 2, rng),
                         sound(speech, 0.5, rng), sound(noise, 2, rng)])
assert len(list(utterances(io.BytesIO(stream.tobytes())))) == 2
print("try_mic tests passed")
