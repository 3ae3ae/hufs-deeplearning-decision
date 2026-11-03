# /// script
# requires-python = "==3.12.*"
# dependencies = ["laya==0.4.15", "torch==2.14.1", "transformers==5.21.0", "kiwipiepy==0.24.1"]
# ///
# 학습은 프로젝트 환경(torch 2.8)과 따로 돌린다: torch 2.8의 MPS로는 전체 학습이 메모리 부족으로 멈췄다.
# 저장된 모델은 서버(torch 2.8)에서 그대로 읽힌다. 실행: uv run train_laya.py train | eval MODEL_DIR
import argparse
import gc
import json
import math
import random
from pathlib import Path
from time import perf_counter

import laya
import torch
from huggingface_hub import snapshot_download
from laya.common import collate_items
from laya.train import encode_item, items_from_rows, load_checkpoint, rlcd_loss, save_checkpoint, sigma_at

import pipeline


ROOT = Path(__file__).parent
MODEL_ID = "convaiinnovations/laya-multilingual"
REVISION = "1720e3e3357cfe1e281542e223f8273b0890ca34"
SEED = 42


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def train(args):
    if (args.out / "model.safetensors").exists():
        raise FileExistsError(f"이미 모델이 있습니다: {args.out}")
    base = args.init or snapshot_download(MODEL_ID, revision=REVISION, local_files_only=True,
                                          allow_patterns=["config.json", "encoder/*", "model.safetensors",
                                                          "rl_agent_config.json", "tokenizer/*"])
    model, tokenizer, cfg = load_checkpoint(str(base))
    rows = read_rows(args.data)
    if args.limit is not None:
        rows = rows[:args.limit]
    for row in rows:
        row["expected"] = row.pop("gold")
    items, skipped = items_from_rows(tokenizer, rows, 1024, 256)
    if skipped or len(items) != len(rows) * 3 or not items:
        raise ValueError(f"학습 데이터 확인 필요: rows={len(rows)}, items={len(items)}, skipped={skipped}")

    torch.manual_seed(SEED)
    model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.head_checkpointing = True
    model.to("mps").train()
    optimizer = torch.optim.AdamW([
        {"params": [p for n, p in model.named_parameters() if n.startswith("encoder.")], "lr": 2.5e-5},
        {"params": [p for n, p in model.named_parameters() if not n.startswith("encoder.")], "lr": 1e-4},
    ], weight_decay=0.01)
    steps = math.ceil(len(items) / 8)
    updates = math.ceil(steps / 2) * args.epochs
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=updates, eta_min=1e-6)
    print(f"train: {len(rows)} rows, {len(items)} questions, {updates} updates, MPS FP32", flush=True)
    began, update = perf_counter(), 0
    for epoch in range(args.epochs):
        shuffled = list(items)
        random.Random(SEED + epoch).shuffle(shuffled)
        optimizer.zero_grad(set_to_none=True)
        for step, start in enumerate(range(0, len(shuffled), 8)):
            chunk = [encode_item(tokenizer, item, 1024, 256) for item in shuffled[start:start + 8]]
            batch = collate_items([chunk], tokenizer.pad_token_id)
            batch = {k: batch[k].to("mps") for k in
                     ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype", "target")}
            logits, _ = model(batch["input_ids"], batch["attention_mask"], batch["marker_pos"],
                              batch["marker_mask"], batch["qtype"])
            loss = rlcd_loss(logits, batch["target"], batch["marker_mask"], batch["qtype"],
                             sigma_at(epoch, args.epochs, 0.4, 0.1))
            # 마지막 누적 묶음에 배치가 하나만 남으면 그 하나로 나눈다.
            (loss / min(2, steps - step // 2 * 2)).backward()
            if (step + 1) % 2 == 0 or step + 1 == steps:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                update += 1
                if update % 50 == 0 or step + 1 == steps:
                    torch.mps.synchronize()
                    elapsed = perf_counter() - began
                    print(f"epoch {epoch + 1}/{args.epochs} update {update}/{updates} "
                          f"loss {loss.item():.4f} elapsed {elapsed:.1f}s "
                          f"ETA {elapsed * (updates - update) / update:.1f}s", flush=True)

    cfg.update(fine_tuned=True, max_len=1024, head_max_len=256,
               temperature=[1.0, 1.0, 1.0], temperature_by_options={},
               training={"base_model": str(args.init or MODEL_ID), "revision": REVISION, "seed": SEED,
                         "rows": len(rows), "epochs": args.epochs, "updates": update})
    save_checkpoint(model, tokenizer, cfg, str(args.out))
    (args.out / "questions.json").write_text(json.dumps(pipeline.QUESTIONS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {args.out}", flush=True)


def evaluate(model_dir):
    if not (model_dir / "model.safetensors").is_file():
        raise FileNotFoundError(f"모델 파일이 없습니다: {model_dir}")
    agent = laya.load(str(model_dir), device="mps")
    rows = read_rows(ROOT / "data/val.jsonl")
    lines = []

    def log(text):
        print(text, flush=True)
        lines.append(text)

    def predict(state, questions):
        torch.mps.synchronize()
        began = perf_counter()
        answers = agent.predict(state, questions)["answers"]
        torch.mps.synchronize()
        return {q: answer["choice"] for q, answer in answers.items()}, (perf_counter() - began) * 1000

    for _ in range(10):
        predict(rows[0]["state"], rows[0]["questions"])
    log(f"model: {model_dir}")
    log(f"validation: {len(rows)} rows")
    correct = dict.fromkeys(pipeline.QUESTIONS, 0)
    joint, times = 0, []
    for row in rows:
        decisions, ms = predict(row["state"], row["questions"])
        for q in correct:
            correct[q] += decisions[q] == row["gold"][q]
        joint += decisions == row["gold"]
        times.append(ms)
    for q, count in correct.items():
        log(f"{q}: {count}/{len(rows)} ({count / len(rows):.2%})")
    log(f"all three: {joint}/{len(rows)} ({joint / len(rows):.2%})")
    log(f"validation mean ms/call: {sum(times) / len(times):.2f}")
    log("")

    real = read_rows(ROOT / "colab/eval_real.jsonl")
    exact, times = 0, []
    for row in real:
        segments = []
        for segment, state in pipeline.windows(pipeline.normalize_numbers(row["asr"])):
            decisions, ms = predict(state, pipeline.QUESTIONS)
            segments.append((segment, decisions["robot"], decisions["action"], decisions["direction"]))
            times.append(ms)
        predicted = pipeline.assemble(segments)
        ok = predicted == row["commands"]
        exact += ok
        log(f"{row['id']} {'OK' if ok else 'NG'}")
        if not ok:
            log(f"  ASR: {row['asr']}")
            log(f"  predicted: {json.dumps(predicted, ensure_ascii=False)}")
            log(f"  gold: {json.dumps(row['commands'], ensure_ascii=False)}")
            for text, robot, action, direction in segments:
                log(f"  {text} -> robot={robot}, action={action}, direction={direction}")
    log(f"real exact: {exact}/{len(real)} ({exact / len(real):.2%})")
    log(f"real mean ms/call: {sum(times) / len(times):.2f} ({len(times)} segment calls)")
    (model_dir / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--epochs", type=int, default=1)
    training.add_argument("--out", type=Path, default=ROOT / "models/laya-commands")
    training.add_argument("--limit", type=int, help=argparse.SUPPRESS)
    training.add_argument("--init", type=Path, help="이어서 학습할 모델 폴더 (기본: laya-multilingual)")
    training.add_argument("--data", type=Path, default=ROOT / "data/train.jsonl")
    evaluation = commands.add_parser("eval")
    evaluation.add_argument("model_dir", type=Path)
    args = parser.parse_args()
    if not torch.backends.mps.is_available():
        parser.error("MPS를 사용할 수 없습니다.")
    torch.set_num_threads(8)
    if args.command == "train":
        if args.epochs < 1 or (args.limit is not None and args.limit < 1):
            parser.error("epochs와 limit은 1 이상이어야 합니다.")
        train(args)
        gc.collect()
        torch.mps.empty_cache()
        evaluate(args.out)
    else:
        evaluate(args.model_dir)


if __name__ == "__main__":
    main()
