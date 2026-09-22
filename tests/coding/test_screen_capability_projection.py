from loushang.coding.ui.screen_input import project_coding_capabilities
from loushang.harness.session import (
    SessionInputCapabilities,
    SessionInputCapability,
    SessionOperationAvailability,
    SessionOperationCapability,
    SessionOperationResolver,
)


def test_coding_projection_reads_declarations_without_resolving_or_inventing_approval():
    def forbidden():
        raise AssertionError("projection must not instantiate or resolve Session operations")

    resolver = SessionOperationResolver(
        forbidden,
        availability=SessionOperationAvailability.from_capabilities([SessionOperationCapability.INPUT]),
        declared_input_capabilities=SessionInputCapabilities.from_capabilities([SessionInputCapability.STEER]),
    )
    value = project_coding_capabilities(("local", "1"), resolver, clipboard_declared=False)
    entries = {entry.operation: entry for entry in value.entries}
    assert entries["submit"].availability == entries["steer"].availability == "available"
    assert entries["follow_up"].reason == entries["interrupt"].reason == "not_supported"
    assert entries["approve"].reason == entries["deny"].reason == "not_projected"
    assert entries["image_paste"].reason == "not_projected"
    standard = project_coding_capabilities(("local", "2"), SessionOperationResolver(forbidden), clipboard_declared=True)
    assert standard.get("interrupt", binding_key=standard.binding_key).availability == "available"
    assert standard.get("image_paste", binding_key=standard.binding_key).availability == "available"
