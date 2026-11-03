# Tool exit to Worked: focused latency evidence

Status: the candidate branch meets the 500ms p95 goal in a 30-turn offline
native-screen matrix; pre-tool GC pauses remain open. The original focused
tool-completion investigation targeted 250ms. Broader experiments are recorded
in `issue-803-responsiveness-evidence-2026-10-20.md`.

## Measurement boundary

The start is the controlled tool service returning its result. The end is the
first flushed terminal frame containing the matching Worked divider. A real
POSIX PTY, native terminal reader, independent physical keyboard process,
prepared offline model transport and restored file-backed Session were used.
The authority was an isolated continuation with approximately 29,100 records;
the original session remained read-only. The measured source was `cb8fcaeb`.

The earlier five-pair silent-command comparison measured tool exit to Worked
p95 at 1,329.02ms before the input-waiter fix and 1,276.65ms after it. Five
normal turns each of streaming output, three tools, 1.08MB ASCII and 2.16MB
Unicode measured p95 between 1,357.84ms and 1,720.77ms on the current source.
Those four workloads have no matched earlier-version counterpart.

## One unprofiled long-session trace

This diagnostic turn took **1,159.16ms** from tool exit to visible Worked.
The following intervals are from timestamps emitted at actual boundaries;
the model input commit is additionally measured by its own phase timer.

| Tool-exit offset | Boundary or operation | Elapsed |
| ---: | --- | ---: |
| 0–113.55ms | Tool result conversion, publication and entry into the next model-call preparation | 113.55ms |
| 113.55–256.33ms | Session model-call preparation, including request evidence and codec setup | 142.78ms |
| 256.33–283.02ms | Scheduling and adapter admission | 26.69ms |
| 283.02–478.04ms | Provider adapter builds the prepared request from the long context | 195.02ms |
| about 478.52–953.86ms | Durable model input commit before transport | 475.34ms |
| 953.86–1,159.16ms | Offline response, terminal outcome and Worked projection/flush | 205.30ms |

Within the 475.34ms commit, prepared-request validation took 94.79ms, logical
input thaw 16.29ms, binary externalization 51.23ms, resolver construction
13.81ms, materialization 203.77ms and snapshot append 15.35ms. The completed
writer used its extended index cache and reused 2,912 sequence items. No
generation-two collection occurred between tool exit and Worked in this turn;
the measured delay is intrinsic to the current post-tool path, even without a
GC pause.

An optional main-thread profiler inflated this path to 3.17 seconds, so its
times are excluded from latency acceptance. Its call counts locate repeated
full-context work across provider request construction, JSON validation,
canonicalization, transcript materialization and final projection. The
unprofiled stage timestamps above are the latency evidence.

Both diagnostic turns retained their draft, emitted one Worked divider and
executed no historical tools. Native reopening reconstructed four model input
snapshots with terminal usage and checked both tool results; the authority was
unchanged by verification.

## Prefix reuse boundary

One later isolated turn counted object identities on both sides of Agent's
message conversion. After the controlled tool, all 1,467 earlier Agent messages
were the same objects seen before it. The prepared adapter then received 1,469
normalized messages, and none of the 1,467 earlier positions retained object
identity across the two model calls. The converter and normalization boundary
therefore discards an identity-only cache key before provider preparation.

This is a feasibility observation, not permission to trust object identity:
message parts can contain mutable containers, and conversion, provider options
or the selected transcript path can change. Reuse must carry explicit immutable
provenance from the selected transcript and recheck the final suffix before
publishing a prepared request. The diagnostic turn's two snapshots, terminal
usage and tool output were rebuilt on native reopening without historical tool
execution or authority changes. Its extra identity logging is excluded from
latency acceptance.

Native reconstruction of two further ordinary silent-command continuations
checked the exact serialized requests. In the shorter history, both logical
and prepared message lists grew from 231 to 233; in the longer history they
grew from 1,459 to 1,461. In each case the entire earlier message list was an
equal prefix and every non-message field was equal. Both authorities stayed
unchanged. This establishes that an append-only reuse path is applicable to
these turns; it does not establish a safe cache key for conversions, mutation,
branch changes, provider options or other tool cases.

## Post-commit work

A further instrumented turn located work after the prepared-request snapshot
was durably committed. Its adapter began offline invocation about 5ms after
the commit. The attempt-usage recorder then took 63.66ms, including a 50.04ms
durable append. The terminal-outcome recorder took 33.00ms, including a
32.85ms durable append. The final Session check took 10.32ms, followed by
prompt completion and the Worked flush. The interval from snapshot commit to
visible Worked was about 207ms in this diagnostic turn. It includes transport
payload projection and model event processing in addition to the named phases.
The extra tracing makes this a stage-location result, not a comparable p95.

The success path therefore has little room for post-commit work under a
250ms end-to-end target. Any prefix-staging design must preserve terminal
attempt usage and model outcome recovery semantics. The current implementation
awaits their append attempts before Worked. Whether Worked must await successful
terminal-observation durability is a separate design choice: ordinary recorder
failures are already traced and swallowed, and recovery classifies a missing
terminal outcome as unknown. Native reopening of
this turn verified both snapshots, terminal usage and its tool output without
executing historical tools or changing the authority.

## Owned prepared envelope

The AI-prepared request now retains the original recursively frozen payload,
headers, canonical JSON and digest as one owned envelope. The committer checks
that these exact fields still belong to that envelope, thaws the immutable
payload once, and uses the already computed canonical identity. A replaced
field follows the existing full-validation path; malformed or changed
payloads are still rejected before any Model Input write. A regression test
forbids a second canonicalization and JSON validation of an untouched envelope,
and four tests cover changes to its payload, headers, canonical string and
digest. Transport projection also rejects a replaced payload or visible header,
so it cannot send a different envelope after the committed snapshot. Transport
now copies the same frozen tree without another JSON validation scan or digest
recalculation. The focused AI/Model Input suites passed with 119 tests and one
skip; `make check-ai` passed with 871 offline tests.

In one 29,193-record native PTY diagnostic, the post-tool prepared-request
validation phase was 13.47ms, compared with 94.79ms in the earlier long-session
trace. These are separate turns, not a matched p95. The same new turn still
took 1,467.38ms from tool exit to Worked; other post-tool phases and scheduling
remain substantial. Native reopening verified its two snapshots, terminal
usage and tool output, with zero historical tool executions and no change to
the original authority. The broader Harness typecheck currently reports six
errors in unrelated sandbox PID-namespace typing; the changed transcript
module passes focused mypy.

One final-code 24,459-record native PTY turn completed and showed one Worked
after 1,046.33ms. Its prepared-request validation took 2.51ms. A 495.55ms
logical-input thaw in that turn is anomalous against earlier turns and needs
separate attribution; this single run cannot establish an end-to-end
improvement. Native reopening again verified both snapshots, terminal usage and
the tool result without executing history or changing the original authority.

## Tool-phase allocation experiment rejected

A later GC-instrumented turn located one 695.61ms main-thread generation-two
collection inside the post-tool binary-externalization phase. That phase took
708.23ms, while the same phase ordinarily took about 9–12ms in this shorter
history. The earlier 29,100-record trace had no post-tool generation-two
collection, so GC is an intermittent tail amplifier rather than the sole cause
of the slow path.

A private candidate made the built-in blob codec share unchanged subtrees of
the committer's exclusively owned logical/prepared JSON. The public default
continued making independent copies, and custom codecs kept the prior call
route. Image, literal-marker, Model Input and static checks passed. Five
alternating real-PTY pairs used the same read-only 24,459-record seed, offline
model transport, a controlled silent command, and a native reopen after every
turn:

| Measure | Baseline `d3190fcd` | Candidate |
| --- | ---: | ---: |
| Tool exit to Worked median | 1,027.36ms | 817.06ms |
| Tool exit to Worked p95 | 1,102.86ms | 1,635.31ms |
| Main-thread generation-two collections, five turns | 4 | 3 |

All ten reports, twenty snapshots with terminal usage and ten outputs rebuilt
successfully; no historical tool ran, drafts and durable-before-send held, and
the seed authority remained unchanged. The candidate's worst turn had a
920.67ms main-thread collection and took 1,781.38ms to Worked. Both variants
still took more than 500ms even in turns without a main-thread generation-two
collection. The candidate was reverted: sharing unchanged blob subtrees did
not control the tail or approach the 250ms objective. No Product GC policy or
threshold was changed.

