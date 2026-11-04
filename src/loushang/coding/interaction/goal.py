"""Thin embedded TUI commands over the original Goal and finite Work driver."""

from __future__ import annotations

import hashlib
import json
import shlex
from uuid import uuid4

from loushang.harness.host.types import HostActionResult
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.tasks import GoalTask
from loushang.harnesswork.integrations.goal_run import run_goal

HELP = (
    "Goal: /goal <development target> creates a task in this Session (no model call).\n"
    "/goal new [--check 'command'] [--method NAME] [--calls N] -- <target>\n"
    "/goal run | step | status | pause | cancel | resume | review | accept TOKEN | reject TOKEN REASON | abandon | close\n"
    "Default: human acceptance, 8 total model calls, 4096 output tokens/call, 24 Work, 600s/run.\n"
    "Workspace file tools: read/edit/write; configured checks use original Bash approvals.\n"
    "Run/step/resume authorize model/tool execution under the existing Session permissions."
)
CONTROLS = {"status", "pause", "cancel", "review", "abandon", "close"}


def is_goal_command(text):
    return text == "/goal" or text.startswith("/goal ")


def is_goal_control(text):
    if not is_goal_command(text):
        return False
    words = text.split()
    return len(words) == 1 or words[1] in CONTROLS


class _SessionCommands:
    def __init__(self, session):
        self.session, self.owner, self.goal_id = session, None, None
        self.review_identity = self.review_token = None
        self.running = self.opening = False

    def status(self):
        if self.owner is None:
            from loushang.coding.adapters.interactive_goal import read_task_history

            try:
                history = read_task_history(self.session)
            except GoalError as error:
                if str(error) == "unknown Goal: Session has no Goal journal":
                    return HELP
                raise
            return "\n".join(
                f"Goal {g.id}: {g.status}; history read-only; validity=not_checked"
                for g in history.goals.values()
            )
        if self.goal_id is None:
            return HELP
        state = self.owner.controller.query(self.goal_id)
        if self.owner._closed:
            return f"Goal {state.id}: {state.status}; history read-only; validity=not_checked"
        facts = self.owner.controller.facts()
        allowance = self.owner._allowances[self.goal_id]
        return (
            f"Goal {state.id}: {state.status} ({state.reason or 'ready'})\n"
            f"Target: {state.requirements[0].text}\n"
            f"Model calls: {allowance.total_calls}/{allowance.total_limit}; "
            f"Work: {sum(b.goal_id == state.id for b in facts.batches)}/{state.limit}; "
            f"execution_unresolved={facts.unresolved}; validity=not_checked\n"
            "Use /goal review to inspect current evidence and request acceptance."
        )

    async def execute(self, args):
        if not args or args in {"help", "status", "new"}:
            return self.status()
        if args == "close":
            if self.owner is not None:
                await self.owner.close()
            return "Goal resources closed; parent Session remains available."
        if args in {"pause", "cancel", "abandon"}:
            owner, gid = self.require_owner()
            state = owner.controller.query(gid)
            control_error = None
            try:
                if state.status in {"active", "paused"}:
                    owner.controller.control(
                        gid,
                        "abandon" if args == "abandon" else "pause",
                        command_id=f"control-{uuid4().hex}",
                        revision=state.revision,
                        epoch=state.epoch,
                        reason="user_" + args,
                    )
            except Exception as error:
                if args == "pause":
                    raise
                control_error = str(error)
            if args != "pause":
                outcomes = await owner.controller.request_cancel(gid)
                return (
                    self.status()
                    + "\nCancellation observations: "
                    + str(outcomes)
                    + (
                        "\nGoal control record unavailable: " + control_error
                        if control_error
                        else ""
                    )
                )
            return self.status()
        if args == "review":
            owner, gid = self.require_owner()
            identity = await owner.review_basis(gid)
            self.review_identity = identity
            self.review_token = hashlib.sha256(identity.encode()).hexdigest()[:16]
            state = owner.controller.query(gid)
            snapshot = json.loads(identity)["inventory"]
            baseline = state.metadata["initial_inventory"]
            changed = [
                name
                for name in sorted(set(snapshot) | set(baseline))
                if snapshot.get(name) != baseline.get(name)
            ]
            return (
                self.status()
                + "\nCurrent candidate digest: "
                + hashlib.sha256(identity.encode()).hexdigest()
                + "\nChanged files since Goal creation:\n"
                + "\n".join(changed[:100])
                + "\nChecks: "
                + str(list(state.metadata["task_contract"]["checks"]))
                + f"\nAfter reviewing the actual files, accept with /goal accept {self.review_token}. "
                "Required configured checks must pass; this token never waives them. "
                "Or /goal reject TOKEN <specific feedback> to continue planning."
            )
        if args.startswith("accept "):
            owner, gid = self.require_owner()
            if (
                args.split() != ["accept", self.review_token]
                or self.review_identity is None
            ):
                raise GoalError(
                    "use /goal review first; acceptance requires its current token"
                )
            await owner.accept(gid, self.review_identity)
            self.review_identity = self.review_token = None
            return self.status()
        if args.startswith("reject "):
            owner, gid = self.require_owner()
            parts = args.split(maxsplit=2)
            if (
                len(parts) != 3
                or parts[1] != self.review_token
                or self.review_identity is None
            ):
                raise GoalError("use /goal review, then /goal reject TOKEN REASON")
            await owner.review(
                gid, self.review_identity, approved=False, reason=parts[2]
            )
            self.review_identity = self.review_token = None
            return (
                self.status()
                + "\nReview rejected; /goal run plans from the recorded feedback."
            )
        if args in {"run", "step", "resume"}:
            if self.running:
                raise GoalError("Goal run already in progress")
            owner, gid = self.require_owner()
            self.running = True
            try:
                if args == "resume":
                    state = owner.controller.query(gid)
                    owner.controller.control(
                        gid,
                        "resume",
                        command_id=f"resume-{uuid4().hex}",
                        revision=state.revision,
                        epoch=state.epoch,
                        reason="user_resume",
                    )
                await run_goal(owner, gid, steps=1 if args == "step" else 24)
                return self.status()
            finally:
                self.running = False
        if args.split()[0] in {"accept", "reject", "run", "step", "resume", *CONTROLS}:
            raise GoalError(HELP)
        if self.opening or self.running:
            raise GoalError("Goal command already in progress")
        self.opening = True
        try:
            task = parse_task(args)
            if self.owner is None:
                from loushang.coding.adapters.goal import GoalConstructionError
                from loushang.coding.adapters.interactive_goal import InteractiveGoal

                try:
                    self.owner = await InteractiveGoal.attach(session=self.session)
                except GoalConstructionError as error:
                    self.owner = error.owner
                    raise
            self.goal_id = await self.owner.create_task(task)
            return (
                self.status()
                + "\nCreated without running. /goal run starts execution; /goal abandon declines."
            )
        finally:
            self.opening = False

    def require_owner(self):
        if self.owner is None or self.goal_id is None:
            raise GoalError("No live Goal in this Session. " + HELP)
        return self.owner, self.goal_id


