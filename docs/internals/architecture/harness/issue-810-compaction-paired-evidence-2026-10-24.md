# Issue #810: Paired Compaction Evidence (2026-10-24)

## Question and method

Does the opt-in `local_combined` strategy save time or money while retaining
continuation-critical history compared with the default `local_separate` strategy?

Two fixed, synthetic split-turn cases were run through the real Coding compaction
adapter. Each has 36 older conversation messages and two messages from an unfinished
turn. The initial case supplies no previous checkpoint; the update case adds a
structured previous checkpoint and one extra legacy marker. The older conversation
serializes to 18,342 UTF-8 bytes before prompt overhead. All strategy/model pairs
received the same case. Repetitions alternate execution order: separate then
combined for odd repetitions, reversed for even repetitions. Each compaction call
records elapsed time, prompt UTF-8 bytes, returned usage, and catalog-derived cost.
The benchmark runs only with `--live` and writes full synthetic outputs locally under
`.artifacts/compaction/`.

After compaction, a separate run asks the same model to explain the unfinished
resume error, release condition, writer invariant, and compatibility error from
each checkpoint. The five checked facts are `ERR_RETRY_GAP`, `qa-17`,
`checkpoint-v2`, `single writer` (including the hyphenated spelling), and
`CTX-409`. The update case also checks `LEGACY-KEEP-42` in the summary itself.
These exact-fact checks supplement, rather than replace, human judgment of
semantic quality. Four continuation answers were spot-checked for the correct
relationships among the facts.

The [machine-readable samples](issue-810-compaction-paired-samples-2026-10-24.json)
retain every call measurement, synthetic summary, and follow-up answer for audit.

## Results

All completed compactions used two model calls for `local_separate` and one for
`local_combined`; no combined attempt fell back. The initial case retained 6/6
summary anchors in every run, the update case 7/7. All 20 follow-up answers
recovered 5/5 requested facts after normalizing `single-writer` to `single writer`.

| Model and case | Strategy | Repetitions, seconds | Median seconds | Median estimated cost per compaction |
| --- | --- | --- | ---: | ---: |
| Kimi Code K2.7, initial | separate | 24.511, 18.575 | 21.543 | unavailable |
| Kimi Code K2.7, initial | combined | 15.606, 14.850 | 15.228 | unavailable |
| Kimi Code K2.7, update | separate | 19.213, 12.667 | 15.940 | unavailable |
| Kimi Code K2.7, update | combined | 16.366, 28.500 | 22.433 | unavailable |
| DeepSeek V4 Flash, initial | separate | 10.469, 7.610, 8.800, 6.594 | 8.205 | $0.0004053 |
| DeepSeek V4 Flash, initial | combined | 8.736, 16.791, 10.520, 7.389 | 9.628 | $0.0007700 |
| DeepSeek V4 Flash, update | separate | 7.897, 7.271 | 7.584 | $0.0004196 |
| DeepSeek V4 Flash, update | combined | 11.666, 13.521 | 12.594 | $0.0007620 |

Kimi Code did not report usable token counts or per-token cost through this route.
DeepSeek costs are computed from returned token usage and the current model catalog
prices, not an invoice. Its repeated prompts received 3,456–3,712 cached input
tokens on the main calls after the first run; the first uncached initial pair cost
$0.0010416 (separate) and $0.0010158 (combined). Later costs depend strongly on
cache hits and output length. The median output-token count on DeepSeek initial
cases was 1,218 for separate and 1,915 for combined. This outweighed the saved
call in several runs. Request sizes were stable within each case: the initial
DeepSeek separate main prompt was 19,572 bytes plus a 1,115-byte turn-prefix
prompt; combined used one 20,431-byte prompt.

## Decision and limits

Keep `local_separate` as Coding's default. One model/case favored combined latency,
but update runs and DeepSeek did not. The one-call path remains an explicit opt-in.
This evidence covers short-to-moderate synthetic split-turn compactions, not the
whole-session latency/cost of changing the automatic trigger, very large histories,
or an OpenAI native provider compaction run. Issue #810 remains open for that
capacity-trigger and larger-session evaluation.

## Reproduction

From the repository root, with the relevant API key in the environment:

```sh
.venv/bin/python scripts/benchmarks/benchmark_compaction_strategies.py \
  --live --provider deepseek --endpoint openai-completions \
  --model deepseek-v4-flash --api-key-env DEEPSEEK_API_KEY \
  --case split-turn-initial --repetitions 4 \
  --output .artifacts/compaction/paired-deepseek-initial.json

.venv/bin/python scripts/benchmarks/benchmark_compaction_strategies.py \
  --live --provider deepseek --endpoint openai-completions \
  --model deepseek-v4-flash --api-key-env DEEPSEEK_API_KEY \
  --case split-turn-update --repetitions 2 \
  --output .artifacts/compaction/paired-deepseek-update.json

.venv/bin/python scripts/benchmarks/evaluate_compaction_continuation.py \
  --live --api-key-env DEEPSEEK_API_KEY \
  --input .artifacts/compaction/paired-deepseek-initial.json \
          .artifacts/compaction/paired-deepseek-update.json \
  --output .artifacts/compaction/continuation-deepseek.json
```

The Kimi Code run used provider `kimi-code`, endpoint `kimi-code-openai`, model
`kimi-for-coding`, and `KIMI_CODE_API_KEY` with two repetitions per case. The
initial Moonshot platform attempt failed authentication before producing a sample
and is excluded from the table.