On a later approximately 29,400-record isolated continuation with the
evidence-free replay fixes, a 315.15ms main-thread generation-two collection
fell inside the post-tool prepared-request validation phase (329.5ms). Worked
arrived after 1,350.52ms; maximum loop delay was 329.1ms and keyboard echo
latency reached 562.4ms. Native reopening reconstructed its two snapshots,
terminal usage and output without changing the original authority or invoking
historical tools. A renewed owned-tree copy-on-write micro check did not
contradict the five-pair rejection above: on the same isolated history, median
logical projection was 26.08ms detached versus 26.36ms owned, and prepared
projection was 26.77ms versus 24.56ms. Its Product candidate was reverted after
98 focused tests passed; no copy-on-write Product change remains. The repeat
is diagnostic only and does not justify another latency acceptance claim.

## Exact prefix-mutation proof feasibility

A private read-only check timed exact comparison of restored historical Agent
messages against a copy. It used type-sensitive recursive equality, then a
restricted byte serialization that accepts only the built-in message, part and
usage dataclasses and ordinary containers. The latter never deserializes the
bytes, does not run custom reducers, rejects unknown object types, and detects
both an altered nested part and a boolean-to-integer change.

| Context | Recursive comparison median | Restricted bytes median | Serialize every message median |
| --- | ---: | ---: | ---: |
| 234 messages, 24,475 records | 14.18ms | 3.91ms | 4.43ms |
| 1,474 messages, 29,193 records | 68.30ms | 22.44ms | 24.69ms |

Seven warm samples formed each median. Both source authorities remained byte-
and mtime-stable, and no historical tool executed. This checks reconstructed
messages; it is not an Agent/Provider integration test or a matched PTY result.
Per-message restricted serialization was 25.77ms in the longer context,
approximately the same as serializing all messages again. An isolated logical-
message cache therefore cannot materially reduce the post-tool path. The
restricted proof is useful only if it authorizes reuse of the larger
normalization, prepared-request and Model Input prefix work.

## Normalization-only prefix reuse rejected

A temporary AI cache reused a normalized message prefix only after checking
the prior raw and normalized messages, unchanged model target and pairing mode,
a closed tool boundary, and disjoint historical/new tool-call IDs. It fell back
to full normalization after nested mutation, an incomplete tool pair, a model
change or a potentially late tool result. Six focused cache regressions and
the existing 59 context tests passed; Ruff and focused mypy passed. The
candidate was then removed without a Product commit.

Real PTY diagnostics on isolated session copies showed why this seam is too
small. On 24,459 records, the cache hit spent 21.46ms checking the prefix and
23.47ms total in normalization; tool exit to Worked was 554.44ms. On a
29,209-record copy with roughly 1,479 messages, the cache hit spent 111.95ms
checking the prefix and 117.19ms total in normalization; Worked arrived after
1,340.09ms. These are diagnostics rather than matched before/after p95s. The
longer run still spent 299.81ms in adapter preparation, 454.64ms in durable
Model Input commit, and roughly 200ms after commit. A cache limited to AI
normalization therefore cannot meet the 250ms end-to-end target and can add
main-thread work to shorter contexts.

A separate native PTY stage trace on the same long-history scale located
PreparedModelRequest construction inside adapter preparation: 194.59ms of a
220.18ms adapter phase. Its projected-payload copy took 44.73ms and metrics
scan took 60.82ms. The subsequent durable commit took 432.06ms, with
216.30ms in v2 materialization; its plan and roots phases took 68.29ms and
84.81ms. The normalizer-only prototype did not reuse any of these stages.
The next candidate must stage or incrementally prove the prepared payload and
Model Input prefix together, then verify the total PTY latency.

Two further private feasibility checks excluded isolated substitutes for that
shared prefix. A request-preparation wrapper executed the offline adapter's
synchronous `prepare_request` in an asyncio worker thread, while retaining the
same capacity and durable-before-send barriers. One later sequential native
PTY turn took 1,358.6ms from tool exit to Worked, with a 323.6ms main-thread
generation-two collection and 503.2ms maximum keyboard echo latency. Native
reopening verified its two snapshots, terminal usage and one output without
altering the original authority. This is not a matched comparison, and the
single turn does not justify a thread-affinity change to all adapters.

On the isolated 1,533-item logical and prepared message arrays, seven warm
read-only samples compared exact prefix proof mechanisms. Type-sensitive
recursive equality took 21.60ms and 21.34ms median; native canonical JSON
encoding and comparison took 28.75ms and 30.05ms; the validated canonical
encoder took 53.87ms and 53.86ms. Replacing only the v2 writer's existing
equality proof with canonicalization would add work. A useful prefix cache must
reuse normalization, adapter payload and Model Input plans as one proven unit.

## Exact tool-exit-to-Worked allocation

The 1,340.09ms experimental turn above and a fresh 1,099.87ms turn on current
`3881eb56` code used separate isolated copies of the same 29,209-record
history, a real PTY, one silent tool process and offline model transport.
Both were diagnostic single turns, not matched p95 comparisons. The first
column includes the reverted normalization cache; the second does not.

| Interval from actual process exit | Experimental 1.34s turn | Current code 1.10s turn |
| --- | ---: | ---: |
| Result publication and admission until Session preparation starts | 124.71ms | 133.45ms |
| Session model-call preparation | 127.14ms | 146.57ms |
| AI normalization and resolution until adapter preparation starts | 125.65ms | 26.82ms |
| Adapter prepared-request construction | 299.81ms | 198.14ms |
| Adapter end through durable Model Input commit | 455.22ms | 401.03ms |
| Durable commit through first visible Worked frame | 207.57ms | 193.87ms |
| **Total** | **1,340.09ms** | **1,099.87ms** |

Result conversion itself took under 0.2ms in both traces. The first interval
also includes result publication, next-call context work and scheduling; those
substeps need finer instrumentation before assigning their individual costs.
For the current turn, PreparedModelRequest construction used 175.82ms of the
198.14ms adapter interval; its payload projection and metrics pass used
35.53ms and 57.76ms respectively. The 400.52ms commit included 49.59ms of
binary externalization and 206.27ms of v2 materialization, of which plan and
roots used 68.32ms and 81.34ms. The remaining phase-timer difference is not
yet attributed to a single operation. After commit, terminal usage and outcome
appends took 57.56ms and 48.85ms, the final Session check took 14.94ms, and
model return, intervening scheduling and visible rendering filled the rest.

The current-code turn recorded a 686.50ms maximum event-loop delay and
689.76ms maximum input echo latency. Thus the observed freeze is real main-
loop unavailability, not only slow Worked labeling. Native reopening verified
both Model Input snapshots and terminal usage, the one tool-output hash and
truncation state, an unchanged post-run copy during read-only verification,
and zero historical tool calls.

## Canonical prepared-envelope metrics

The prepared-request constructor now obtains message and tool-schema byte
counts from the same canonical encoding used for the full request, avoiding a
second JSON encoding of the historical message list. On the isolated
29,209-record continuation's rebuilt 1,481-item payload, seven alternating
read-only micro samples measured the former canonical-and-size step at 62.51ms
median and the single-encoding step at 38.31ms median. Their canonical bytes
and both size metrics were exactly equal; the source authority bytes and mtime
were unchanged. The focused AI suite passed 41 tests, and `make check-ai`
passed 874 offline tests with 90.63% coverage. These are local stage results,
not a matched real-PTY Worked p95 or evidence of the 250ms target.

## Streaming mapping-root hash

The v2 mapping-root hash now consumes canonical sequence items directly,
without joining the full historical list into an intermediate string. On the
same isolated long-session copy, seven read-only micro samples of the 1,485-item
prepared sequence measured 25.30ms median for the former join-and-hash path
and 10.67ms for streaming, with identical SHA-256 results. One instrumented
real-PTY continuation measured its post-tool root phase at 71.39ms before and
59.56ms after; overall Worked times were 1,281.22ms and 1,401.89ms. These
are different sequential turns, not matched pairs, and the total does not
establish an improvement. Native reopening verified four snapshots with
terminal usage and two outputs, with unchanged authority and zero historical
tool calls. The Model Input and Session model-call suites passed 132 tests.

## Next work

