# Synthetic evaluation

Run these scripts from the repository root:

```bash
backend/.venv/bin/python eval/corrupt.py
backend/.venv/bin/python eval/run_eval.py
```

`corrupt.py` writes twelve deterministic synthetic cases to `eval/results/corruptions.json`. They cover changed dose, frequency, duration, as-needed instruction, continuation, restriction threshold, follow-up timeframe, numeric date, dropped negation, unsupported clinician attribution, and stop/continue conflict for a configured high-alert medication.

`run_eval.py` compares section-based extraction against the gold facts for every `data/synthetic/doc_*.txt` file (each requires a matching gold JSON), evaluates each controlled mutation against its expected reason code, measures detector flags on clean controls, and reports claim routing counts. Results are saved to `eval/results/latest.json`.

The extraction report includes exact fact precision, recall, and F1 overall and by authoring style (`template` versus `curated_narrative`), exact source-link accuracy, per-document counts, clean/trap counts, and a SHA-256 fingerprint over all source and gold files. These strata expose errors hidden by the aggregate score, but there are currently only a small number of curated narratives; style-level results are descriptive and too small for generalization. Inspect `per_document` and `style_metrics` before quoting a headline result.

The corruption report also records clean and corrupted review-priority-score summaries. Every claim remains in human review; these scores only order the queue and are not probabilities or accuracy measures.

The current run is a smoke evaluation, not a performance study: the extraction score uses 59 synthetic documents (45 clean and 14 trap) and 340 exact labeled facts. The corpus has 50 template documents and 9 curated narrative documents, including medication-conflict traps. The current run scored 1.00 exact extraction F1 in both styles (template: 50 documents, 302 facts; curated narrative: 9 documents, 38 facts) and matched all 340 source links. The cross-fact medication-conflict detector caught 14/14 traps (10 stop/continue, 2 dose, 1 frequency, and 1 duration conflict) and flagged 0/45 clean documents. The verifier harness detected 12/12 hand-authored claim mutations and flagged 0/11 clean controls. The medication-name check recognizes only a small configured generic-name subset. These results measure the current templates, curated narratives, and hand-authored cases only; do not generalize them to other documents or patients. The harness does not evaluate LLM extraction, the optional live entailment judge, translation meaning, or clinical correctness.

## Held-out varied-summary review set

`heldout/cases.json` is a separate 40-case synthetic set with varied note layouts, abbreviations, and messy wording. It includes paraphrased unsupported claims, small medication changes, polarity changes, omitted medication details, and mismatched source links. Keep the existing templated cases as regression tests; this held-out set is a review set and must not be used to tune thresholds. A case set is not human evaluation: the author-created expected labels are hidden from the reviewer worksheet and are not clinician adjudication.

Run the pinned 1.7B judge and deterministic verifier after Ollama is available:

```bash
backend/.venv/bin/python eval/run_heldout.py
```

The runner checks `/api/tags` and requires the pinned `qwen3:1.7b` digest before writing predictions. The current 40-case run is saved in `heldout/system_predictions.json`; the judge assessed 32 claims and skipped the 8 deliberately mismatched source links because those citations cannot be trusted. These are model outputs, not human labels. A qualified nurse, clinician, or medical student should independently fill `heldout/reviewer_labels.csv`, marking unsupported additions, missing details, medication changes, wrong source links, and overall support. Then run:

```bash
backend/.venv/bin/python eval/score_heldout_reviews.py
```

The scoring report gives miss and false-alarm rates for each deterministic error category and reports agreement between the 1.7B judge and human overall-support labels. It requires complete reviewer credentials and labels; no misses, false alarms, or human-agreement results are claimed until that adjudication is completed. Keep reviewer labels blinded to `author_expected_labels` until review is finished. This synthetic set cannot establish clinical performance or safety.

### Verification ablation and repeatability

To compare pass-through, the LLM judge alone, deterministic checks alone, and the full verifier on the same 40 challenge cases plus 40 clean controls, run:

```bash
backend/.venv/bin/python eval/run_verification_ablation.py --cases eval/heldout/ablation_cases.json --output eval/heldout/verification_ablation_controls.json --models qwen3:1.7b qwen3:8b --repeats 5 --resume
```

The runner writes case-level trials to the output JSON after each case, so interrupted runs can resume. It requires each exact model tag to be installed in the local Ollama service. A result passes only if it is explicitly supported with no review flags; unresolved results count as failed. The controls are exact copies of source sentences with matching source IDs. The summary is `heldout/verification_ablation_summary.md`. Both challenge labels and control construction are synthetic and author-specified; report them as diagnostic results, not clinician-adjudicated accuracy or general false-alarm estimates. Report flip rates only for models with all requested repeats complete.

