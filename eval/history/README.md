# Evaluation history

Single runs recorded while tuning the agents after the first live review, kept so the
numbers in the main README can be traced. All runs: `qwen2.5-coder:7b` through Ollama
(about 70% of the model offloaded to an RTX 4050 Laptop GPU, 16k context), temperature 0,
the 26 cases in `eval/cases/`. Single runs differ by one or two findings from noise alone.

| Report | Commit | What changed |
|---|---|---|
| [1-baseline](2026-10-16-1-baseline-ad63b60.md) | `ad63b60` | Before tuning. |
| [2-v1](2026-10-16-2-v1-d49d176.md) | `d49d176` | Secret scan (scored separately), finding categories with off-category drops, coverage hint, step-by-step tests prompt, "report each vulnerability separately" in the security prompt. |
| [3-v2](2026-10-16-3-v2-306acde.md) | `306acde` | Tests prompt back to the checklist, covered/untested coverage hints, trivial and rename-only edits ignored, security sentence removed. |

After v2 the test reviewer's note was given one more sentence (`a65b45f`) and the prompts
were frozen. The final numbers, three runs each on the tuning set and on the held-out set
in `eval/cases_holdout/`, are in [../results.md](../results.md) and
[../results_holdout.md](../results_holdout.md). A first held-out attempt was discarded: the
machine went to sleep during its second run and Ollama stopped. Its one complete run had
5 TP / 11 FP / 1 FN (it missed the `list.pop(0)` case); the three final runs found that case
every time.

The baseline report has no secret-scan row because the scan did not exist yet; from v1 on,
the agent rows measure the LLM alone and the scan is scored on its own row.