An event-path timing probe on the same long-session scale measured one
post-tool continuation with 111.86ms in the awaited Tool-result append,
approximately 91ms between the following turn start and Session preparation
before the synchronous Session preparer, and 238.29ms in Session
preparation. That preparation included 57.23ms of logical-input serialization,
32.35ms of request-evidence projection, and 143.88ms creating the committer;
the latter included 48.25ms constructing its blob codec. Instrumentation and
turn-to-turn variation make these diagnostic allocations, not comparable p95s.

Subsequent direct timing of the same path attributed a 94.56ms pre-preparer
interval to `prepare_model_input_async`, which cooperatively recovers Resource
evidence. Session-graph preparation was 0.10ms in that turn. The extension
context transformer and its deep copy were not invoked. A separate read-only
micro sample found context-to-model conversion below 2ms for roughly 1,500
messages, so neither transformation explains this interval. This was another
sequential turn, with 1,922.32ms from tool exit to Worked, and is not a matched
before/after comparison.

The asynchronous recovery previously replayed all context message bindings
whenever the appended suffix contained a Model Input snapshot, even when that
snapshot had no Resource evidence component. A regression test first failed on
this unnecessary replay. Recovery now obtains the bindings lazily only after
reading a nonempty Resource evidence component; the final request projection
still checks its exact message-to-record bindings. The evidence-free and
snapshot-evidence tests, Agent Product contract tests, and Coding Model Input
tests passed (70 total). A later sequential, instrumented native-PTY turn on
the same long-session copy measured recovery at 65.44ms versus 94.56ms in the
previous turn, and tool-exit-to-Worked at 1,838.89ms versus 1,922.32ms. These
turns are not matched pairs and establish only the stage attribution, not a
p95 gain. Native reopening verified two snapshots with terminal usage and the
tool output, with original authority unchanged and no historical tool calls.
Ruff and focused mypy passed. `make check-harness` stopped at six mypy errors
in the unchanged sandbox package legacy runtime, before running its test target.

The user requested no transcript replay in the ordinary live tool path. A
second regression test first failed because evidence-free request projection
still requested context bindings despite having no committed or recovered
Resource evidence. Projection now validates selected-path records and hydrates
new evidence first, then skips context binding when both evidence maps are
empty. Evidence-bearing requests retain their exact record-to-message checks.
The existing transcript Unit of Work already caches ordinary append-only
context projection; branch changes and resumed sessions use the checkpoint
aware replay path. One later sequential native-PTY turn on the same long copy
recorded no context-binding call in post-tool Resource evidence projection,
which took 16.18ms; Session preparation took 145.37ms and tool exit to Worked
was 1,682.45ms. This remains diagnostic only. The focused evidence, Agent
Product, and Coding Model Input suites passed 70 tests; native reopening
verified two snapshots with terminal usage and one output without modifying
the original authority or executing historical tools.

For resume, the latest compaction checkpoint is the context boundary: restore
its summary, the retained records from `first_kept_record_id` up to that
checkpoint, and records after it. Replaying only records after the checkpoint
would omit intentionally retained context. The current replay folder still
reduces state over the whole selected path, because model selection, metadata,
annotations and similar state may originate before compaction. Any resume
optimization needs a separate, validated state checkpoint before it can skip
that reduction. The append-only live path should keep using its incremental
projection; it does not need to replay the transcript on each tool result.

A private candidate indexed only record types that might carry blob references
while still rechecking their mutable contents on every sampling. This history
had 7,839 such messages among 29,321 selected records. The candidate reduced
one observed reference-collection interval from 43.66ms to 32.08ms, while
Worked was slower in the separate sequential turn. It was reverted: a 12ms
stage reduction does not justify the extra selected-path cache and mutation
surface while the full target remains far away. The focused Product/session
tests passed, and the original history remained read-only.

An incremental receipt lookup replaced the usage recorder's full active-path
scan. Four focused attempt-usage tests and the combined Model Input/session
model-call suite passed (97 passed, one skipped). One diagnostic native PTY
turn with the change measured 1,135.40ms from tool exit to Worked. The usage
recorder took 97.83ms, of which its durable append took 97.74ms. This isolated
turn is not a matched before/after p95 and does not establish an end-to-end
gain. Native reopening verified its two snapshots with terminal usage and one
tool result without changing the authority or executing historical tools.

## Prepared-request prefix candidate

The Session now offers the last successfully committed prepared request to the
next AI request through its existing committer. AI reuses sealed message items
and their canonical encoding only after a type-sensitive, ordered comparison
of the entire old prefix and all other payload fields and visible headers.
Different nested values, signed floating zero, field order or a shortened
message sequence take the ordinary full-construction path. The new suffix is
validated and frozen before transport; metrics, binary-field locations, hash
and canonical bytes are recomputed for the resulting exact request. The
candidate is retained only after the durable Model Input commit succeeds.

On two isolated snapshots with 1,535 then 1,537 prepared messages, nine
alternating read-only samples measured full construction at 154.35ms median
and prefix construction at 64.07ms median. Canonical payload, hash, metrics,
binary-field locations and copied transport payload matched exactly. A separate
root-hash-only micro sample saved about 23ms across logical and prepared lists;
it was not implemented as a separate cache.

One native-PTY diagnostic pair on same-source long-history copies measured
3,102.55ms baseline and 2,671.32ms candidate from actual tool exit to Worked.
The copied fixtures lacked their writer-head and Model Input index sidecars,
causing cold materialization of about 1.06s and 0.95s in the post-tool commits.
Maximum input echo was worse in the candidate (1,737.58ms versus 1,086.81ms).
Both copies reopened with two exact snapshots and terminal usage, one correct
tool-output fingerprint, unchanged read-only authority and no historical tool
execution. This single noisy pair does not establish a p95 improvement or the
250ms target. The complete AI gate passed 875 offline tests with 90.64%
coverage; the focused Session/Model Input selection passed 104 tests.

Review of the adjacent v2 sequence cache found that its type-sensitive prefix
comparator still treated `-0.0` and `0.0` as equal although their canonical
JSON differs. A regression failed first; the comparator now distinguishes the
two signs so a changed prefix is replanned. The prefix and append tests pass.
This is a correctness guard for later writer reuse, not a latency claim.

Extend the exact prefix proof into the transcript writer and remove other
repeated full-context work while preserving the durable-before-send order.

## Background planning and verified value references

The writer's v2 plan previously compared and reused every historical JSON
message in the TUI event loop, yielding periodically. A regression first
showed that the event loop could not process input while the first items were
being collected. Planning now runs in a background thread over request-local
copies of the cached sequence plans; the writer checks the transcript
revision and leaf again before any write. Cancellation, branch replacement and
concurrent append regressions pass in both warm and cold cache states. The
focused Model Input and Session model-call selection passed 104 tests.

The first four native-PTY matched pairs used the same 29,465-record seed and
ran sequentially, alternating old and new order. A fifth baseline completed,
but the candidate was stopped when the goal was paused; this is not a five-pair
p95 result. The old/new tool-exit-to-Worked times in the four complete pairs
were 2,016/2,096ms, 2,162/2,051ms, 1,850/1,980ms and 2,044/2,058ms.
Threaded planning shortened its own phase from roughly 347–490ms to
152–167ms, but did not establish an end-to-end improvement. Maximum keyboard
echo in those pairs remained about 697–926ms. All nine completed authorities
were reopened read-only and verified: 18 snapshots with terminal usage, nine
tool-output fingerprints and truncation results, unchanged authority and no
historical tool execution. The background-planning change is an intermediate
input-loop responsiveness fix, not acceptance of the Worked target.

A second regression first found 55 value-index lookups after appending one
message to a 50-message request. The writer now retains verified value
references with an ancestry-bound sequence plan. It canonicalizes each
candidate prefix item before reusing a reference, so nested changes,
boolean/integer changes and signed floating zero cannot inherit an old node.
The changed suffix still uses the normal materialization and integrity path.
This reduced the regression's old-value lookups below ten; 138 Model Input,
v2 and Session tests plus 32 file-index/image/thaw tests passed. One bounded
native-PTY candidate reopened with two exact snapshots, terminal usage and
one output; its value-materialization phase was 67ms versus 102ms in the
separate baseline turn. The pair had unrelated phase variance and does not
prove a Worked improvement.

