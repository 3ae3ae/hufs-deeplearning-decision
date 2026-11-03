# /// script
# requires-python = "==3.12.11"
# dependencies = ["funasr==1.4.16", "torch==2.8.0", "torchaudio==2.8.0", "numpy==2.2.6", "kiwipiepy==0.24.1"]
# ///
"""uv run make_data.py: 기존 2,600개에 Reset/Exit·방향 수정 계획 400개를 추가한다."""
import argparse
import bisect
import difflib
import hashlib
import json
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

sys.dont_write_bytecode = True
from pipeline import QUESTIONS, assemble, normalize_numbers, windows

SYSTEM = '''한국어 음성 명령 데이터를 만든다. 퍼즐 게임에서 플레이어가 로봇 3대에게 말로 명령한다.
로봇: red=빨강이/빨강아/빨간 로봇/레드, green=초록이/초록아/초록 로봇/그린, blue=파랑이/파랑아/파란 로봇/블루.
명령: Move=이동, Rotate=회전, Interact=벽 부수기("벽 부숴", "벽 깨", "부숴 줘", "벽 부수고", "상호작용해" 등, 대부분은 벽을 부순다고 말한다), ResetGame=퍼즐 처음부터 다시("리셋", "다시 시작", "처음부터 다시", "초기화", "다시 해" 등), ExitGame=게임 종료("게임 종료", "게임 꺼", "그만할래", "끝낼래", "나갈래" 등).
입력 JSON 배열의 계획마다, 플레이어가 한 번에 말하는 자연스러운 구어 발화를 만들어라.
- cmds를 순서대로 모두 말하고 다른 명령은 더하지 마라. cmds가 비었으면 명령이 아닌 혼잣말 한마디.
- name이 있을 때만 로봇 이름을 말한다.
- dir: Front=앞/위/전진, Back=뒤/아래/후진, Left=왼쪽/좌측, Right=오른쪽/우측. 회전은 Left=반시계 방향, Right=시계 방향도 된다. 회전 Back은 "뒤로 돌아". dir이 없으면 방향을 말하지 않는다.
- n이 있으면 unit과 함께 한글 숫자로 말한다. 칸·걸음은 한/두/세/네/다섯…, 미터·도는 일/이/삼/사…(예: 세 칸, 삼 미터, 구십 도). n이 없으면 숫자를 말하지 않는다.
- wrong이 있으면 그 명령을 먼저 wrong의 값으로 잘못 말하다가 "아니", "아니다", "아 잠깐", "말고"로 끊고, 계획의 원래 값으로 고쳐 말한다. 고친 뒤에는 wrong 값을 다시 말하지 않는다.
- cancel이 true면 그 명령을 말한 뒤 "아니다 하지 마", "취소" 등으로 취소한다.
- style을 따르고 채움말(음, 어, 그러니까), 접속어(그리고, 그 다음에, -고, -서), 반말·존댓말을 섞어 매번 다르게 말한다.
출력은 JSON 배열만: 계획마다 {"id": id, "p": [[조각, c], ...]}. 조각을 순서대로 이으면 전체 발화다. c는 그 조각에서 끝나는 최종 명령의 i이고, 나머지 조각(채움말, 접속어, 잘못 말한 부분, 취소된 명령, 이름만)은 -1이다. 취소되지 않은 명령마다 c는 정확히 한 번 나온다.
예) 입력 [{"id":5,"cmds":[{"i":0,"op":"Move","name":"green","dir":"Back","n":2,"unit":"칸"},{"i":1,"op":"Move","dir":"Left","n":3,"unit":"미터","cancel":true},{"i":2,"op":"Rotate","dir":"Right","n":45,"unit":"도","wrong":{"n":90}}],"style":"반말"}]
출력 [{"id":5,"p":[["초록아, 뒤로 두 칸 가 줘.",0],["왼쪽으로 삼 미터... 아니다, 그건 하지 마.",-1],["그 다음에 오른쪽으로 구십...",-1],["아 아니,",-1],["사십오 도 돌아",2]]}]
'''
JUDGE_SYSTEM = r'''한국어 음성 명령을 게임 명령 목록으로 바꾼다.
로봇: red=빨강이/빨간 로봇/레드, green=초록이/초록 로봇/그린, blue=파랑이/파란 로봇/블루.
명령: Select("red"), Move("Front"|"Back"|"Left"|"Right", n), Rotate("Left"|"Right", n), Interact(), ResetGame(), ExitGame().
규칙:
- 말하다가 고치거나 취소한 것은 최종 의도만 남긴다.
- 로봇 이름을 부르면 그 로봇이 이후 명령의 대상이 된다(취소된 명령에서 부른 이름도). Select는 대상 로봇이 바뀐 뒤 첫 Move/Rotate/Interact 바로 앞에만 넣는다. 발화 시작부터 이름이 없으면 Select 없이 쓴다.
- 이동 방향: 앞·위·전진=Front, 뒤·아래·후진=Back, 왼쪽·좌측=Left, 오른쪽·우측=Right. 말하지 않으면 Front.
- 회전 방향: 왼쪽·반시계=Left, 오른쪽·시계=Right. 말하지 않으면 Right. "뒤로 돌아"는 Rotate("Right", 180).
- n은 말한 숫자(칸·미터·걸음·도). 말하지 않았으면 -1.
- ResetGame/ExitGame 앞에는 Select를 넣지 않는다. 명령이 없으면 빈 목록.
입력: [{"id":1,"t":"발화"}, ...]
출력: JSON 배열만. [{"id":1,"c":["Select(\"red\")","Move(\"Front\", 2)"]}, ...]
'''
WALL_JUDGE_SYSTEM = JUDGE_SYSTEM.replace(
    next(line for line in JUDGE_SYSTEM.splitlines() if line.startswith("명령:")),
    '명령: Select("red"), Move("Front"|"Back"|"Left"|"Right", n), Rotate("Left"|"Right", n), Interact()=벽 부수기·상호작용, ResetGame()=퍼즐 처음부터 다시, ExitGame()=게임 종료.',
)
ROBOTS = ["red", "green", "blue"]
NAMES = dict(zip("빨강 빨간 레드 초록 그린 파랑 파란 블루".split(), ["red"] * 3 + ["green"] * 2 + ["blue"] * 3))
DIRECTIONS = {"Front": "앞|위|전진|직진", "Back": "뒤|아래|후진", "Left": "왼|좌|반시계", "Right": "오른|우측|(?<!반)시계"}
STYLES = ["반말", "존댓말", "반말, 망설이며 채움말 많이", "짧고 급하게", "반말, 접속어로 길게 이어서", "존댓말, 차분하게"]
VOICES = ["Yuna (한국어(한국))", "Jian (Premium)"]
GENERATOR = "neuralwatt/deepseek-v4.1-flash"
JUDGES = ["neuralwatt/kimi-k3", "neuralwatt/glm-5.3"]


