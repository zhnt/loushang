from __future__ import annotations

import asyncio


def test_harnesswork_executes_an_opaque_ontology_action() -> None:
    from loushang.harnesswork import (
        InMemoryEventLogBackend,
        WorkEventFact,
        WorkOperation,
        WorkRuntime,
    )

    class OntologyActionExecutor:
        async def execute(self, operation, context):
            assert operation.domain == "ontology"
            assert operation.payload == {
                "action_type": "Project.UpdateProgress",
                "object_id": "project-42",
            }
            context.publish(
                WorkEventFact(
                    kind="OntologyActionCommitted",
                    payload={"object_id": operation.payload["object_id"]},
                )
            )

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        runtime = WorkRuntime(
            event_log=event_log,
            executor=OntologyActionExecutor(),
        )
        accepted = await runtime.accept(
            WorkOperation(
                operation_id="ontology-action-1",
                kind="ExecuteOntologyAction",
                session_id="project-workspace-42",
                domain="ontology",
                payload={
                    "action_type": "Project.UpdateProgress",
                    "object_id": "project-42",
                },
            )
        )

        completed = await runtime.wait(accepted.run_id)

        assert completed.status == "completed"
        assert [
            entry.payload["kind"] for entry in event_log.query(run_id=accepted.run_id)
        ] == [
            "ExecuteOntologyAction",
            "WorkRunStarted",
            "OntologyActionCommitted",
            "WorkRunCompleted",
        ]

    asyncio.run(scenario())