The built-in binary projection copied both full JSON trees even for text-only
requests. The committer now uses the logical canonical encoding it already
needs for the hash to check for declared images, logical image objects and
reserved literal marker keys. Only a plain request with the exact built-in
codec skips projection; custom codecs, images and markers retain the existing
path. A first-failing regression and 99 Model Input/image tests passed. A
bounded native-PTY turn confirmed the binary-externalization phase was absent
and reopened with two snapshots and exact tool output. Its Worked latency was
2,663ms because a 538ms generation-two collection moved into prepared-request
validation. This is a stage reduction, not an end-to-end tail result.

The current long-session critical path remains about two seconds: tool result
append, next call preparation, prepared request construction, multiple v2
graph writes and snapshot append, then usage/outcome/assistant writes and
terminal projection. Meeting 500ms requires shortening that serial chain and
controlling full-history allocations and GC pauses; the current changes alone
do not meet the goal.

## One ordered v2 graph and snapshot append

The writer now builds its missing value, sequence and root bundles in an
isolated index, with final record IDs and ancestry known before persistence.
Batch-capable Stores receive those bundles and the prepared snapshot in one
ordered append; other Stores retain the existing ordered fallback. The shared
index and verified prefix plans advance only after the
durable batch receipt. A staging failure leaves neither graph facts nor
speculative references behind; an acknowledged write with an uncertain
receipt retries the exact operation IDs. Cancellation after the Store accepted
the batch leaves a complete, independently rebuildable snapshot.

The focused Model Input, v2 file index and Session selection passed 141 tests
with one existing skip before adding the unknown-receipt regression. The
long-session native PTY diagnostic used a 29,465-record source, separate
copy-on-write authorities and 20 bounded keyboard samples per run. It measured
4,977ms before and 3,384ms after from tool exit to Worked; the post-tool v2
commit fell from 1,841ms to 1,326ms, with the values and sequence phases
falling from 84/190ms to 20/17ms. The two runs had material phase and GC
variance: the prior run's maximum echo was 2,729ms versus 785ms in the
candidate, while prepared planning remained 635/610ms. This one diagnostic
pair is not a p95 estimate, nor evidence that the 500ms goal is met. The
remaining full-history canonical prefix proof and request/terminal chain
still dominate the path.

## Sealed prepared prefix reuse

The AI `PreparedModelRequest` already seals its payload and, when an append is
verified, carries the exact same frozen message objects into the next request.
The transcript writer now retains those frozen source identities alongside
its ancestry-bound value plans after a durable commit. For an owned request
whose stored payload needs no binary replacement, identity proves the reused
prefix without a second per-item JSON encoding. Any fresh object, unsealed
request or changed item still takes the canonical comparison path. A
first-failing 50-message regression observed 52 redundant canonical prefix
checks; it passes below ten after this change and also proves a later changed
prefix rebuilds to the new content. The 149-test focused Model Input, Session
and thaw selection passed with one existing skip.

An isolated 1,545-message in-memory append measured the second writer plan
at 10.63ms before and 1.54ms after, with 1,547 versus two canonical prefix
checks; the complete second commit measured 18.16ms versus 8.61ms. This
short-message micro sample establishes the eliminated duplicate work, not
the long-session Worked latency. Logical Model Input is frozen separately on
each turn and still needs its own provenance-backed incremental proof.

One sequential long-session native PTY diagnostic against the previous batch
commit used the same 29,465-record source and bounded 20-key input. Tool exit
to Worked was 3,384ms before and 2,850ms after; the post-tool v2 commit was
1,326ms versus 975ms, and its plan phase was 610ms versus 300ms. Maximum
keyboard echo was 785ms versus 691ms. The candidate authority reopened
read-only with two exact snapshots and terminal usage, one exact tool-output
fingerprint, no history tool execution and unchanged file bytes. This one
pair demonstrates the intended plan reduction but cannot establish p95 or
accept the 500ms goal. Session preparation, logical input projection, adapter
construction, residual v2 work and terminal writes still remain serial.

## Logical prefix sealing and deferred plain-text blob setup

Session now retains its previous frozen logical Model Input. At the next
projection it checks each raw prefix item against the frozen value, including
nested shape, strict JSON types and signed zero. Only the exact prefix shares
immutable objects. The writer then recognizes those verified identities and
avoids a second JSON encoding. Branches still rebuild or extend their own
ancestry-bound node index before any reference is reused. An isolated
1,545-message complex-JSON append measured second writer planning at 21.73ms
before and 2.33ms after, with 1,547 versus two redundant canonical prefix
checks; context construction remained about 24ms in both samples. The focused
selection passed 151 tests with one existing skip before the blob setup change.

One native PTY long-session diagnostic against the previous sealed-prepared
commit measured post-tool writer planning at 300ms before and 89ms after, and
v2 commit at 975ms versus 826ms. Tool exit to Worked stayed about 2,850ms in
both runs; maximum keyboard echo was 691ms versus 737ms. Both sessions were
independently reopened with exact snapshots, usage and tool output, without
changing the authority. This is a writer improvement, not a verified Worked
improvement.

For plain persistent requests, Product now gives the committer a deferred
blob-codec factory. The committer determines from the already needed logical
canonical data and sealed prepared binary fields whether an image or reserved
marker needs projection, opening the blob authority only then. A real image
still opens the codec and round-trips exactly. This removes an unnecessary
active-path blob-reference scan from the text-only preparation chain; its
full-path latency impact remains to be measured.

The first same-source 20-key long-session check removed both per-call blob
codec constructions: the post-tool `create_model_input_committer` phase fell
from 221ms to 136ms. Tool exit to Worked nevertheless rose from 2,849ms to
3,361ms; the post-tool v2 root phase varied from 86ms to 286ms and snapshot
append from 159ms to 219ms. Maximum echo was 737ms versus 908ms. The
candidate independently reopened with exact two snapshots, usage and output,
and unchanged authority. This diagnostic establishes the skipped scan, not
an end-to-end improvement; GC and Store variability remain material.

The v2 mapping-root hash now stores a digest state at the end of the committed
messages sequence. When the next plan proves an unchanged prefix and all
preceding fields match, the writer hashes only the suffix and the remaining
fields. Otherwise it hashes the full mapping. A 1,545-message direct sample
measured 1.34ms versus 0.02ms; the focused v2 hash regressions proved exact
hashes for append, changed item and changed preceding field. In one sequential
29,465-record PTY diagnostic, the post-tool root phase was 14ms, compared
with 86ms in the earlier no-cache run and 286ms in the immediately prior
noisy run. Tool exit to Worked measured 2,457ms; maximum echo was 672ms.
The copy reopened read-only with two exact snapshots and terminal usage, one
exact tool-output fingerprint, unchanged authority and no historical tool
execution. This single result does not establish p95 or the 500ms goal.

## Terminal observation batching and lineage checks

AI's terminal provider callback now sends the observed terminal attempt usage
and outcome through one Session operation. The transcript commits them in
that order as one Store batch when the backend supports batches. Legacy
recorders keep their existing two-call contract. The batch retains the same
durable receipt, cancellation settlement and uncertain-receipt retry rules.
Focused regressions cover one ordered batch, exact-once retry, cancellation,
legacy recorders and Session integration. The transcript also keeps a global
set of committed outcome invocation ids, built once on open and advanced only
after a successful local commit. The owning Model Input committer proves the
current snapshot chain using its receipts and the expected revision and leaf;
the terminal batch therefore avoids rescanning the entire active path. A
regression first failed on that scan and now passes. A separate branch/reopen
test proves a prior outcome still blocks a duplicate invocation.

Two sequential 29,465-record PTY diagnostics on the same source gave
tool-exit-to-Worked times of 2,532ms with batching alone and 2,426ms after
removing the redundant terminal lineage scan, versus 2,457ms in the preceding
root-cache run. Maximum keyboard echo was 775ms and 746ms, versus 672ms.
The latter run measured a 124ms terminal batch, 246ms tool-result append and
175ms final assistant-message handling; its post-tool Model Input commit was
761ms. Both candidates independently reopened with exact snapshots, terminal
usage and tool output, without changing the source authority or executing
historical tools. These noisy single samples demonstrate bounded terminal
work but neither a reliable latency reduction nor acceptance of the 500ms
goal. The post-tool preparation and Model Input commit remain the larger
serial costs.

Acceptance still requires five matched before/after PTY rounds across the
required tool cases and history scales. A faster Worked display before the
final model call and terminal outcome would change the state contract and
cannot satisfy this objective.