def amount(rng, op):
    if op == "Move":
        return rng.choices(range(1, 11), [15, 18, 18, 12, 10, 7, 5, 5, 4, 6])[0]
    value = rng.choices([90, 45, 180, 30, 60, 15, "special", "uniform"], [35, 12, 10, 8, 6, 4, 5, 20])[0]
    return rng.choice([120, 270, 360]) if value == "special" else rng.randint(1, 359) if value == "uniform" else value


def sample(rng, ident, revised=False, wall=False, targeted=None):
    cmds, current = [], None
    if targeted is not None and targeted[0]:
        count = 1 if targeted[1] else rng.choices(range(2, 6), [28, 18, 11, 7])[0]
    else:
        count = rng.choices(range(6), [6, 30, 28, 18, 11, 7])[0]
    for i in range(count):
        ops = ["Move", "Rotate", "Interact"]
        weights = [50, 30, 20] if targeted is not None else [45, 25, 25] if wall else [55, 28, 12]
        if targeted is None and i == count - 1:
            ops, weights = ops + ["ResetGame", "ExitGame"], weights + [2.5, 2.5]
        terminal = targeted[0] if targeted is not None and i == count - 1 else None
        cmd = {"op": terminal or rng.choices(ops, weights)[0]}
        if cmd["op"] in {"ResetGame", "ExitGame"}:
            cmds.append(cmd)
            continue
        choice = rng.random()
        if (i == 0 and choice < .85) or (i > 0 and choice < .55):
            cmd["name"] = current if i > 0 and choice >= .45 and current else rng.choice([r for r in ROBOTS if i == 0 or r != current])
            current = cmd["name"]
        op = cmd["op"]
        if op in {"Move", "Rotate"}:
            dirs, weights = (["Front", "Back", "Left", "Right", None], [33, 20, 21, 21, 5]) if op == "Move" else (["Left", "Right", "Back", None], [45, 45, 7, 3])
            direction = rng.choices(dirs, weights)[0]
            if direction:
                cmd["dir"] = direction
            probability = .85 if op == "Move" else 0 if direction == "Back" else .5 if direction is None else .8
            if rng.random() < probability:
                cmd.update(n=amount(rng, op), unit=rng.choices(["칸", "미터", "걸음"], [60, 30, 10])[0] if op == "Move" else "도")
            if rng.random() < (.40 if targeted is not None else .35 if revised else .18):
                keys = [k for k in ("dir", "n", "name", "op") if k in cmd]
                key = rng.choices(keys, [2 if k == "dir" else 1 for k in keys])[0] if targeted is not None else rng.choice(keys)
                value = rng.choice([d for d in dirs if d and d != direction]) if key == "dir" else rng.choice([r for r in ROBOTS if r != current]) if key == "name" else "Rotate" if op == "Move" else "Move"
                if key == "n":
                    value = amount(rng, op)
                    while value == cmd["n"]:
                        value = amount(rng, op)
                cmd["fix"] = {key: value}
        if "fix" not in cmd and rng.random() < (.10 if revised else .06):
            cmd["cancel"] = True
        cmds.append(cmd)
    return {"id": ident, "cmds": cmds, "style": rng.choice(STYLES)}


def targeted_plans(rng):
    endings = [(op, True) for op in ("ResetGame", "ExitGame") for _ in range(30)]
    endings += [(op, False) for op in ("ResetGame", "ExitGame") for _ in range(60)]
    endings += [(None, False)] * 220
    rng.shuffle(endings)
    return [sample(rng, i, revised=True, targeted=ending) for i, ending in zip(range(2624, 3024), endings)]


