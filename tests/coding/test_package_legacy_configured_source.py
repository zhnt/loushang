from __future__ import annotations

from copy import deepcopy

import pytest

from loushang.coding.package_legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source,
)


def _projection(path: str) -> dict[str, object]:
    return {
        "productId": "coding",
        "projectionVersion": 1,
        "scopes": {
            "global": {
                "present": False,
                "rawSha256": None,
                "settingsPath": "/private/global.json",
                "sourcePatch": {},
            },
            "project": {
                "present": True,
                "rawSha256": "a" * 64,
                "settingsPath": "/private/project.json",
                "sourcePatch": {"plugin_sources": [path]},
            },
        },
    }


def test_single_configured_source_must_be_exact_installed_local_directory() -> None:
    source = "/private/source"
    matched = match_coding_legacy_local_skill_configured_source(
        _projection(source), source_identity=f"local:{source}"
    )
    assert matched is not None
    assert (matched.scope, matched.path) == ("project", source)

    for invalid in (
        "/private/another",
        "/private/source/../source",
        "source",
        "~/source",
    ):
        with pytest.raises(ValueError, match="same installed local Source"):
            match_coding_legacy_local_skill_configured_source(
                _projection(invalid), source_identity=f"local:{source}"
            )


def test_configured_source_refuses_another_writer_or_source_kind() -> None:
    projection = _projection("/private/source")
    scopes = projection["scopes"]
    assert isinstance(scopes, dict)
    project = scopes["project"]
    assert isinstance(project, dict)
    patch = project["sourcePatch"]
    assert isinstance(patch, dict)
    for extra, message in (
        (
            {"plugin_sources": ["/private/source", "/private/another"]},
            "same installed local Source",
        ),
        (
            {"plugin_sources": ["/private/source"], "package_roots": ["/tmp/packages"]},
            "separate migration",
        ),
        (
            {
                "plugin_sources": ["/private/source"],
                "resource_roots": ["/tmp/resources"],
            },
            "separate migration",
        ),
    ):
        candidate = deepcopy(projection)
        candidate["scopes"]["project"]["sourcePatch"] = extra
        with pytest.raises(ValueError, match=message):
            match_coding_legacy_local_skill_configured_source(
                candidate, source_identity="local:/private/source"
            )
    assert patch == {"plugin_sources": ["/private/source"]}


def test_scoped_sources_may_cover_a_subset_of_the_installed_set() -> None:
    projection = _projection("/private/project-source")
    projection["scopes"]["global"]["present"] = True
    projection["scopes"]["global"]["rawSha256"] = "b" * 64
    projection["scopes"]["global"]["sourcePatch"] = {
        "plugin_sources": ["/private/global-source"]
    }
    identities = (
        "local:/private/global-source",
        "local:/private/project-source",
    )
    assert (
        match_coding_legacy_local_skill_configured_source(
            projection,
            source_identity=identities[0],
            installed_source_identities=identities,
        ).scope
        == "global"
    )
    assert (
        match_coding_legacy_local_skill_configured_source(
            projection,
            source_identity=identities[1],
            installed_source_identities=identities,
        ).scope
        == "project"
    )
    mixed = deepcopy(projection)
    mixed["scopes"]["global"]["sourcePatch"]["plugin_sources"] = []
    assert (
        match_coding_legacy_local_skill_configured_source(
            mixed,
            source_identity=identities[0],
            installed_source_identities=identities,
        )
        is None
    )
    same_scope = deepcopy(projection)
    same_scope["scopes"]["global"]["sourcePatch"] = {}
    same_scope["scopes"]["project"]["sourcePatch"]["plugin_sources"] = [
        "/private/global-source",
        "/private/project-source",
    ]
    assert (
        match_coding_legacy_local_skill_configured_source(
            same_scope,
            source_identity=identities[0],
            installed_source_identities=identities,
        ).scope
        == "project"
    )
    for changed in (
        ("global", ["/private/uninstalled"]),
        ("project", ["/private/global-source"]),
    ):
        candidate = deepcopy(projection)
        candidate["scopes"][changed[0]]["sourcePatch"]["plugin_sources"] = changed[1]
        with pytest.raises(ValueError):
            match_coding_legacy_local_skill_configured_source(
                candidate,
                source_identity=identities[0],
                installed_source_identities=identities,
            )