## Post-tool input and long-history frame work

The post-tool keyboard probe places twenty keys at 40ms intervals starting
when the controlled tool service returns, so it measures input while the
continuation persists and publishes Worked. On one 29,465-record continuation
after terminal batching and lineage changes, tool exit to Worked was 3,682ms,
maximum echo 1,179ms and maximum event-loop delay 723ms. After moving exact
sealed prepared-request validation, logical thaw and canonical encoding to a
worker, a comparable single turn measured 3,259ms, 856ms and 633ms. Both
copies reopened with exact snapshots, terminal usage and tool output. These
samples show responsive input is still at risk and do not estimate p95.

A profiled post-tool turn found that 28 screen refreshes repeatedly traversed
thousands of stable historical render segments. Profiling inflated total work,
so its timings are diagnostic only. The render loop now reuses the unchanged
cacheable segment prefix, cumulative line offsets and a per-frame Kitty image
index. The first changed or uncacheable segment and all later segments remain
subject to normal validation and finalization. A 6,000-segment, changing-editor
micro sample fell from 11.26ms median per frame before these changes to
2.37ms after both. A failed-finalization test, uncacheable-boundary test and
145 TUI/transcript tests passed. The first full PTY sample after both changes
showed 2,909ms to Worked and 580ms maximum echo; its authority reopened
exactly. This one sample does not establish a Worked improvement or the goal.

The transcript unit of work also now prepares detached conversation graph
appends in a worker while retaining its commit lock and existing durable
publication barrier. A deliberately held graph-append test first demonstrated
an event-loop stall, then passed after the change; the selected 75 transcript,
model-input and Session tests passed. In one later long-session PTY sample,
tool exit to Worked was 2,965ms, maximum echo 180ms and maximum loop delay
898ms. The original authority remained unchanged; native reopening verified
the two snapshots with terminal usage and the exact tool output without
running historical tools. The lower echo maximum is promising but is a noisy
single observation, not a responsiveness p95. Worked remains around 3s.

The measured post-tool sequence still waits for the tool-result append
(about 580ms in that turn), Session/model-input preparation and commit
(roughly 1.8s together), terminal observations (96ms), final assistant append
(135ms), and the final flush. Moving graph copies off-loop does not remove
these ordered durability and model-call boundaries. The 500ms end-to-end
acceptance remains open.

## Incremental Store head reuse

An instrumented follow-up separated one tool-result append: the native
FileStore operation took 254ms, including 53ms to decode and validate the
advisory Store head, 41ms to append the authoritative JSONL fact and 76ms to
rewrite the head. The asynchronous append awaited 434ms in all, and the
message route took 526ms. The 2,567ms Worked result is one noisy diagnostic
turn; its copy reopened with exact snapshots, usage and output.

The same FileStore writer now retains its validated head after an accepted
append and checks the journal and sidecar file identities under the existing
exclusive lock before reuse. A changed sidecar falls back to authoritative
replay; another writer's journal update forces a fresh head read. The cache is
bounded to sixteen keys. Three regressions cover a cache hit, sidecar mutation
and a second writer; the selected Store, settlement, Model Input index and
writer lifecycle suites passed with 70 tests and 17 platform skips before the
third regression was added. Ruff and focused mypy passed.

On the same long-session seed, the next single PTY turn skipped head decoding
at the tool-result append. Its native Store operation took 207ms and the
message route 439ms; Worked appeared after 2,478ms versus 2,567ms in the
preceding instrumented run. The head rewrite still took 112ms in this run.
Native reopening again verified both snapshots, terminal usage and output,
with unchanged source authority and no historical tool execution. This
demonstrates the intended skipped read, but the difference is not a matched
p95 estimate and the 500ms target remains unmet.

## Canonical logical-message prefix

The built-in Model Input commit now caches per-message canonical JSON only
after the full logical input has passed its existing validation. A later
context reuses those strings only for the exact frozen message objects that
the context-freeze pass already proved against the previous raw values.
Changed messages, additional components, tools and request options are
encoded from the current context. Custom codec commits keep their previous
full-hash path. A regression first failed for the absent reuse path, then
proved exact canonical bytes for an appended message and a nested mutation;
the focused Model Input, canonical, v2 and Session suites passed with 152 tests
and one existing skip. Ruff and focused mypy passed.

A direct comparison on a rebuilt 1,549-message logical input measured full
canonical encoding at 104.52ms median versus 22.42ms with the proven prefix,
with byte-identical output in seven repetitions. A single full PTY turn on
the same long-session seed still took 3,193ms from tool exit to Worked,
versus 2,478ms in the preceding head-cache turn; the prepared-request phase
also varied from about 250ms to 578ms. The new authority independently
reopened with exact snapshots, usage and tool output and no historical tool
execution. This direct encoding improvement has not produced a measured
end-to-end improvement or met the 500ms goal.

## Follow-up prepared-request allocation, 2026-10-22

The offline PTY probe was split around its own provider payload construction
and transport assertion. On a continuation of the same roughly 29,500-record
history, tool exit to Worked took 3,018ms in one run. The post-tool prepared
request took 291ms: serializing 1,553 messages took 70ms and sealing the
prepared payload took 221ms. The Model Input commit took 610ms, including
91ms prepared-request validation, 54ms logical-input thaw, 100ms incremental
materialization and 124ms snapshot append. The standard transport payload
copy took 90ms; the probe's extra snapshot lookup took only 3ms. The maximum
observed input echo was 185ms, while the maximum loop delay reached 1,264ms.
These are one-run measurements, not p95 values or additive critical-path
totals; phase wall times include scheduling and machine contention.

A separate nine-repetition comparison on 1,549 rebuilt logical messages
found a 61ms median for both recursive exact comparison and a single native
JSON encoding comparison. Replacing the existing mutation proof with JSON
encoding would therefore have no demonstrated material speed benefit and
would need additional strict-type proof. No Product change was made for it.

The run's native reopen verified its two snapshots and terminal usage, the
exact output and unchanged source authority, with zero historical tool
executions. The adapter's full serialization and prepared-request sealing,
ordered Model Input commit, tool-result append and final assistant append
remain on the post-tool critical path. The 500ms acceptance remains open.

## Advisory Store head background publication, 2026-10-22

The persistent transcript Store now returns from an authoritative journal
append without waiting for that append's advisory Store head sidecar rewrite.
A background worker checks the journal identity under its exclusive lock
before publishing the head and refreshes the same writer's bounded head cache.
Another writer's newer journal prevents a stale head publication. Disposal
joins submitted sidecar writes before releasing the rooted IO owner; a missing
or stale sidecar still forces journal replay on a later writer. The Model Input
snapshot and terminal batches retain their existing durable wait points.

A regression first failed because the background mode was absent. The added
tests then showed that a deliberately held sidecar write does not delay the
journal append receipt, a later append reuses the refreshed cache, a stale
background update does not replace another writer's head, and lifecycle
disposal waits for the background worker. The selected Store, transcript
lifecycle and Model Input tests passed: 149 passed, 18 platform skips. Ruff,
focused mypy and `git diff --check` passed.

Two subsequent long-session offline PTY diagnostics on the same growing copy
reported 2,748ms and 2,929ms to Worked. The latter overlapped a short test
run and cannot serve as an uncontended comparison. Its native tool-result
Store append took 126ms without a synchronous sidecar rewrite; the earlier
instrumented turn took 277ms with a synchronous write. The first background
turn still reread a sidecar after an unrelated background update; refreshing
the writer cache fixed that extra read in the second turn. Both runs reopened
with exact Model Input snapshots, terminal usage and tool output, unchanged
source authority and zero historical tool executions. The end-to-end 500ms
target remains unproven and unmet.

## Receipt-gated incremental conversation graph, 2026-10-22

Strict materialized transcript appends now validate only new record identities,
parent links and cycles before the Store operation. The existing UOW commit
lock keeps the selected branch fixed. After the Store receipt has the expected
revision and record identities, the repository publishes the prevalidated
records into its existing indexes. Unmaterialized and compatible-mode paths
retain detached candidates. A retained detached graph still has independent
child lists; changed lists are replaced during publication.