def gold(cmds):
    result, current, selected = [], None, None
    for cmd in cmds:
        current = cmd.get("name", cmd.get("fix", {}).get("name", current))
        if cmd.get("cancel"):
            continue
        op = cmd["op"]
        if op in {"ResetGame", "ExitGame"}:
            result.append(f"{op}()")
            continue
        if current and current != selected:
            result.append(f'Select("{current}")')
            selected = current
        direction, n = cmd.get("dir"), cmd.get("n", -1)
        if op == "Rotate":
            direction, n = ("Right", 180) if direction == "Back" else (direction or "Right", n)
        result.append("Interact()" if op == "Interact" else f'{op}("{direction or "Front"}", {n})')
    return result


def request(batch, model, thinking, prompt):
    seconds, error = 0., "llm"
    for attempt in range(2):
        start = perf_counter()
        try:
            result = subprocess.run(["pi", "-p", "--model", model, "--thinking", thinking, "--no-tools", "--no-session", "-nc", "-ns", "-np", "--no-mcp", "--system-prompt", prompt, "--", json.dumps(batch, ensure_ascii=False)], capture_output=True, text=True, timeout=120)
            stderr = "\n".join(line for line in result.stderr.splitlines() if not line.startswith("Warning: No models match"))
            if result.returncode:
                raise RuntimeError(stderr[-500:])
            parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", result.stdout.strip()))
            if not isinstance(parsed, list):
                raise ValueError("JSON array required")
            return parsed, seconds + perf_counter() - start, attempt + 1, None
        except (json.JSONDecodeError, ValueError):
            error = "json"
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            error = "llm"
            print(f"LLM retry/drop: {type(exc).__name__}: {str(exc)[-500:]}", flush=True)
        seconds += perf_counter() - start
    return [], seconds, 2, error


def batches(payload, model, thinking, prompt):
    start, output = perf_counter(), {}
    groups = [payload[i:i + 6] for i in range(0, len(payload), 6)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(lambda b: request(b, model, thinking, prompt), groups))
    for group, (response, _, _, error) in zip(groups, responses):
        for item in group:
            matches = [r for r in response if isinstance(r, dict) and type(r.get("id")) is int and r["id"] == item["id"]]
            output[item["id"]] = dict(value=matches[0] if len(matches) == 1 else None, error=error or (None if len(matches) == 1 else "json"))
    return output, dict(seconds=perf_counter() - start, call_seconds=sum(r[1] for r in responses), calls=sum(r[2] for r in responses))


def llm_plan(plan):
    return dict(id=plan["id"], style=plan["style"], cmds=[dict(i=i, **{("wrong" if k == "fix" else k): v for k, v in c.items()}) for i, c in enumerate(plan["cmds"])])


def check_fixes(plan, chunks):
    positions = {c: i for i, (_, c) in enumerate(chunks) if c >= 0}
    words = {"dir": DIRECTIONS, "name": {r: "|".join(n for n, robot in NAMES.items() if robot == r) for r in ROBOTS},
             "op": {"Rotate": "돌|회전|틀", "Move": "가|이동|움직|전진|후진"}}
    checks, start = [], 0
    for index, cmd in enumerate(plan["cmds"]):
        if cmd.get("cancel"):
            continue
        end = positions[index] + 1
        if cmd.get("fix"):
            region = normalize_numbers(" ".join(t for t, _ in chunks[start:end]))
            cues = list(re.finditer("아니|잠깐|말고", region))
            valid = bool(cues)
            if cues:
                after = region[cues[-1].start():]
                for key, wrong in cmd["fix"].items():
                    wrong_pattern, correct_pattern = (rf"(?<!\d){v}(?!\d)" for v in (wrong, cmd[key])) if key == "n" else (words[key][wrong], words[key][cmd[key]])
                    if key == "op":
                        correct_pattern = "가|이동|움직|전진|후진|칸|미터|걸음" if cmd[key] == "Move" else words[key][cmd[key]]
                        wrong_pattern = "이동|움직|전진|후진|칸|미터|걸음" if wrong == "Move" else words[key][wrong]
                    valid &= bool(re.search(correct_pattern, after) and not re.search(wrong_pattern, after))
            checks.append(dict(cmd_index=index, start=start, end=end, valid=valid))
        start = end
    return checks


def validate(plan, chunks):
    if not isinstance(chunks, list) or not chunks or any(not isinstance(p, list) or len(p) != 2 or not isinstance(p[0], str) or not p[0].strip() or type(p[1]) is not int for p in chunks):
        return "json"
    if sorted(c for _, c in chunks if c != -1) != [i for i, cmd in enumerate(plan["cmds"]) if not cmd.get("cancel")]:
        return "c_set"
    if any(re.search(r"[0-9]", text) for text, _ in chunks):
        return "digits"
    if len(" ".join(text for text, _ in chunks)) > 200:
        return "too_long"
    for i, (text, c) in enumerate(chunks):
        if c >= 0 and not re.search(r"[^\s.,?!…]", text):
            return "json"
        if c >= 0 and (direction := plan["cmds"][c].get("dir")) and not re.search(DIRECTIONS[direction], " ".join(t for t, _ in chunks[max(0, i - 2):i + 1])):
            return "dir_word"
    if any(not check["valid"] for check in check_fixes(plan, chunks)):
        return "fix_order"


