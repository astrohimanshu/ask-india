"""QLoRA fine-tune of a 7B coder on the verified (question, SQL) pairs.

    uv run --extra train python -m askindia_training.train_qlora \
        --pairs results/training/pairs.jsonl --out results/training/adapter-v1

4-bit NF4 base, bf16 LoRA adapters (r=16, alpha=32) on attention and MLP projections, chat-format
examples that reproduce the agent's prompt exactly, loss on the assistant turn only. Runs on a
single 24 GB card; a few thousand pairs take on the order of an hour.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from askindia_training.prompting import contexts, to_chat_example


def load_pairs(path: Path, split: str) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if r["split"] == split]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default="results/training/pairs.jsonl")
    parser.add_argument("--out", default="results/training/adapter-v1")
    parser.add_argument("--base", default="Qwen/Qwen2.5-Coder-7B-Instruct")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-len", type=int, default=2048)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument(
        "--limit", type=int, default=0, help="train on at most N pairs (smoke runs)"
    )
    args = parser.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    ctx = contexts()
    train = load_pairs(Path(args.pairs), "train")
    dev = load_pairs(Path(args.pairs), "dev")
    if args.limit:
        train, dev = train[: args.limit], dev[: max(1, args.limit // 10)]
    examples = [to_chat_example(ctx[p["dataset"]], p["question"], p["sql"]) for p in train]
    dev_examples = [to_chat_example(ctx[p["dataset"]], p["question"], p["sql"]) for p in dev]
    datasets_seen = sorted({p["dataset"] for p in train})
    print(f"train={len(examples)} dev={len(dev_examples)} datasets={datasets_seen}")

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    lora = LoraConfig(
        r=args.rank,
        lora_alpha=args.rank * 2,
        lora_dropout=0.05,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        task_type="CAUSAL_LM",
    )
    out = Path(args.out)
    config = SFTConfig(
        output_dir=str(out),
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        gradient_checkpointing=True,
        bf16=True,
        logging_steps=10,
        eval_strategy="epoch" if dev_examples else "no",
        save_strategy="epoch",
        save_total_limit=2,
        max_length=args.max_len,
        assistant_only_loss=True,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        report_to=[],
        model_init_kwargs={
            "quantization_config": quant,
            "torch_dtype": torch.bfloat16,
            "device_map": "auto",
        },
    )
    trainer = SFTTrainer(
        model=args.base,
        args=config,
        train_dataset=Dataset.from_list(examples),
        eval_dataset=Dataset.from_list(dev_examples) if dev_examples else None,
        processing_class=tokenizer,
        peft_config=lora,
    )
    started = time.perf_counter()
    trainer.train()
    trainer.save_model(str(out / "final"))
    metrics = {**trainer.state.log_history[-1], "seconds": round(time.perf_counter() - started)}
    (out / "final" / "train_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(json.dumps(metrics, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