def parse_task(args):
    if not args.startswith("new "):
        return GoalTask(args)
    tokens = shlex.split(args)[1:]
    checks, method, calls = [], None, 8
    while tokens and tokens[0] != "--":
        if len(tokens) < 2:
            raise GoalError(HELP)
        option, value = tokens[:2]
        tokens = tokens[2:]
        if option == "--check":
            checks.append(value)
        elif option == "--method":
            method = value
        elif option == "--calls":
            calls = int(value)
        else:
            raise GoalError(HELP)
    if not tokens or tokens[0] != "--":
        raise GoalError(HELP)
    return GoalTask(" ".join(tokens[1:]), tuple(checks), method, calls)


async def execute_goal_command(session, text):
    provider = getattr(session, "list_commands", None)
    if callable(provider) and any(
        getattr(c, "name", None) == "goal" for c in provider()
    ):
        return HostActionResult(
            error_message="/goal conflicts with a selected Session command."
        )
    service = getattr(session, "_embedded_goal_commands", None)
    if service is None:
        service = _SessionCommands(session)
        session._embedded_goal_commands = service
    return HostActionResult(
        status_message=await service.execute(text[len("/goal") :].strip())
    )


class GoalControlSurface:
    """Use the existing surface starter task; no new background task owner."""

    def __init__(self, command, text, request_render):
        from loushang.tui.ui_parts.text_pager import TextPager

        self.command, self.text, self.request_render = command, text, request_render
        self.pager = TextPager(
            "Goal", "Reading Goal or waiting for original execution to settle…"
        )
        self.closed = False

    async def start(self):
        from loushang.tui.ui_parts.text_pager import TextPager

        result = await self.command(self.text)
        if not self.closed:
            self.pager = TextPager(
                "Goal",
                result.error_message
                or result.status_message
                or "Goal command completed.",
            )
            self.request_render()

    def render(self, constraints):
        return self.pager.render(constraints)

    def handle_input(self, event):
        return self.pager.handle_input(event)

    def close(self):
        self.closed = True