def position_map(source, target):
    a, b = ([i for i, char in enumerate(s) if not char.isspace()] for s in (source, target))
    mapping = {}
    for tag, i, end, j, stop in difflib.SequenceMatcher(None, "".join(source[k] for k in a), "".join(target[k] for k in b), autojunk=False).get_opcodes():
        for k in range(i, end):
            pos = j + (k - i if tag == "equal" else (k - i) * (stop - j) // (end - i))
            mapping[a[k]] = b[pos] if pos < len(b) else len(target)
    return mapping


def cer(reference, output):
    reference, output = (re.sub(r"[\s.,?!…~]", "", normalize_numbers(s)) for s in (reference, output))
    row = list(range(len(output) + 1))
    for i, a in enumerate(reference, 1):
        new = [i]
        for j, b in enumerate(output, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = new
    return row[-1] / max(1, len(reference))


def label(plan, chunks, asr=None):
    parts = [normalize_numbers(text.strip()) for text, _ in chunks]
    source = " ".join(parts)
    target = source if asr is None else normalize_numbers(asr)
    windowed = windows(target)
    segments, spans, cursor = [text for text, _ in windowed], [], 0
    for text in segments:
        start = target.index(text, cursor)
        spans.append((start, start + len(text)))
        cursor = start + len(text)
    starts, ends = [s for s, _ in spans], [e for _, e in spans]
    labels, anchors = [["none", "none", "none"] for _ in spans], set()
    mapping = None if asr is None else position_map(source, target)
    for match in re.finditer("|".join(NAMES), source):
        pos = match.start() if mapping is None else mapping[match.start()]
        j = bisect.bisect_right(ends, pos)
        if j < len(labels):
            labels[j][0] = NAMES[match.group()]
    offset = 0
    for text, (_, c) in zip(parts, chunks):
        if c >= 0 and spans:
            pos = offset + max(m.start() for m in re.finditer(r"[^\s.,?!…]", text))
            pos = pos if mapping is None else mapping[pos]
            j = max(0, bisect.bisect_right(starts, pos) - 1)
            if j in anchors:
                return [], "clean_merge" if asr is None else "asr_merge"
            anchors.add(j)
            cmd = plan["cmds"][c]
            labels[j][1:] = [cmd["op"], cmd.get("dir", "none") if cmd["op"] in {"Move", "Rotate"} else "none"]
        offset += len(text) + 1
    actual, expected = assemble([(text, *values) for text, values in zip(segments, labels)]), gold(plan["cmds"])
    mask = lambda cmds: [re.sub(r"-?\d+(?=\)$)", "#", cmd) for cmd in cmds]
    if (actual != expected) if asr is None else (mask(actual) != mask(expected)):
        return [], "clean_mismatch" if asr is None else "asr_mismatch"
    rows = [{"state": state, "questions": QUESTIONS, "gold": dict(zip(QUESTIONS, values))}
            for (_, state), values in zip(windowed, labels)]
    return rows, None


def save_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def save_records(path, records):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def prepare(records):
    prepared = []
    for old in records:
        plan, chunks = old["plan"], old["chunks"]
        previous = old.get("clean_reason", old.get("reason") if old.get("status") == "clean_reject" else None)
        reason = old.get("generation_error") or validate(plan, chunks)
        if previous in {"json", "c_set", "digits", "too_long", "dir_word"}:
            reason = previous
        fixes = check_fixes(plan, chunks) if reason in {None, "fix_order"} else []
        if not reason:
            _, reason = label(plan, chunks)
        text = " ".join(t for t, _ in chunks) if not reason else None
        record = dict(old)
        record.update(gold=gold(plan["cmds"]), tts_text=text, clean_reason=reason, reason=reason,
                      status="clean_reject" if reason else "clean_valid", fix_checks=fixes,
                      asr_results=old.get("asr_results", []) if old.get("tts_text") == text else [])
        prepared.append(record)
    return prepared


def generate(plans, thinking):
    start = perf_counter()
    output, timing = batches([llm_plan(p) for p in plans], GENERATOR, thinking, SYSTEM)
    records = prepare([dict(id=p["id"], plan=p, chunks=(output[p["id"]]["value"] or {}).get("p"),
                            generation_error=output[p["id"]]["error"],
                            generation=dict(model=GENERATOR, thinking=thinking, prompt="reset-v4")) for p in plans])
    timing.update(seconds=perf_counter() - start, plans=len(plans), clean_valid=sum(r["clean_reason"] is None for r in records),
                  fix_order=sum(r["clean_reason"] == "fix_order" for r in records))
    return records, timing


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def agree(commands, expected):
    return isinstance(commands, list) and all(isinstance(c, str) for c in commands) and [re.sub(r"\s", "", c) for c in commands] == [re.sub(r"\s", "", c) for c in expected]


def judge_prompt(record):
    return WALL_JUDGE_SYSTEM if record["id"] >= 2024 else JUDGE_SYSTEM


def judge_result(record, response, model, prompt=JUDGE_SYSTEM):
    commands = (response["value"] or {}).get("c")
    error = response["error"] or (None if isinstance(commands, list) and all(isinstance(c, str) for c in commands) else "json")
    return dict(model=model, thinking="low", commands=commands, error=error,
                agree=not error and agree(commands, record["gold"]),
                tts_sha256=digest(record["tts_text"]), system_sha256=digest(prompt))


def judge_batch(records, model, prompt=JUDGE_SYSTEM):
    output, timing = batches([dict(id=r["id"], t=r["tts_text"]) for r in records], model, "low", prompt)
    results = [dict(id=r["id"], judge=judge_result(r, output[r["id"]], model, prompt)) for r in records]
    timing.update(plans=len(records), agreements=sum(r["judge"]["agree"] for r in results),
                  errors=sum(r["judge"]["error"] is not None for r in results))
    return results, timing


def adjudicate(records):
    clean = [r for r in records if r["clean_reason"] is None]
    model = "neuralwatt/kimi-k3"
    todo = []
    for record in clean:
        value = record.get("judge")
        if value and value.get("model") == model and value.get("system_sha256") == digest(judge_prompt(record)) and value.get("tts_sha256") == digest(record["tts_text"]):
            record["judge"] = value
            value["agree"] = not value.get("error") and agree(value.get("commands"), record["gold"])
        else:
            todo.append(record)
    timing = {}
    for name, new, prompt in (("old", False, JUDGE_SYSTEM), ("new", True, WALL_JUDGE_SYSTEM)):
        group = [r for r in todo if (r["id"] >= 2024) == new]
        results, timing[name] = judge_batch(group, model, prompt)
        for record, result in zip(group, results):
            record["judge"] = result["judge"]
    for record in clean:
        passed = record["judge"]["agree"]
        record.update(status="judge_valid" if passed else "judge_reject", reason=None if passed else "judge")
    print(f"judge {model}: {sum(r['judge']['agree'] for r in clean)}/{len(clean)}", flush=True)
    return timing


def make_transcriber():
    model = None
    def transcribe(text, voice, rng):
        nonlocal model
        import numpy as np
        import torch
        from funasr import AutoModel
        elapsed, rate = Counter(), rng.randint(160, 230)
        if model is None:
            loading = perf_counter()
            model = AutoModel(model="FunAudioLLM/SenseVoiceSmall", hub="hf", device="mps", disable_update=True, disable_pbar=True, disable_log=True)
            if next(model.model.parameters()).device.type != "mps":
                raise RuntimeError("SenseVoice did not load on mps")
            elapsed["model_load_seconds"] = perf_counter() - loading
        with tempfile.TemporaryDirectory() as tmp:
            audio, began = Path(tmp) / "speech.aiff", perf_counter()
            try:
                subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(audio), "--", text], check=True)
                elapsed["tts_seconds"] = perf_counter() - began
                raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"], capture_output=True, check=True).stdout
                samples = np.frombuffer(raw, dtype="<f4").copy()
                if not samples.size:
                    raise ValueError("Empty TTS audio")
                torch.mps.synchronize()
                began = perf_counter()
                result = model.generate(input=samples, cache={}, language="ko", use_itn=False)
                torch.mps.synchronize()
                elapsed["asr_seconds"] = perf_counter() - began
                return rate, re.sub(r"<\|.*?\|>", "", result[0]["text"]).strip(), elapsed
            finally:
                audio.unlink(missing_ok=True)
    return transcribe


