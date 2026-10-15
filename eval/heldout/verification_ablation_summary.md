# Held-out verification results (binary pass/fail)

This experiment uses 40 synthetic challenge cases with deliberately incorrect explanations and 40 clean controls with source-exact explanations. Both Qwen models completed five repeats on the same 80 cases.

**Scoring rule:** A case **passes** only when the checker accepts it as supported with no review flags. A case **fails** if the checker does not confirm support, returns an error, or routes the case for review. For a deliberately bad challenge case, fail is the desired result; for a clean control, fail is a false alarm. This fail-closed rule reports only pass or fail.

## Headline results

| Check | Judge | Bad examples failed / 40 (caught) | Bad examples passed / 40 (missed) | Clean controls failed / 40 (false alarms) |
|---|---|---:|---:|---:|
| No verification | — | 0 | 40 | 0 |
| Deterministic checks only | — | 35 | 5 | 0 |
| LLM judge alone | Qwen 1.7B | 27 | 13 | 2 (5%) |
| Full verifier | Qwen 1.7B | 38 | 2 | 0 |
| LLM judge alone | Qwen 8B | 25 | 15 | 0 |
| Full verifier | Qwen 8B | 38 | 2 | 0 |

The full verifier caught 11 more bad examples than the Qwen 1.7B judge alone and 13 more than the Qwen 8B judge alone. It passed two bad explanations for each model. The two Qwen 1.7B judge-only false alarms were clean follow-up sentences; the full verifier passed them because they exactly matched their sources.

## Results by challenge type

Each challenge type has eight bad examples. The table shows **failed / passed**; on bad examples, a failure is a catch and a pass is a miss.

| Challenge type | Qwen 1.7B judge | Qwen 1.7B full | Qwen 8B judge | Qwen 8B full |
|---|---:|---:|---:|---:|
| Paraphrased claim change | 6 / 2 | 6 / 2 | 8 / 0 | 8 / 0 |
| Dose or schedule change | 8 / 0 | 8 / 0 | 8 / 0 | 8 / 0 |
| Negation or polarity change | 8 / 0 | 8 / 0 | 8 / 0 | 8 / 0 |
| Omitted detail | 5 / 3 | 8 / 0 | 1 / 7 | 6 / 2 |
| Wrong source link | 0 / 8 | 8 / 0 | 0 / 8 | 8 / 0 |

The deterministic source-link check catches all eight wrong-link examples that both judges alone pass. Omission is the weakest judge-only category, especially for Qwen 8B (1/8 caught); the full verifier catches 6/8 with that model.

## Controls, repeatability, and misses

The 40 controls are exact copies of supported sentences with matching source IDs. The Qwen 1.7B judge alone falsely failed two; Qwen 8B and both full verifiers falsely failed none. These are deliberately simple controls and do not estimate false alarms on clean paraphrases or broader documents.

There were 0 verdict flips across five repeats for either model, all 80 cases, and every condition. Repeatability does not establish correctness.

The full verifier misses for Qwen 1.7B were HO-006 (it accepted “There was no stomach irritation during admission” against a source saying gastritis improved and no bleeding was reported) and HO-008 (it accepted “The incision is fully healed” against a reassuring wound check). Qwen 8B missed HO-030 (the explanation dropped “until the clinic reviews it”) and HO-032 (it dropped “nightly”).

## Independence and limits

The workspace has no `.git` metadata or experiment history, so it is not possible to verify whether verifier rules were tuned against the 40 challenge cases. Do not treat these numbers as an independent accuracy estimate. The controls were added for this evaluation from the same synthetic documents, and their expected labels are author-written, not clinician-adjudicated. These results do not establish clinical performance or safety.

Raw five-repeat outputs are in `verification_ablation_controls.json`; the runner is `../run_verification_ablation.py`, and the combined input dataset is `ablation_cases.json`.