Run `backend/.venv/bin/python eval/evaluate_local_explanations.py` to generate 12 fixed synthetic facts with the configured local Ollama model (`qwen3:1.7b` by default). Add `--include-corpus --output eval/results/local_model_corpus_quality.json` to also run every distinct fact text in the synthetic corpus (currently 191 unique texts). To compare another model already installed in Ollama, pass its exact tag, for example `--model-id phi:latest`; use `--limit 3` for a quick bounded check. The script never pulls or downloads models. The result records each generated output and deterministic verifier decision. Use `--rescore-existing <report.json>` to apply current verifier rules to saved outputs without calling Ollama again. The expanded 203-case Qwen audit is saved at `eval/results/local_model_corpus_quality_59_docs_rescored.json`; it routed 12 outputs for deterministic review and 26 high-alert claims for expected human review. A Qwen-generated narrative draft set was excluded after it omitted or changed fixed facts; the curated narrative examples are labeled as such. A two-case `phi:latest` smoke audit initially exposed two equivalent frequency/duration phrasings; after updating normalization, rescoring flagged neither case. See `eval/results/local_model_phi_smoke_rescored.json`. This synthetic corpus is not independently adjudicated; it does not measure model accuracy or clinical safety, and deterministic checks can miss semantic errors.


Run `backend/.venv/bin/python eval/evaluate_translation.py` to generate the synthetic local-model translation audit and bilingual adjudication sheet described below. The script first checks `http://localhost:11434/api/tags` (derived from `LLM_BASE_URL`) and requires the pinned `MODEL_ID` tag and digest to be installed. If Ollama is down or that model version is missing, it exits with an error before writing either artifact; it never reports an endpoint failure as a completed 0/N audit. The latest `eval/results/translation_audit.json` run used `qwen3:1.7b` (digest `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`): the script completed and saved outputs for 6 synthetic cases; 2/6 (33.3%) preserved every protected name and detail verbatim, and 0/6 had human semantic ratings. This establishes script completion and token preservation only. It does not show that the Hindi is accurate, safe, or understandable. Hindi output is **machine translation, not validated** until a qualified bilingual reviewer completes the semantic review.

## Bilingual human adjudication

`translation_cases.json` contains six independently authored, synthetic English source sentences for Hindi, covering medication instructions, follow-up, warning signs, and restrictions. Run:

```bash
backend/.venv/bin/python eval/evaluate_translation.py
```

The script produces the model outputs and writes the exact source/output pairs to `eval/results/translation_adjudication.csv`. Ratings are tied to a hash of the exact Hindi output, so if a regenerated output differs, an older rating is not reused. A stale output-cell bug in the earlier CSV was fixed; the current worksheet now matches `translation_audit.json`.

To rate the translations, serve the repository locally and open the offline review form:

```bash
python3 -m http.server 8765
```

Open [http://localhost:8765/eval/translation_review.html](http://localhost:8765/eval/translation_review.html), choose `eval/results/translation_audit.json`, enter reviewer identity and qualification, and rate each English/Hindi pair. The form records semantic fidelity, preservation of critical details, omissions, additions, readability, naturalness, an acceptable/revise/reject decision, issue categories, notes, and an optional corrected Hindi version. It saves draft entries in that browser's local storage and exports a CSV when all cases are complete; the audit text stays local to the machine. Replace `eval/results/translation_adjudication.csv` with the exported file, then update the report without running the model again:

```bash
backend/.venv/bin/python eval/evaluate_translation.py --summarize-reviews
```

The report summarizes means, detail-preservation rate, omissions, additions, reviewer decisions, and corrected outputs. A revise/reject decision needs a correction or explanatory note. A poor rating means keep that output out of use; use the reviewer correction for the individual case, inspect repeated error types, revise the prompt/terminology and rerun the audit, or use a professionally translated and bilingual-reviewed workflow if errors persist. A rating only describes these reviewed synthetic examples: one reviewer does not establish general Hindi translation quality or clinical safety. Collect a second independent reviewer if you need reviewer-agreement estimates.

These source cases are authored separately from the templated document corpus, but they are synthetic and have not been clinically authored or independently translated. The script does not invent reference translations or assess semantic quality automatically. Token preservation is reported separately and is not a translation score. Ratings are descriptive and do not establish clinical performance or safety.

The current corpus is English text, not scanned-page images. OCR is enabled for scanned PDFs when local Tesseract is installed, but OCR accuracy has not been benchmarked. Review the recognized source page manually; a page that cannot be read causes the upload to fail rather than accepting partial text.