def interact_coverage(records):
    plans = [r for r in records if any(c["op"] == "Interact" for c in r["plan"]["cmds"])]
    texts = [" ".join(p[0] for p in r["chunks"]) for r in plans
             if isinstance(r["chunks"], list) and r["chunks"] and all(isinstance(p, list) and len(p) == 2 and isinstance(p[0], str) and p[0].strip() for p in r["chunks"])]
    wall = [bool(re.search("벽|부수|부숴|깨", t)) for t in texts]
    interaction = ["상호작용" in t for t in texts]
    return dict(plans=len(plans), utterances=len(texts), wall_utterances=sum(wall),
                interaction_utterances=sum(interaction), both=sum(a and b for a, b in zip(wall, interaction)),
                keyword_mentions={word: sum(t.count(word) for t in texts) for word in ("벽", "부수", "부숴", "깨", "상호작용")})


def round3_rows(new_rows, older_rows):
    if len(older_rows) < 8000:
        raise ValueError("round3 requires at least 8,000 older train rows")
    rows = list(new_rows) + random.Random(3).sample(older_rows, 8000)
    random.Random(3).shuffle(rows)
    return rows


def reset_exit_share(actions):
    total = sum(actions.values())
    reset, exit_game = actions.get("ResetGame", 0), actions.get("ExitGame", 0)
    return dict(rows=total, ResetGame=reset, ExitGame=exit_game,
                combined=reset + exit_game, fraction=(reset + exit_game) / max(1, total))