The new regression first failed because a materialized single append cloned
the historical repository. It now passes for both single and batched commits.
Further tests cover a pending Store receipt, failed append, branch selection,
detached candidates, and an out-of-order strict batch. The selected Branch,
Repository, Store, Session, Product Session, Model Input, lifecycle, writer,
maintenance and interaction tests passed: 178 passed, one existing skip across
the two runs. Ruff and focused mypy passed.

On a separate in-memory repository built from the 29,500-record continuation,
nine paired appends measured detached graph cloning at 10.68ms median and
the receipt-gated incremental preparation/publication at 0.85ms median.
The following offline PTY turn had a 36ms tool-result event route and 2,785ms
tool exit to Worked. Native journal append in this one run took only about
2ms, compared with tens of milliseconds in earlier runs, so the entire
tool-route difference cannot be attributed to the graph change. Maximum
input echo was 940ms and maximum loop delay 605ms; overall responsiveness
remains unacceptable. Native reopening verified both Model Input snapshots,
terminal usage and exact tool output, with unchanged source authority and no
historical tool executions. The 500ms goal remains open.

A separate prepared-request shortcut used strict JSON validation followed by
in-memory per-message serialization fingerprints. In an alternating same-
process comparison on 1,561 messages, its median was 118ms versus 123ms for
the existing exact comparison. That small gain did not justify extra memory
and complexity; the candidate and its regression were removed without a
Product change.

## Long transcript render and model preparation, 2026-10-22

An offline completion profile of a roughly 29,600-record session showed that
26 TUI frames spent 3.16s in `SegmentedRenderLines` cumulative-line rebuilding
under profiler overhead. The transcript and screen layout both recounted the
same long historical prefix. The TUI now caches the committed segment index,
uses binary search for visible slices, and concatenates already indexed parts
without recounting them. A regression first observed 415 historical line-count
reads on a repeated 200-record tail frame and 402 in the screen layout; both
paths now make fewer than 30. The render tests passed: 156 passed. In a
successive pair of offline PTY turns with 20 post-tool input samples, whole-turn
frame-render sums were 3,327ms and 1,242ms, maximum input echo was 899ms and
738ms, and tool exit to Worked was 2,468ms and 2,071ms. These are single
growing-session samples, not a p95 or a clean isolated effect estimate.

The broad TUI/HarnessTUI run passed 2,364 tests with seven skips and two
macOS PTY terminal-attribute restoration failures. Both failures reproduced
unchanged on the preceding code branch; they are not evidence of this TUI
change. Native reopening of the faster PTY turn verified exact Model Input
snapshots, terminal usage and output, unchanged authority, and no historical
tool execution.

Without keyboard input, the updated TUI still took 1,782ms from tool exit to
Worked. The post-tool path included about 449ms in Resource evidence and
Session preparation and 499ms in Model Input commit, plus prepared-request
construction, transport-payload copy, terminal settlement, final append and
event-loop scheduling. Its source authority and two snapshots reopened
exactly. Render work alone cannot meet the 500ms target.

A private, unmodified-Product experiment moved the synchronous Session model
preparer to a worker thread. Its one-run maximum post-tool input echo fell
from 738ms to 234ms while Worked remained about 2.09s. The Product runtime now
does this work off the event loop while serializing workers. Cancellation
returns immediately; a cancelled worker retains the preparation lock until it
finishes, so the next request cannot race the previous Session context cache.
A regression first failed on the synchronous implementation and then passed
for cancellation and serialization. The selected Model Call and Resource
evidence tests passed: 41 passed. A subsequent Product PTY turn reported
177ms maximum input echo and 2,189ms to Worked; native reopening verified the
two snapshots, terminal usage, output and unchanged authority with zero
historical tool executions. This improves input response, not the 500ms
Worked goal, which remains open.

## Sealed Model Input source reuse, 2026-10-22

The normal Model Input commit previously thawed every already frozen logical
message and copied every already sealed prepared payload message before its
v2 writer reused nearly all of those values. A regression first observed the
full logical thaw and prepared payload copy. The writer now receives a shallow
native top-level sequence over its sealed values when the preceding Model
Input context or prepared request proves an exact shared prefix. Its cached
sequence plan checks immutable source identities and canonicalizes any changed
suffix; a cache miss still canonicalizes every value. Cold requests retain the
original native JSON copy path because the frozen-tree encoder made the first
uncached index build slower in one diagnostic. Binary projection still receives
a detached native tree and does not duplicate that copy on a cold request.

The long-session normal post-tool commit's logical projection fell from about
76ms to below 1ms; its prepared-request validation/copy fell from about 55–67ms
to below 1ms. Across three successive single-run no-keyboard diagnostics,
tool exit to Worked measured 1,622ms after logical reuse, 1,707ms after both
reuse paths, and 2,031ms after cold/warm selection. These are not a paired
p95 comparison and do not establish an end-to-end gain. In the final run the
hot Model Input commit took 380ms, including 34ms resolver build, 94ms
incremental materialization and 59ms authoritative snapshot append; the cold
commit took about 4.05s. Native reopening verified each run's two Model Input
snapshots, terminal usage and exact output, unchanged source authority and no
historical tool execution. Model Input, PreparedRequest and Model Call tests
passed: 163 passed, one existing skip. Ruff, focused mypy and diff checks
passed. The 500ms tool-exit-to-Worked target remains open.

## Speculative Resource evidence prefetch experiment, 2026-10-22

An uncommitted candidate scheduled Resource evidence recovery after the first
durable Model Input snapshot, while the tool was still running. A regression
verified that the next request waited for the speculative task, rechecked the
current path, and cancelled the task on disposal; 82 selected tests passed.
The offline long-session turn recovered evidence for 103ms before tool exit,
but still spent 138ms in evidence recovery after the tool result changed the
selected path. Tool exit to Worked was 2,710ms, with a 1,260ms maximum event
loop delay. Native reopening verified both snapshots, terminal usage and exact
tool output, unchanged source authority, and no historical tool execution.
This single sample does not isolate the prefetch cost from run variation, but
it does show that speculative recovery cannot replace the required check of
the new tool result. The candidate was removed; the measurement remains as a
constraint for the next optimization.

## Incremental evidence recovery scan, 2026-10-22

The append-only recovery path used to enumerate every historical record while
searching for new Model Input snapshots, and the async entry point rebuilt the
full record-ID tuple a second time. A regression first observed 101 enumerated
records and two reads of each historical ID after a single append. The scan
now starts at the proven append suffix and the async entry point passes its
already captured ID tuple to recovery. Branch changes still take the full
path; 19 Resource evidence tests passed. On a subsequent 29,753-record offline
turn, the post-tool evidence stage took 152ms and tool exit to Worked took
2,485ms. This is another single growing-session sample, so it does not prove
an end-to-end gain. Native reopening verified both snapshots, terminal usage,
exact tool output, unchanged authority and zero historical tool executions.
The 500ms target remains open.

## Commit phase and GC attribution, 2026-10-22

Model Input commit timing now covers the logical canonical encoding, the two
cooperative yield points, and publication of a committed graph. In one later
29,769-record offline continuation, the hot post-tool commit took 397ms:
logical canonical encoding 64ms, resolver build 37ms, materialization 102ms,
snapshot append 57ms, and publication 15ms. The complete tool-exit-to-Worked
transition was 1,991ms. The first cold request in the same turn was much
slower; its roughly 4.4s commit included 518ms logical encoding, 913ms node
index build and 2.6s materialization. A separate generation-2 garbage
collection ran on the main thread for 2,604ms during that cold request and
corresponded to a 3,532ms maximum event-loop delay. This is evidence of a
distinct responsiveness problem in cold long-session preparation, not proof
that the hot Worked path improved. Exact native reopening again verified both
snapshots, terminal usage and tool output, unchanged authority and zero
historical tool executions.

A separate post-tool `cProfile` run on the same growing offline session
attributed 0.87s of instrumented CPU to `PreparedModelRequest` prefix reuse,
including 0.66s in strict recursive raw-to-frozen JSON comparison; 0.59s to
creating a detached provider transport payload; and 1.70s across 15 rendered
frames, including 0.74s across 30 common-segment-prefix comparisons. The
profiler substantially inflated the path (6.9s of sampled execution), so
these figures identify code paths but are not user-facing latency estimates.
The request-prefix comparison must still distinguish types and signed zero,
and the transport copy must protect the sealed durable payload from SDK
mutation. Native reopening of this profiled run verified both Model Input
snapshots and terminal usage, exact tool output, unchanged source authority
and zero historical tool executions.

