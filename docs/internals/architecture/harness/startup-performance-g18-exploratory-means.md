# G18 Exploratory Mean Startup Comparison

## Authority and scope

On 2026-09-11 the user requested continuing with average speed improvements as
the priority. This authorizes a small **exploratory A/B** despite the unaccepted
native A/A, not a retrospective relaxation of formal performance gates. The
[formal delivery record](startup-performance-g18-linux-delivery.md) and its
inconclusive evidence remain unchanged in classification. No push or merge.

Use the frozen original A `5f7346bb93c0b58203f60450a50cbf54c5713cec` and lazy
facade B `537cc91099a1a48bf16ec15f9d20772a6204737a`, their existing independently
verified wheels and `install-a`/`install-b`. No Product or collector edits.

## Bounded measurement

- Invoke the existing `measure_g18_startup.py`, two blocks, three pairs per
  block, all ten built-in import/help/version cases. No case selection.
- Each case has six measured A/B pairs plus four declared warmups (one per
  side/block): 120 observations used for means, 40 excluded warmups, 160 total.
- Preserve the original alternating side order and reversed second-block case
  order. Keep private per-sample app state, installation-private warm bytecode,
  fresh processes, original timeout/output/cleanup validation, source/wheel/
  installation/helper checks, private parent environment and `/var/tmp` scratch.
- Fresh output `.artifacts/g18-linux-delivery/inert-ab-exploratory-mean-01`.
  Do not run tests, builds, reviews or diagnostic samplers during collection.
  Stop on failure and retain the partial report; no automatic retries.
- The original comparator deliberately remains `not-evaluated` for this small
  sample count. Do not alter it or call a descriptive mean a formal pass.

## Interpretation

Report each case's arithmetic mean elapsed time for A and B, mean saved time
`mean(A) - mean(B)`, and reduction `1 - mean(B)/mean(A)`. Each case has equal
pair counts, so mean paired difference equals the difference of these means.
Also retain block means, median, range, CPU means and paired direction counts
to reveal noise or inconsistent direction. Include every valid measured sample,
including outliers and slower B samples; exclude only predeclared warmups.

Do not combine different entrypoints into an unweighted universal speedup or
extrapolate help/import gains to TUI readiness, recovery, first model/tool use,
settlement or another platform. Six pairs are an initial estimate, not a
confidence guarantee. The two installation paths and uncontrolled OS/page-cache
conditions also limit attribution. Existing same-wheel A/A timings are not B
measurements and will not be pooled into these means.

## Result — 2026-09-11

Status: complete exploratory comparison, not formal acceptance. Exec 84243 exited
0; collection ran 06:23:53.846980–06:35:37.339514 UTC. Parent environment:
`/var/tmp/lg18-tests-uLWOLO`; retained scratch:
`/var/tmp/loushang-g18-baseline-6h9f805k`.

Report: `.artifacts/g18-linux-delivery/inert-ab-exploratory-mean-01/report.json`,
SHA256 `90c8324a60dcfb3f4e955a4efb5c6a2efa396774164510117cfa1eacdfd698d5`.
The sibling `means.json` binds that report hash and retains each case's unrounded
means, medians, ranges, block means, CPU means, all six paired differences and
direction counts. Derived statistics do not modify the original report.

All 160 observations are valid with exit 0 and no recorded failure. Exact expected
case/block/pair/side/warmup identities and order were independently reconstructed
and checked, including 120 measured observations and 40 declared warmups. Source
commits, distinct frozen A/B wheels, before/after helpers and collector's final
installation checks match. No Product or collector implementation was changed.
The original small-sample comparator remains `not-evaluated` as planned.

Arithmetic means below are in seconds. Positive reduction means less elapsed
time; negative means B was slower. Each row uses all six measured samples per
side; none were removed for being slow.

| Entry | A mean | B mean | Reduction | B faster pairs |
| --- | ---: | ---: | ---: | ---: |
| import-harness | 0.0598 | 0.0522 | 12.73% | 4/6 |
| import-coding | 3.5469 | 0.0554 | 98.44% | 6/6 |
| import-cli | 4.9803 | 5.2310 | -5.03% | 0/6 |
| cli-help | 8.3765 | 8.2117 | 1.97% | 2/6 |
| cli-version | 4.8600 | 4.9903 | -2.68% | 2/6 |
| tui-help | 7.8341 | 8.3318 | -6.35% | 1/6 |
| hosted-help | 3.9107 | 3.8627 | 1.23% | 3/6 |
| hosted-tui-help | 3.6448 | 2.5934 | 28.85% | 6/6 |
| mux-help | 3.7777 | 2.6388 | 30.15% | 6/6 |
| plugin-help | 0.7316 | 0.7547 | -3.15% | 2/6 |

The strongest observed improvements are import-coding (3.492 seconds saved),
hosted-tui-help (1.051 seconds) and mux-help (1.139 seconds). Each improves in
both blocks and every pair. Recorded mean CPU time also decreases respectively
from 3.2082 to 0.0489, 3.3221 to 2.3400, and 3.4790 to 2.4262 seconds; the
observation is not limited to reduced wall-clock delay. This is preliminary
evidence of scoped lazy-facade benefit, not a confidence estimate or a claim
that first-use costs disappeared rather than being deferred.

Ordinary cli-help is essentially unchanged in its median (8.2040 versus 8.2088
seconds), and B wins only two pairs despite its slightly better mean. Do not
advertise that 1.97% as a reliable improvement. Import-cli is slower in all six
pairs, and tui-help is slower in five; retain these negative observations for
follow-up rather than describing the candidate as universally faster. The
unchanged import-harness control differs by only 7.61 ms, illustrating why a
percentage alone can mislead on very short paths. Small differences in controls
do not justify subtracting noise or adjusting the measured gains.

## Development implication

The lazy package facade has a useful initial result on import-coding and the
hosted client/mux help paths, but not on the ordinary CLI/TUI help path. Static
inspection shows `coding.cli.__main__` still imports bootstrap, runtime adapters,
workflow and UI code at module load, while `coding.ui.cli` eagerly imports its
`run_cli`. A separate lightweight CLI/help/version boundary is therefore a
reasonable next optimization hypothesis, not a confirmed explanation of every
timing difference. Preserve actual argument parsing, help output and exit
semantics; measure the resulting candidate rather than claiming those savings
in advance. This run does not implement that next change or extend dispatch or
lifecycle semantics.

No full native A/B was run, no formal checklist was marked passed, no historical
report was relabeled, and no push/merge was performed.
