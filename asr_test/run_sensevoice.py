# /// script
# requires-python = "==3.12.11"
# dependencies = ["funasr==1.4.16", "torch==2.8.0", "torchaudio==2.8.0", "numpy==2.2.6"]
# ///
"""uv run asr_test/run_sensevoice.py [--audio-dir 폴더] [--out 결과.md] [--device cpu|mps]"""
import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import decode_audio

ROBOTS = "빨강이 빨강 빨간 레드 블루 파랑이 파랑 파란 초록이 초록 그린".split()
CORRECTIONS = "아니 말고 잠깐 취소".split()
TERMS = ROBOTS + "오른쪽 왼쪽 앞 뒤 위 아래 우측 좌측 전진 후진 반시계 시계".split() + CORRECTIONS + "칸 미터 도 걸음".split()


def cer(reference, output):
    reference, output = (re.sub(r"[\s.,?!…]", "", s) for s in (reference, output))
    row = list(range(len(output) + 1))
    for i, a in enumerate(reference, 1):
        new = [i]
        for j, b in enumerate(output, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = new
    return row[-1] / max(1, len(reference))


def missing(reference, output):
    reference, output = (re.sub(r"\s", "", s) for s in (reference, output))
    return [term for term in TERMS if output.count(term) < reference.count(term)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", type=Path, default=Path("asr_test/recordings"))
    parser.add_argument("--out", type=Path, default=Path("asr_test/results_sensevoice.md"))
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    args = parser.parse_args()
    sentences = [json.loads(line) for line in Path(__file__).with_name("sentences.jsonl").read_text(encoding="utf-8").splitlines()]
    audio = {}
    for path in sorted(args.audio_dir.iterdir()):
        if path.is_file() and path.suffix.lower() == ".wav":
            if path.stem in audio:
                parser.error(f"같은 id의 음성이 여러 개입니다: {path.stem}")
            audio[path.stem] = path
    sentences = [s for s in sentences if s["id"] in audio]
    if not sentences:
        parser.error("문장 id와 일치하는 음성이 없습니다.")

    import torch
    from funasr import AutoModel

    model = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf", device=args.device,
                      disable_update=True, disable_pbar=True, disable_log=True)
    device = next(model.model.parameters()).device.type
    if device != args.device:
        parser.error(f"요청한 {args.device} 대신 {device}로 모델이 로드되었습니다. --device cpu를 사용하세요.")

    def transcribe(samples, itn):
        if device == "mps":
            torch.mps.synchronize()
        start = perf_counter()
        result = model.generate(input=samples, cache={}, language="ko", use_itn=itn)
        if device == "mps":
            torch.mps.synchronize()
        seconds = perf_counter() - start
        return re.sub(r"<\|.*?\|>", "", result[0]["text"]).strip(), seconds

    transcribe(decode_audio(audio[sentences[0]["id"]].read_bytes()), False)  # 첫 호출의 초기화 시간은 측정에서 제외
    rows, errors, omissions, mismatches, durations = [], [], [], [], []
    times = {False: [], True: []}
    for s in sentences:
        samples = decode_audio(audio[s["id"]].read_bytes())
        durations.append(len(samples) / 16000)
        off, t_off = transcribe(samples, False)
        on, t_on = transcribe(samples, True)
        times[False].append(t_off)
        times[True].append(t_on)
        errors.append(cer(s["text"], off))
        omissions.append(missing(s["text"], off))
        numbers = [int(n) for n in re.findall(r"\d+", on)]
        mismatches.append(numbers != s["numbers"])
        number_result = f"expected {s['numbers']} got {numbers}" if mismatches[-1] else "OK"
        cells = [s["id"], s["text"], off, on, f"{errors[-1]:.2%}", ", ".join(omissions[-1]) or "없음",
                 number_result, f"audio {durations[-1]:.3f} / off {t_off:.3f} / on {t_on:.3f}"]
        rows.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", "<br>") for c in cells) + " |")
        print(f"[{s['id']}] off {t_off:.3f}s / on {t_on:.3f}s", flush=True)
    summary = (f"- device: {device}\n- file count: {len(rows)}\n- mean CER: {mean(errors):.2%}\n"
               f"- missing correction utterances: {sum(bool(set(m) & set(CORRECTIONS)) for m in omissions)}\n"
               f"- missing robot utterances: {sum(bool(set(m) & set(ROBOTS)) for m in omissions)}\n"
               f"- numbers mismatch utterances: {sum(mismatches)}\n"
               f"- ITN off seconds/call: mean {mean(times[False]):.3f}, max {max(times[False]):.3f}\n"
               f"- ITN on seconds/call: mean {mean(times[True]):.3f}, max {max(times[True]):.3f}\n"
               f"- mean audio duration: {mean(durations):.3f}s")
    header = "| id | 읽은 문장 | ITN off | ITN on | CER | 빠진 단어 | 숫자 | 시간(초) |\n| --- | --- | --- | --- | --- | --- | --- | --- |"
    args.out.write_text(f"# SenseVoiceSmall\n\n{summary}\n\n{header}\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    assert cer("가 나...?!…", "가나") == 0 and cer("가나다", "가라") == 2 / 3
    assert missing("빨강이 빨강이 아니 말고", "빨 강 이 말 고") == ["빨강이", "빨강", "아니"]
    main()
