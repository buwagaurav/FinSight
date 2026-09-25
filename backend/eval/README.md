# FinSight evaluation

Two separate questions, two separate tools:

| Question | Tool | Needs API key | Cost |
|---|---|---|---|
| Is FinSight's **data** right? | `check_data.py`: compares revenue, net profit and EPS with each company's audited XBRL filing on NSE | No | Free |
| Does the **assistant** report that data faithfully? | `run_eval.py`: asks `questions.jsonl` and grades every answer | Yes | ~125 multi-step Claude calls |

```bash
cd backend
../.venv/bin/python -m eval.check_data              # data accuracy -> eval/data_check.json
../.venv/bin/python -m eval.build_questions         # regenerate questions from current data
../.venv/bin/python -m eval.run_eval --limit 10     # try 10 questions first
../.venv/bin/python -m eval.run_eval --yes          # full run -> eval/results/<timestamp>-<model>*.json
../.venv/bin/python -m eval.run_eval --limit 20 --model deepseek:deepseek-flash   # compare models on the same questions
```

**questions.jsonl** has 125 questions over 20 companies: 80 lookups (a figure for a year), 40 calculations
(percentage change, CAGR) and 5 the assistant should decline (price predictions, yes/no buy calls). Expected
answers come from FinSight's own engine, so this measures faithfulness, not data truth; that is what
`check_data.py` is for. Regenerate the questions after the data refreshes (new fiscal year).

**Comparing models**: run the same questions with `--model provider:model-id` for each candidate. Each summary has
accuracy, grounded and cited rates, `confidently_wrong`, latency and tokens per question; multiply tokens by the
provider's price list to get cost per question.

**Grading** (`grade.py`): a numeric answer is correct if any figure in it is within the question's tolerance
(1% for ₹ amounts; 2-3% or 0.15 points for percentages). The summary also reports how often answers passed
FinSight's own grounding check and cited sources, and `confidently_wrong`: wrong answers that still passed the
grounding check, the most dangerous failure. "Should decline" grading is a heuristic; read those answers yourself.

**check_data.py notes**: NSE's annual XBRL often mislabels period dates, so the full-year column is taken as the
one with the largest revenue. Filed EPS is restated for later splits and bonus issues before comparing. Bank
revenue is skipped (definitions differ). This NSE endpoint currently covers filings up to FY24.
