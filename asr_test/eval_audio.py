import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import DEVICES, load_models, process_audio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=DEVICES, default="auto")
    parser.add_argument("--audio-dir", type=Path, default=Path(__file__).parent / "recordings")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    here = Path(__file__).parent
    gold = {row["id"]: row["commands"] for row in
            map(json.loads, (here / "sentences.jsonl").read_text(encoding="utf-8").splitlines())}
    recordings = sorted(args.audio_dir.glob("*.wav"))
    if {path.stem for path in recordings} != set(gold):
        parser.error("녹음 파일과 정답 문장의 id가 일치하지 않습니다.")
    models, lock = load_models(args.model, args.device), Lock()
    lines, timings, exact, results = [], [], 0, {}

    def log(text):
        print(text, flush=True)
        lines.append(text)

    log(f"model: {args.model}")
    log(f"device: {models[1].device.type}")
    for path in recordings:
        result = process_audio(path.read_bytes(), models, lock)
        results[path.stem] = {"text": result["text"], "raw": result["raw"]}
        ok = result["raw"] == gold[path.stem]
        exact += ok
        timings.append(result["ms"])
        log(f"{path.stem} {'OK' if ok else 'NG'}")
        if not ok:
            log(f"  ASR: {result['text']}")
            log(f"  predicted: {json.dumps(result['raw'], ensure_ascii=False)}")
            log(f"  gold: {json.dumps(gold[path.stem], ensure_ascii=False)}")
    log(f"exact: {exact}/{len(recordings)} ({exact / len(recordings):.2%})")
    for stage in ("asr", "decide", "total"):
        values = [t[stage] for t in timings]
        log(f"{stage} ms: mean {mean(values):.2f}, max {max(values):.2f}")
    (here / "results_e2e.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
