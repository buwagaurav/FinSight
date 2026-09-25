"""Runs the assistant over eval/questions.jsonl and grades every answer.

Each question is a real multi-step Claude call (a few cents each with the default model), so the script
asks for confirmation unless you pass --yes. Questions are asked with no company context, so the
assistant must find the company itself, like a user typing into a search box.

Run:  cd backend && ../.venv/bin/python -m eval.run_eval --limit 10
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")

from app.ai import assistant, llm  # noqa: E402  (settings are read after .env is loaded)
from eval.grade import grade, summarize  # noqa: E402


def ask(q: dict) -> dict:
    started = time.time()
    try:
        result = assistant.ask(q["question"])
    except Exception as e:  # keep going; a failed call is graded as wrong
        result = {"answer": "", "error": str(e), "sources": [], "tool_calls": [], "verification": {}}
    graded = grade(q, result)
    return {**q, **graded, "latency_s": round(time.time() - started, 1), "answer": result.get("answer"),
            "error": result.get("error"), "verification": result.get("verification"), "usage": result.get("usage")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only the first N questions")
    ap.add_argument("--kind", choices=["lookup", "calculation", "should_decline"])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    ap.add_argument("--model", help='assistant model to test, e.g. "deepseek:<model-id>" (default: FINSIGHT_MODEL_ASSISTANT)')
    args = ap.parse_args()
    if args.model:
        os.environ["FINSIGHT_MODEL_ASSISTANT"] = args.model
    model = llm.model_spec("assistant")
    if not llm.is_configured("assistant"):
        raise SystemExit(f"No credentials for {model}. Add its API key to backend/.env first.")
    qs = [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines() if line.strip()]
    if args.kind:
        qs = [q for q in qs if q["kind"] == args.kind]
    qs = qs[:args.limit] if args.limit else qs
    if not args.yes and input(f"Run {len(qs)} questions against {model}? This calls the paid API. [y/N] ").lower() != "y":
        return

    with ThreadPoolExecutor(args.workers) as pool:
        rows = []
        for i, row in enumerate(pool.map(ask, qs), 1):
            rows.append(row)
            mark = "✓" if row["correct"] else "✗"
            print(f"[{i}/{len(qs)}] {mark} {row['id']:<22} {row['detail']:<20} {row['latency_s']}s")

    usage = [r["usage"] for r in rows if r.get("usage")]
    tokens = {k: sum(u.get(k, 0) for u in usage) for k in ("input_tokens", "output_tokens")}
    summary = {"model": model, "tokens_total": tokens,
               "tokens_per_question": {k: round(v / max(len(rows), 1)) for k, v in tokens.items()}, "run_at": datetime.now().isoformat(timespec="seconds"), **summarize(rows)}
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + model.replace(":", "_").replace("/", "_")
    (out_dir / f"{stamp}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) + "\n")
    (out_dir / f"{stamp}-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nDetails: eval/results/{stamp}.jsonl")


if __name__ == "__main__":
    main()