## Provider request preparation off the input loop, 2026-10-22

The post-tool profile found that the second long-context preparation, provider
request serialization and recursive sealing, still ran on the event loop
after Session model-call preparation had moved to a worker. Built-in OpenAI
Responses, OpenAI Chat Completions and Anthropic Messages adapters now opt in
to worker preparation for durable requests when there is no custom trace
callback. The opt-in belongs to the concrete class; subclass and custom
adapter behavior remains on the caller thread unless explicitly declared.
The existing durable commit and cancellation gates still run on the event
loop. New regressions first observed input-loop blocking, then verified loop
progress, cancellation without commit or transport, trace callback thread
affinity, and commit-before-transport order. Selected PreparedRequest,
ProviderRuntime and ProviderCancellation tests passed: 90 passed; Ruff and
focused mypy passed.

In successive 20-input offline long-session turns, the opted-in fake adapter
showed post-tool input echo p95/max of 192/195ms and tool exit to Worked of
1,949ms. The same adapter with opt-in disabled showed 640/643ms and 2,958ms.
The source session grew between runs and its load times differed substantially,
so these are directional responsiveness evidence, not isolated latency or p95
claims for the Worked transition. Native reopening verified four exact Model
Input snapshots with terminal usage, both tool outputs, unchanged source
authority and zero historical tool executions. The 500ms Worked target remains
open.

An isolated comparison on the native-reopened 1,631-message prepared payload
found 127ms median for the existing exact raw-to-frozen prefix check, 87ms for
strict validation followed by native JSON equality, and 180ms for strict
validation plus canonical JSON comparison (seven repeats each). Native
equality alone also conflates booleans with integers and opposite signed
zeros, so the 40ms diagnostic advantage does not justify replacing the exact
check without an additional correctness proof. The candidate was not applied.

## Sealed logical encoding overlapped with provider preparation, 2026-10-22

After Session model-call preparation freezes the logical request, its canonical
encoding and hash can be computed without reading provider output or mutating
the transcript. The durable prepared-request path now starts that computation
alongside an opted-in provider's worker preparation and joins both before the
Model Input commit barrier. The committer reuses the canonical bytes and hash
in the binary-codec path; direct commits join an unfinished worker, including
one left running after caller cancellation, before touching the same context.
A cancellation regression first observed concurrent encoding during direct
commit and then passed with this join. No transport can start before durable
snapshot publication.

Three successive growing-session, no-keyboard offline turns measured tool
exit to Worked at 2,536ms with prewarm disabled, 1,701ms with it enabled, and
4,546ms with it disabled again. Hot Model Input commits were 869ms, 245ms and
969ms respectively; the logical encoding phase fell from 210/155ms to below
1ms when prewarmed. Provider and Session preparation also varied between
runs, so the end-to-end difference is directional, not an isolated effect
estimate or p95. Native reopening verified all six Model Input snapshots and
terminal usage records, three exact tool outputs, unchanged source authority
and zero historical tools. The selected AI, Model Call and Model Input tests
passed: 169 passed, one existing skip; Ruff and focused mypy passed. The
500ms Worked objective remains open.

## Evidence-free append recovery and resolver reuse, 2026-10-22

The selected Session now proves an append-only suffix by walking parent links
from its leaf to the last hydrated record. Resource evidence skips historical
path recovery only when its caches contain no evidence and every new Model
Input snapshot was certified evidence-free after the durable commit. Unknown
snapshots, evidence metadata, resumed Sessions and branch changes retain full
recovery. A red regression covered the evidence-free hot path; additional
tests covered branch fallback, certification after durable commit, and no
certification for an evidence-bearing request.

The v2 Model Input index cache now retains the resolver's record-position map
after successful publication. Subsequent writers extend that map only when
the previous record objects remain the exact selected prefix; a changed
object rebuilds the resolver, and branch or compatibility changes invalidate
the cache. A red regression observed two full resolver builds for two
successive commits and now observes one. The relevant Model Input, Model Call,
Request Evidence, Product contract and transcript tests passed: 184 passed,
one existing skip; Ruff and focused mypy passed.

In two successive growing-session, no-keyboard offline turns, the first
candidate measured tool exit to Worked at 2,683ms, Resource evidence
projection below 1ms, hot Model Input commit 748ms and resolver build 237ms.
With resolver reuse, the next turn measured Worked at 2,237ms, hot commit
478ms and resolver extension 196ms. The full asynchronous evidence preparation
was 63ms and 48ms, respectively. These are directional measurements across
different system loads and Session sizes; they do not isolate a p95 or prove
the 500ms objective. Native reopening of each result verified both Model
Input snapshots and terminal usage, exact tool output, unchanged source
authority and zero historical tool executions. The 500ms Worked target and
long-session event-loop pauses remain open.

A subsequent 20-keyboard-input run on the same growing offline Session
measured maximum echo delay of 262ms, tool exit to Worked of 3,422ms and
maximum event-loop delay of 943ms. Its hot Model Input commit was 1,183ms,
including 176ms resolver extension and 742ms materialization. Keyboard
injection and changing load make this a responsiveness check, not a controlled
latency comparison. Native reopening again verified both snapshots and
terminal usage, exact tool output, unchanged authority and zero historical
tools. The visible input stall and 500ms Worked goal are still unresolved.

## TUI trailing-tool candidate rejected, 2026-10-22

The long-session TUI lane tried a certified dirty-suffix marker and a trailing
tool-record render path. It preserved exact rendered lines and control rows in
106 relevant tests; Ruff and focused mypy passed. A synthetic 2,000-record
tool update fell from a 2.32ms median to 0.93ms, and a 10,000-record update
fell from 12.01ms to 5.57ms. However, successive real offline long-session
turns with 20 keyboard inputs measured 4,225ms and 2,136ms from tool exit to
Worked under changing load. The first had 476ms maximum input echo delay;
the second had 238ms. Their frame timing did not isolate a useful end-to-end
gain from the candidate. In the second run, the screen layout consumed 273ms
across 32 post-tool frames, of which transcript segments consumed 47ms and
tool indexing 5ms. The largest single layout segment was 45ms. The TUI
candidate was removed from the worktree because it added change-tracking
authority and a special render path for only a few milliseconds of local
gain. Model preparation and durable request materialization remain the next
targets.

## Sealed logical-message reuse, 2026-10-22

Session preparation now retains the previous Model Input's owned, immutable
message values alongside the exact Agent message objects that produced them.
Before reusing a prefix, it checks the complete wire-relevant shape of every
message once, including bounded nested tool arguments, signatures, details,
cost and error information. A changed message reserializes that message and
the suffix. Unsupported values and nested JSON exceeding 64 nodes take the
existing serialization path. The Model Input freezer accepts identity with
its own prior sealed value as proof of equality, avoiding a second walk of
that prefix. A post-seal check prevents a newly serialized message changed
during preparation from receiving a stale reuse certificate.

An initial version checked the same long prefix three times. Its hot Session
preparation took 644ms and the whole tool-exit-to-Worked path took 2,015ms;
the redundant checks erased the freeze saving. After reducing the hot path
to one check, 1,675 messages were reused and hot Session preparation took
236ms; tool exit to Worked took 1,765ms. A separate 20-keyboard-input run
reused 1,679 messages, with 298ms Session preparation, 2,046ms to Worked,
198ms maximum input echo delay and 677ms maximum event-loop delay. The hot
Provider preparation in that run still took 489ms and the durable Model
Input commit 261ms. These growing-session samples do not establish a p95;
the 500ms Worked target and event-loop stalls remain open.

Model Call, Model Input, Request Evidence and Agent Product contract tests
passed with 189 tests and one existing skip. Ruff passed. Native reopening
of both long-session results verified two snapshots and terminal usage
records each, the exact tool output, unchanged authority and zero historical
tool executions.

The next diagnostic run timestamped event-loop heartbeats and captured GC
stacks. Its 933ms maximum loop delay coincided with a 932ms generation-2
collection in a worker that was freezing the first long Model Input, 10.7s
after prompt start and before the tool began at 16.5s. This establishes that
the headline maximum loop delay in that run was not a tool-exit stall. After
tool start, the largest measured loop delay was 254ms. The same run had
413ms maximum input echo delay and 2,879ms tool exit to Worked under extra
profiling and concurrent local load, so its end-to-end times are diagnostic
rather than a controlled comparison. Post-tool delayed heartbeats coincided
with tool-result append/render, the exact-message certificate walk, and
Provider preparation. The next optimization must reduce those synchronous
walks and preserve the durable barrier; changing the Worked label alone would
hide the remaining work. Native reopening of this diagnostic run again
verified both Model Input snapshots and terminal usage, the exact tool output,
unchanged authority and zero historical tool executions.

