# Evaluation data

* `golden_set.jsonl` — your ~100-question golden set (30 factual, 25 numeric, 20 multi-hop, 15 multi-document,
  10 unanswerable). Schema: `{"id","type","question","answer","evidence":[{"doc_id","page"}],"verified"}`; pages are
  0-indexed.
  * Draft it: `finsight golden generate --config ml/configs/hybrid.yaml` (uses the configured LLM).
  * **Then review it by hand** — fix or delete bad questions, check the evidence page, and set `"verified": true`.
    Unverified items are ignored by `finsight eval --dataset golden` and by the CI gate.
  * `finsight golden summary` shows how many are verified, by type.
* `baseline_metrics.json` — a saved `finsight eval` result (`data/processed/eval/<config>.json`) that the CI gate
  compares against. Refresh it deliberately when you accept a new baseline.
