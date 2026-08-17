from __future__ import annotations

import json
import subprocess
import sys


def _probe(script: str) -> dict[str, object]:
    output = subprocess.check_output(
        [sys.executable, "-c", script],
        text=True,
    )
    return json.loads(output)


def test_session_public_facade_is_lazy_until_a_symbol_is_requested() -> None:
    result = _probe(
        """
import json
import sys
import loushang.harness.session as session

before = "loushang.harness.session.agent_product" in sys.modules
value = session.AgentProductSession
after = "loushang.harness.session.agent_product" in sys.modules
print(json.dumps({
    "before": before,
    "after": after,
    "module": value.__module__,
    "exported": "AgentProductSession" in session.__all__,
}))
"""
    )

    assert result == {
        "before": False,
        "after": True,
        "module": "loushang.harness.session.agent_product",
        "exported": True,
    }


def test_transcript_public_facade_is_lazy_until_a_symbol_is_requested() -> None:
    result = _probe(
        """
import json
import sys
import loushang.harness.transcript as transcript

before = "loushang.harness.transcript.maintenance" in sys.modules
value = transcript.AgentTranscriptCompactionRuntime
after = "loushang.harness.transcript.maintenance" in sys.modules
print(json.dumps({
    "before": before,
    "after": after,
    "module": value.__module__,
    "exported": "AgentTranscriptCompactionRuntime" in transcript.__all__,
}))
"""
    )

    assert result == {
        "before": False,
        "after": True,
        "module": "loushang.harness.transcript.maintenance",
        "exported": True,
    }


def test_resource_packages_facade_does_not_eagerly_create_plugin_cycle() -> None:
    result = _probe(
        """
import json
import sys
import loushang.harness.resources.packages as packages

before = "loushang.harness.resources.packages.catalog" in sys.modules
value = packages.PackageSourceConfig
after_source = "loushang.harness.resources.packages.source" in sys.modules
after_catalog = "loushang.harness.resources.packages.catalog" in sys.modules
print(json.dumps({
    "before": before,
    "after_source": after_source,
    "after_catalog": after_catalog,
    "module": value.__module__,
}))
"""
    )

    assert result == {
        "before": False,
        "after_source": True,
        "after_catalog": False,
        "module": "loushang.harness.resources.packages.source",
    }
