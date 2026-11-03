import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import train_laya


class Agent:
    def __init__(self):
        self.states = []

    def predict(self, state, questions):
        assert questions == train_laya.pipeline.QUESTIONS
        self.states.append(state)
        values = {"robot": "red", "action": "Move", "direction": "Front"}
        if "⟦빨강이⟧" in state:
            values.update(action="none", direction="none")
        return {"answers": {q: {"choice": v} for q, v in values.items()}}


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "data").mkdir()
    (root / "colab").mkdir()
    (root / "model.safetensors").touch()
    validation = [
        {"state": "⟦명령⟧", "questions": train_laya.pipeline.QUESTIONS,
         "gold": {"robot": "red", "action": "Move", "direction": "Front"}},
        {"state": "⟦오답⟧", "questions": train_laya.pipeline.QUESTIONS,
         "gold": {"robot": "blue", "action": "none", "direction": "Right"}},
    ]
    real = [{"id": "01", "asr": "빨강이 앞으로 두칸가", "commands": ['Select("red")', 'Move("Front", 2)']},
            {"id": "02", "asr": "빨강이 앞으로 두칸가", "commands": []}]
    for path, rows in [(root / "data/val.jsonl", validation), (root / "colab/eval_real.jsonl", real)]:
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    agent, output = Agent(), io.StringIO()
    with patch.object(train_laya, "ROOT", root), patch.object(train_laya.laya, "load", return_value=agent), \
            patch.object(train_laya.torch.mps, "synchronize"), redirect_stdout(output):
        train_laya.evaluate(root)
    report = (root / "eval.md").read_text(encoding="utf-8")
    assert report == output.getvalue()
    for question in ("robot", "action", "direction", "all three"):
        assert f"{question}: 1/2 (50.00%)" in report
    assert "01 OK" in report and "02 NG" in report and "real exact: 1/2 (50.00%)" in report
    assert '  predicted: ["Select(\\"red\\")", "Move(\\"Front\\", 2)"]' in report
    assert "  gold: []" in report and "앞으로 2칸가 -> robot=red, action=Move, direction=Front" in report
    assert len(agent.states) == 16
    assert agent.states[-2:] == ["⟦빨강이⟧ 앞으로 2칸가", "빨강이 ⟦앞으로 2칸가⟧"]

print("train_laya evaluation tests passed")
