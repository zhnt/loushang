"""State/outcome and metadata-event mutations of model-checked projections."""

import copy
import json


def append_state_vectors(cases, idle, content):
    def add(name, kind, value, valid=True):
        cases.append((name, kind, json.dumps(value, ensure_ascii=False), valid))

    def state(status):
        terminal = status in {"succeeded", "failed", "interrupted"}
        return dict(
            executionId="execution",
            status=status,
            revision=3,
            interruptRequested=status == "interrupted",
            outcome=dict(
                status=status,
                errorCode="product_failure" if status == "failed" else None,
                legacyResult={},
            )
            if terminal
            else None,
        )

    def snapshot(status):
        value = copy.deepcopy(idle)
        source = value["result"]["source"]
        view = value["result"]["executions"]
        active = status in {"accepted", "running"}
        observation = dict(
            executionId="execution", status=status, finalCursor=None if active else 3
        )
        source["source"].update(cursor=3, revision=3, running=status == "running")
        source["observation"] = (
            copy.deepcopy(source["observation"])
            if status == "accepted"
            else observation
        )
        source["draft"] = "流式🙂" if status == "running" else ""
        view["revision"] = 3
        view["active" if active else "latestTerminal"] = state(status)
        if not active:
            view["quiescent"] = copy.deepcopy(observation)
        return value

    for status in ["accepted", "running", "succeeded", "failed", "interrupted"]:
        add(f"state-{status}", "snapshot", snapshot(status))
        update = dict(revision=5, execution=state(status))
        batch = copy.deepcopy(content)
        batch["result"]["events"].append(update)
        add(f"mixed-{status}", "events", batch)
    for size in [16_384, 16_385]:
        value = snapshot("running")
        value["result"]["source"]["draft"] = "x" * size
        add(f"draft-limit-{size}", "snapshot", value, size <= 16_384)
    for watermark in [0, 3, 4, 2**53 - 1, 2**53, True, -1, None]:
        value = snapshot("succeeded")
        value["result"]["source"]["observation"]["finalCursor"] = watermark
        add(
            f"completion-watermark-{watermark}",
            "snapshot",
            value,
            type(watermark) is int and 0 <= watermark <= 3,
        )
    for watermark in [2**53 - 1, 2**53]:
        value = snapshot("succeeded")
        value["result"]["source"]["source"]["cursor"] = 2**100 + 1
        value["result"]["source"]["observation"]["finalCursor"] = watermark
        add(f"large-source-watermark-{watermark}", "snapshot", value, watermark < 2**53)
    for name in [
        "terminal-no-outcome",
        "outcome-mismatch",
        "failed-no-error",
        "success-error",
        "running-outcome",
        "missing-outcome",
        "active-terminal",
        "latest-running",
        "unknown-status",
        "interrupt-number",
        "quiescent-running",
        "draft-terminal",
        "accepted-observation",
        "running-watermark",
        "idle-status",
    ]:
        value = snapshot("succeeded")
        view = value["result"]["executions"]
        terminal = view["latestTerminal"]
        if name == "terminal-no-outcome":
            terminal["outcome"] = None
        elif name == "outcome-mismatch":
            terminal["outcome"]["status"] = "interrupted"
        elif name == "failed-no-error":
            terminal["status"] = terminal["outcome"]["status"] = "failed"
        elif name == "success-error":
            terminal["outcome"]["errorCode"] = "unexpected"
        elif name == "running-outcome":
            terminal["status"] = "running"
        elif name == "missing-outcome":
            del terminal["outcome"]
        elif name == "active-terminal":
            view["active"] = copy.deepcopy(terminal)
        elif name == "latest-running":
            view["latestTerminal"] = state("running")
        elif name == "unknown-status":
            terminal["status"] = "unknown"
        elif name == "interrupt-number":
            terminal["interruptRequested"] = 1
        elif name == "quiescent-running":
            view["quiescent"].update(status="running", finalCursor=None)
        elif name == "draft-terminal":
            value["result"]["source"]["draft"] = "stale"
        elif name == "accepted-observation":
            value["result"]["source"]["observation"].update(
                status="accepted", finalCursor=None
            )
        elif name == "running-watermark":
            value["result"]["source"]["observation"]["status"] = "running"
        else:
            value["result"]["source"]["observation"]["executionId"] = None
        add(name, "snapshot", value, False)
    from loushang.appserver.protocol import AppErrorCodeV1

    for code in [v.value for v in AppErrorCodeV1] + ["unknown"]:
        value = snapshot("failed")
        value["result"]["executions"]["latestTerminal"]["outcome"]["legacyResult"] = {
            "code": code
        }
        add(f"legacy-{code}", "snapshot", value, code != "unknown")
    for revision in [0, 1, 2**53 - 1, 2**53, -1, True, 1.0]:
        value = copy.deepcopy(content)
        value["result"]["events"] = [
            dict(revision=revision, execution=state("running"))
        ]
        add(
            f"update-revision-{revision}",
            "events",
            value,
            type(revision) is int and 1 <= revision <= 2**53 - 1,
        )
    for revision in [0, 2**53 - 1, 2**53, True]:
        value = snapshot("running")
        value["result"]["executions"]["active"]["revision"] = revision
        add(
            f"state-revision-{revision}",
            "snapshot",
            value,
            type(revision) is int and 0 <= revision <= 2**53 - 1,
        )
    # The two revisions are independently scoped. The codec does not order
    # these values against each other; do not invent such a consumer rule.
    value = copy.deepcopy(content)
    value["result"]["events"] = [dict(revision=1, execution=state("running"))]
    add("independent-update-revisions", "events", value)
    raw = json.dumps(value)
    cases.append(
        (
            "duplicate-update-revision",
            "events",
            raw.replace('"revision": 1', '"revision": 1, "revision": 2', 1),
            False,
        )
    )
    for field in ["errorCode", "legacyResult"]:
        value = snapshot("failed")
        del value["result"]["executions"]["latestTerminal"]["outcome"][field]
        add(f"outcome-missing-{field}", "snapshot", value, False)
