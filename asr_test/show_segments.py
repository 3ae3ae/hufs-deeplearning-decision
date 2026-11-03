import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import normalize_numbers, split


here = Path(__file__).parent
asr = {}
for line in (here / "results_sensevoice.md").read_text(encoding="utf-8").splitlines():
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if cells[0].isdigit():
        assert len(cells) == 8, line
        assert cells[0] not in asr, cells[0]
        asr[cells[0]] = cells[2]

blocks = []
for line in (here / "sentences.jsonl").read_text(encoding="utf-8").splitlines():
    sentence = json.loads(line)
    lines = [f"## {sentence['id']}"]
    for label, text in [("REF", sentence["text"]), ("ASR", asr[sentence["id"]])]:
        text = normalize_numbers(text)
        lines.extend([f"{label}  {text}", "     [" + " | ".join(split(text)) + "]"])
    blocks.append("\n".join(lines))

(here / "segments_report.md").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