## Session-owned AI normalization offload, 2026-10-22

The previous hot long-session call spent 307ms normalizing model messages on
the event loop, including 26ms transforming tool pairings. Session-owned
typed Context calls now copy only their outer message/tool arrays and run the
same normalization in a worker when there is no trace callback. Direct SDK,
custom Context and traced calls retain caller-thread behavior. Diagnostics,
capability checks and provider admission still run after the worker returns.
Cancellation while normalization is pending prevents provider invocation;
the worker has no commit or transport authority.

Successive 20-key offline turns measured maximum input echo delay of 475ms
before this change and 218ms with it. Tool exit to Worked measured 2,335ms
and 2,110ms, respectively. Normalization moved from the main thread to a
worker; its measured duration changed from 307ms to 156ms under different
load. These are directional observations, not a p95 or an isolated speedup.
Native reopening of the changed run verified two Model Input snapshots and
terminal usage records, the exact tool output, unchanged authority and zero
historical tool executions. The 500ms Worked target remains open.

## Provider-prefix counterfactual, 2026-10-22

A private offline probe reused the previous prepared request's immutable
provider-message prefix by identity and serialized only the new suffix. This
was a diagnostic monkeypatch outside the Product tree, not a Product change:
it assumed an append-only normalized context rather than proving an adapter
frontier. Native reopening nevertheless verified both resulting Model Input
snapshots and terminal usage records, the exact Tool output, unchanged
authority, and zero historical Tool executions.

The hot fake-adapter serialization fell from 214ms to below 1ms. Its complete
prepared-request step fell from 479ms to 188ms because canonical construction,
hashing, and sealing still cost time. Tool exit to Worked moved from 2,110ms
to 1,918ms across successive growing-session, 20-key runs; maximum input
echo was 218ms and 270ms. Changing load prevents an isolated effect or p95
claim. Even the optimistic Provider-only path remains about 1.4 seconds above
the requested 500ms target. A cross-scope incremental source and projection
contract is needed; see the proposed
[Issue 803 incremental model-call pipeline](issue-803-incremental-model-call-pipeline.md).

## Owned Provider prefix check, 2026-10-22

`PreparedModelRequest` now accepts exact nodes from its previously owned,
recursively frozen payload by identity when proving a reused message prefix.
The former comparison rejected these immutable mapping nodes and rebuilt the
entire payload. A regression failed before the change, then passed with exact
canonical bytes, digest, metrics, binary fields and transport copy. The AI gate
passed 884 offline tests. Ordinary mutable adapter values retain the existing
recursive comparison and full-path fallback.

A private offline adapter supplied the prior sealed Provider prefix to exercise
the new Product check on a resumed Session with about 30,000 records and 1,700
model messages. Its post-tool serialization was 0.70ms, the prepared-request
phase 173ms, and the tool-exit-to-Worked interval 1,781ms. Maximum keyboard
echo was 194ms and maximum event-loop delay 731ms. Native reopening verified
both snapshots and terminal usage, the exact Tool output, unchanged authority
and zero historical Tool executions. This is one diagnostic turn using an
adapter-supplied prefix, not a default built-in adapter result or a p95 claim.
The 500ms target remains unmet.

The same trace spent 330ms in Session preparation, including 283ms rechecking
historical message shapes; AI normalization took 171ms in a worker, Model Input
commit 278ms, and the final transport copy 90ms. A candidate direct comparison
against stored shapes passed the focused Session tests but was slightly slower
on a 1,700-message synthetic sample (54.9ms versus 52.7ms median), so it was
removed without a Product commit. The next accepted change needs to shorten
the serial cross-layer chain while keeping the final source and publication
barriers exact.

## Transport copy overlapped with the commit barrier, 2026-10-22

Large text-only requests prepared by an explicitly worker-safe adapter now
copy their sealed Provider payload in a worker while the durable Model Input
commit runs. The adapter receives this one-shot private copy only after the
commit and cancellation checks succeed; later calls still obtain independent
copies. Small requests, image payloads, traced calls and non-opted-in adapters
keep their prior path. A regression first demonstrated that copying began only
after the held commit; the new path passed overlap, copy-isolation and failed-
commit tests. `make check-ai` passed 887 offline tests with 90.64% coverage.

Two sequential long-session diagnostic pairs used the same growing, roughly
30,000-record authority and a private offline adapter that supplied a sealed
Provider prefix. The first baseline/candidate pair measured 1,891/808ms from
Tool exit to Worked; the reverse-order candidate/baseline pair measured
464/579ms. The first pair had a large cold-start and load difference, so these
four turns cannot establish a p95 or an isolated end-to-end speedup. The
post-commit transport copy measured 123 and 54ms in the baselines versus below
0.01ms in both candidates. Model Input commits stayed ordered and completed
before transport. Both candidate authorities reopened with two exact Model
Input snapshots and terminal usage, one exact Tool output, unchanged authority
and zero historical Tool executions.

One optimistic candidate turn fell below 500ms, but the longer candidate took
808ms and this adapter's prefix is diagnostic only. The representative
built-in-adapter p95 target remains open; the Session, normalization and
Provider projection chain still needs a certified shared prefix.

## Incremental pipeline acceptance matrix, 2026-10-22

The candidate on `perf/tool-exit-worked-803` now certifies the Session's
normalized prefix after a durable Tool result, appends the built-in Chat
adapter's stable provider prefix, and reuses exact owned message nodes in
`PreparedModelRequest`. The Provider and logical Model Input envelopes retain
incremental SHA-256 prefix states. Their final hashes, capacity metrics,
binary-marker decisions and durable graph roots remain exact. Changed fields,
mutated messages, uncertain frontiers and invalid cached states take the full
path. Model Input is committed before transport; terminal facts and Agent end
remain before Worked. The relevant final commits are `8c19128f` and
`4bfe0893`, following the earlier Session, AI and v2 writer changes on this
branch.

Thirty sequential, unprofiled continuations ran against one growing,
file-backed resumed Session. It grew from about 31,400 to 31,900 transcript
records and from 203 to 208 MiB. Each of five controlled subprocess cases
(silent, streamed, three consecutive Tools, large ASCII and Unicode output)
ran six times. The native screen runner rendered and flushed terminal frames
while 20 queued keyboard inputs exercised the tool-exit interval. The model
used the built-in OpenAI Chat Completions adapter with an offline synthetic
transport; network access was blocked. This matrix used in-memory terminal
streams rather than a POSIX PTY, so its values are not a matched comparison
with the earlier PTY measurements in this file. The interval starts when the
last Tool service returns and ends at the first terminal flush after the
Worked divider is committed. Separate screen tests verify that the divider
appears in the visible frame.

| Measure, 30 turns | Result |
| --- | ---: |
| Tool exit to Worked p50 | 434.04ms |
| Tool exit to Worked p95, nearest rank | 468.42ms |
| Tool exit to Worked maximum | 470.69ms |
| Keyboard echo p95 / maximum | 95.25ms / 99.17ms |
| Event-loop delay p95 / maximum after Tool exit | 74.6ms / 80.7ms |

All 30 turns preserved the input draft and committed Model Input before
transport. Native reopening verified all 60 exact Model Input snapshots and
terminal usage records, 42 Tool outputs, unchanged authority bytes and mtime,
and zero historical Tool executions. The focused Model Input and Session tests
passed 138 tests with one existing skip; AI passed 894 offline tests; 30 screen
and event-pacing tests passed. The 500ms p95 target is met for this specified
long-session, offline native-screen matrix.

The maximum event-loop delay across the *whole* turn was 473.2ms. Every one
of the 60 observed generation-two GC collections occurred before Tool start;
their maximum duration was 439.5ms. During Tool execution, event-loop delay
reached 185.8ms, with p95 110.1ms. These pre-tool and tool-phase pauses are a
remaining responsiveness issue and are excluded from the tool-exit-to-Worked
acceptance claim. The matrix does not establish a sub-500ms p95 for every
provider, terminal implementation or history size.
