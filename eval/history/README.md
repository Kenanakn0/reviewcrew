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

The baseline report has no secret-scan row because the scan did not exist yet; from v1 on,
the agent rows measure the LLM alone and the scan is scored on its own row.