def build(records, pilots, out):
    start, rng, transcribe = perf_counter(), random.Random(42), make_transcriber()
    counts = Counter(plans=len(records), clean_valid=sum(r["clean_reason"] is None for r in records),
                     judge_valid=sum(r["status"] == "judge_valid" for r in records))
    rejects = Counter(r["reason"] for r in records if r["reason"])
    labels = {q: Counter() for q in QUESTIONS}
    per_voice = {v: dict(count=0, asr_valid=0, cer_sum=0., rejects=Counter(asr_cer=0, asr_merge=0, asr_mismatch=0)) for v in VOICES}
    groups = {name: dict(plans=sum(lo <= r["id"] < hi for r in records),
                         fix_order=sum(lo <= r["id"] < hi and r["clean_reason"] == "fix_order" for r in records))
              for name, lo, hi in (("original", 24, 1224), ("wrong-v2", 1224, 2024), ("wall-v3", 2024, 2624), ("reset-v4", 2624, 3024))}
    timing = Counter()
    older_train, new_train = [], []
    val_ids = set(random.Random(43).sample([r["id"] for r in records], round(len(records) * .05)))
    with tempfile.TemporaryDirectory(prefix=".build-", dir=out) as tmp, (out / ".round_asr.jsonl").open("a") as journal:
        stage = Path(tmp)
        with (stage / "train.jsonl").open("w") as train, (stage / "val.jsonl").open("w") as val:
            for record in records:
                if record["status"] != "judge_valid":
                    continue
                rows, reason = label(record["plan"], record["chunks"])
                if reason:
                    raise RuntimeError(f"Clean labels changed for {record['id']}: {reason}")
                counts["clean_rows"] += len(rows)
                cached = {a["voice"]: a for a in record["asr_results"]}
                record["asr_results"] = []
                for voice in VOICES:
                    clip = dict(cached[voice]) if voice in cached else None
                    if clip is None:
                        rate, text, elapsed = transcribe(record["tts_text"], voice, rng)
                        timing.update(elapsed)
                        clip = dict(voice=voice, rate=rate, asr_text=text)
                        counts["new_asr_versions"] += 1
                    else:
                        counts["cached_asr_versions"] += 1
                    error_rate = cer(record["tts_text"], clip["asr_text"])
                    noisy, reason = ([], "asr_cer") if error_rate > .35 else label(record["plan"], record["chunks"], clip["asr_text"])
                    clip.update(cer=error_rate, status="asr_reject" if reason else "asr_valid", reason=reason)
                    record["asr_results"].append(clip)
                    rows.extend(noisy)
                    counts.update(asr_versions=1, asr_valid_versions=reason is None, asr_rows=len(noisy))
                    summary = per_voice[voice]
                    summary["count"] += 1
                    summary["asr_valid"] += reason is None
                    summary["cer_sum"] += error_rate
                    if reason:
                        summary["rejects"][reason] += 1
                        rejects[reason] += 1
                    journal.write(json.dumps(dict(id=record["id"], asr_results=record["asr_results"]), ensure_ascii=False) + "\n")
                    journal.flush()
                counts["asr_valid_plans"] += any(a["status"] == "asr_valid" for a in record["asr_results"])
                for row in rows:
                    encoded = json.dumps(row, ensure_ascii=False) + "\n"
                    is_val = record["id"] in val_ids
                    (val if is_val else train).write(encoded)
                    counts["val_rows" if is_val else "train_rows"] += 1
                    if not is_val:
                        (new_train if record["id"] >= 2624 else older_train).append(encoded)
                    for q in QUESTIONS:
                        labels[q][row["gold"][q]] += 1
                print(f"[{record['id']}] " + ", ".join(f"{a['voice']}: {a['reason'] or 'valid'}" for a in record["asr_results"]), flush=True)
        for summary in per_voice.values():
            summary["mean_cer"] = summary.pop("cer_sum") / max(1, summary["count"])
        valid = [r for r in records if r["status"] == "judge_valid"]
        shares = dict(plans=len(valid), fix=sum(any(c.get("fix") for c in r["plan"]["cmds"]) for r in valid),
                      cancel=sum(any(c.get("cancel") for c in r["plan"]["cmds"]) for r in valid),
                      either=sum(any(c.get("fix") or c.get("cancel") for c in r["plan"]["cmds"]) for r in valid))
        new = [r for r in records if r["id"] >= 2624]
        new_valid = [r for r in new if r["status"] == "judge_valid"]
        new_round = dict(plans=len(new), clean_valid=sum(r["clean_reason"] is None for r in new),
                         judge_valid=len(new_valid), asr_valid_plans=sum(any(a["status"] == "asr_valid" for a in r["asr_results"]) for r in new_valid),
                         asr_valid_by_voice={v: sum(a["status"] == "asr_valid" for r in new_valid for a in r["asr_results"] if a["voice"] == v) for v in VOICES},
                         terminal_plans=sum(bool(r["plan"]["cmds"]) and r["plan"]["cmds"][-1]["op"] in {"ResetGame", "ExitGame"} for r in new),
                         standalone_terminal_plans=sum(len(r["plan"]["cmds"]) == 1 and r["plan"]["cmds"][0]["op"] in {"ResetGame", "ExitGame"} for r in new))
        selected = round3_rows(new_train, older_train)
        (stage / "round3.jsonl").write_text("".join(selected))
        round3_action = Counter(json.loads(line)["gold"]["action"] for line in selected)
        round3 = dict(rows=len(selected), new_train_rows=len(new_train), older_train_rows=8000,
                      sample_seed=3, shuffle_seed=3, action=round3_action)
        timing["asr_build_seconds"] = perf_counter() - start
        stats = dict(counts=counts, rejects=rejects, per_voice=per_voice, labels=labels, groups=groups,
                     final_plan_features=shares, new_round=new_round, round3=round3,
                     reset_exit_share=dict(all=reset_exit_share(labels["action"]), round3=reset_exit_share(round3_action)),
                     timings=timing, pilots=pilots, environment=sys.prefix, seed=42)
        save_records(stage / "utterances.jsonl", records)
        save_json(stage / "stats.json", stats)
        for name in ("train.jsonl", "val.jsonl", "round3.jsonl", "utterances.jsonl", "stats.json"):
            (stage / name).replace(out / name)
    return stats


def report(stats, records, out):
    counts, new, r3 = stats["counts"], stats["new_round"], stats["round3"]
    lines = [f"전체 {counts['plans']:,}계획, clean-valid {counts['clean_valid']:,}개, judge-valid {counts['judge_valid']:,}개.",
             f"신규 {new['plans']}계획: clean-valid {new['clean_valid']}개, judge-valid {new['judge_valid']}개, ASR-valid 계획(한 음성 이상) {new['asr_valid_plans']}개.",
             f"신규 입력 중 Reset/Exit로 끝나는 계획 {new['terminal_plans']}개, 이 중 단독 명령 {new['standalone_terminal_plans']}개.",
             "", "| 신규 음성 | ASR 대상 | ASR-valid |", "| --- | ---: | ---: |"]
    for voice in VOICES:
        lines.append(f"| {voice} | {new['judge_valid']} | {new['asr_valid_by_voice'][voice]} |")
    lines += ["", f"train {counts['train_rows']:,}행, val {counts['val_rows']:,}행.",
              f"round3.jsonl {r3['rows']:,}행 = 신규 train {r3['new_train_rows']:,}행 + 기존 train {r3['older_train_rows']:,}행. 추출 seed 3, 셔플 seed 3. val 계획의 행 제외.",
              "", "Reset/Exit 비율(none 포함 전체 action 행 기준):", "", "| 범위 | 전체 행 | ResetGame | ExitGame | 합계 | 합계 비율 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, share in stats["reset_exit_share"].items():
        lines.append(f"| {name} | {share['rows']:,} | {share['ResetGame']} | {share['ExitGame']} | {share['combined']} | {share['fraction']:.2%} |")
    lines += ["", "| 질문 | 라벨별 행 수 |", "| --- | --- |"]
    for q, question in QUESTIONS.items():
        lines.append(f"| {q} | " + ", ".join(f"{k} {stats['labels'][q].get(k, 0):,}" for k in question["criteria"]) + " |")
    lines += ["", "DATA_DISK", "", "무작위 신규 Reset/Exit 발화 3개(judge-valid, 추출 seed 3):"]
    candidates = [r for r in records if r["id"] >= 2624 and r["status"] == "judge_valid" and any(c in {"ResetGame()", "ExitGame()"} for c in r["gold"])]
    for i, r in enumerate(random.Random(3).sample(candidates, min(3, len(candidates))), 1):
        lines += ["", f"{i}. ID {r['id']}", f"   - TTS: {r['tts_text']}", f"   - gold: `{json.dumps(r['gold'], ensure_ascii=False)}`"]
    lines += ["", "모델 재학습과 실제 사용자 음성 평가는 실행하지 않았다."]
    text = "\n".join(lines) + "\n"
    path = out / "report.md"
    path.write_text(text.replace("DATA_DISK", "data/ 용량 측정 중."))
    for _ in range(2):
        kib = int(subprocess.check_output(["du", "-sk", str(out)], text=True).split()[0])
        path.write_text(text.replace("DATA_DISK", f"data/ 전체: du {kib:,}KiB ({kib/1024:.3f}MiB). 음성 보관 0개."))


def self_check():
    cases = [({"op": "Rotate", "dir": "Left", "fix": {"dir": "Right"}}, "시계 방향으로 돌아", "반시계 방향으로 돌아"),
             ({"op": "Move", "n": 2, "fix": {"n": 3}}, "세 칸 가", "두 칸 가"),
             ({"op": "Move", "name": "red", "fix": {"name": "blue"}}, "블루 가", "빨강아 가"),
             ({"op": "Move", "fix": {"op": "Rotate"}}, "회전해", "이동해")]
    for cmd, wrong, correct in cases:
        plan = {"cmds": [cmd]}
        assert validate(plan, [[wrong, -1], ["아니 " + correct, 0]]) is None
        assert validate(plan, [[correct, -1], ["아니 " + correct, 0]]) is None
        assert validate(plan, [[correct, -1], ["아니 " + wrong, 0]]) == "fix_order"
        assert validate(plan, [[correct, 0], ["아니 " + wrong, -1]]) == "fix_order"
    assert validate({"cmds": [{"op": "Rotate", "dir": "Left", "n": 94, "fix": {"n": 90}}]}, [["왼쪽으로 구십...", -1], ["아 잠깐 구십사 도 돌아", 0]]) is None
    assert validate({"cmds": [cases[1][0]]}, [["열세 칸 아니 두 칸 가", 0]]) is None
    for text in ("세 칸 아니 열두 칸 가", "세 칸 아니 두 칸과 세 칸 가", "세 칸 아니 두 칸 잠깐 세 칸 가"):
        assert validate({"cmds": [cases[1][0]]}, [[text, 0]]) == "fix_order"
    assert validate({"cmds": [{"op": "Move", "n": 3}, cases[1][0]]}, [["아니 세 칸 가", 0], ["두 칸 가", 1]]) == "fix_order"
    assert validate({"cmds": [{"op": "Rotate", "fix": {"op": "Move"}}]}, [["아니 돌아가", 0]]) is None
    assert validate({"cmds": [{"op": "Move", "n": 2, "fix": {"op": "Rotate"}}]}, [["아니 두 칸", 0]]) is None
    assert cer("앞으로 두 칸~ 가…!", "앞으로 2칸 가") == 0
    assert cer("가" * 20, "나" * 7 + "가" * 13) == .35
    assert position_map("ab cd", "ab d") == {0: 0, 1: 1, 3: 3, 4: 3}
    assert agree(['Move("Front", 2)'], [' Move( "Front",2 ) ']) and not agree(['Move("Back", 2)'], ['Move("Front",2)'])
    payload = llm_plan(dict(id=1, style="반말", cmds=[cases[1][0], {"op": "ExitGame"}]))
    assert [c["i"] for c in payload["cmds"]] == [0, 1] and "wrong" in payload["cmds"][0] and all("fix" not in c for c in payload["cmds"])
    assert SYSTEM.splitlines()[2] == '명령: Move=이동, Rotate=회전, Interact=벽 부수기("벽 부숴", "벽 깨", "부숴 줘", "벽 부수고", "상호작용해" 등, 대부분은 벽을 부순다고 말한다), ResetGame=퍼즐 처음부터 다시("리셋", "다시 시작", "처음부터 다시", "초기화", "다시 해" 등), ExitGame=게임 종료("게임 종료", "게임 꺼", "그만할래", "끝낼래", "나갈래" 등).'
    assert WALL_JUDGE_SYSTEM.splitlines()[2] == '명령: Select("red"), Move("Front"|"Back"|"Left"|"Right", n), Rotate("Left"|"Right", n), Interact()=벽 부수기·상호작용, ResetGame()=퍼즐 처음부터 다시, ExitGame()=게임 종료.'
    assert judge_prompt(dict(id=2023)) == JUDGE_SYSTEM and judge_prompt(dict(id=2024)) == WALL_JUDGE_SYSTEM
    plans = targeted_plans(random.Random(3))
    endings = Counter(p["cmds"][-1]["op"] for p in plans if p["cmds"] and p["cmds"][-1]["op"] in {"ResetGame", "ExitGame"})
    assert len(plans) == 400 and [p["id"] for p in plans] == list(range(2624, 3024))
    assert endings == {"ResetGame": 90, "ExitGame": 90}
    assert sum(len(p["cmds"]) == 1 and p["cmds"][0]["op"] in endings for p in plans) == 60
    assert all(j == len(p["cmds"]) - 1 and set(c) == {"op"} for p in plans for j, c in enumerate(p["cmds"]) if c["op"] in endings)
    older, new = list(range(8005)), [10000, 10001]
    expected = new + random.Random(3).sample(older, 8000)
    random.Random(3).shuffle(expected)
    assert round3_rows(new, older) == expected and len(expected) == 8002
    plan = dict(cmds=[dict(op="Move", name="green", dir="Front", n=2, fix=dict(dir="Right"))])
    chunks = [["초록이는 오른쪽으로…", -1], ["아니다, 돌지 말고", -1], ["위로 두 칸만 이동해", 0]]
    assert validate(plan, chunks) is None and label(plan, chunks)[1] is None
    assert label(dict(cmds=[dict(op="ResetGame")]), [["다 망했다", -1], ["리셋", 0]])[1] is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse", action="store_true", help="이미 확장된 3,000개 계획을 재검증")
    args = parser.parse_args()
    start, out = perf_counter(), Path(__file__).parent / "data"
    checkpoint = out / ".round_records.jsonl"
    source = checkpoint if checkpoint.exists() else out / "utterances.jsonl"
    records = [json.loads(line) for line in source.read_text().splitlines()]
    pilots_path = out / "pilots.json"
    pilots = json.loads(pilots_path.read_text()) if pilots_path.exists() else {}
    ids = {r["id"] for r in records}
    if len(records) == 2600 and ids == set(range(24, 2624)):
        if args.reuse:
            raise ValueError("먼저 --reuse 없이 실행해 400개 계획을 추가하세요.")
        generated, timing = generate(targeted_plans(random.Random(20261030)), "off")
        timing["sampler_seed"] = 20261030
        pilots["round3_generation"] = timing
        save_json(pilots_path, pilots)
        records += generated
    elif len(records) != 3000 or ids != set(range(24, 3024)):
        raise ValueError("Expected 2,600 old plans or all 3,000 plans, ids 24–3023")
    records = prepare(records)
    save_records(checkpoint, records)
    print(f"clean {sum(r['clean_reason'] is None for r in records)}/{len(records)}", flush=True)
    timing = adjudicate(records)
    pilots["round3_judge"] = timing
    save_json(pilots_path, pilots)
    save_records(checkpoint, records)
    journal = out / ".round_asr.jsonl"
    if journal.exists():
        by_id = {r["id"]: r for r in records}
        for line in journal.read_text().splitlines():
            entry = json.loads(line)
            by_id[entry["id"]]["asr_results"] = entry["asr_results"]
    voices = {m.group(1).strip() for line in subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout.splitlines() if (m := re.match(r"^(.*?)\s+ko_KR\s", line))}
    if not set(VOICES) <= voices:
        raise RuntimeError("Required ko_KR voices missing")
    stats = build(records, pilots, out)
    stats["timings"]["total_seconds"] = perf_counter() - start
    save_json(out / "stats.json", stats)
    checkpoint.unlink(missing_ok=True)
    journal.unlink(missing_ok=True)
    report(stats, records, out)


if __name__ == "__main__":
    self_check()
    main()
