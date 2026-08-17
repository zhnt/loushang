from __future__ import annotations

import threading
import time
from pathlib import Path

from loushang.tui import (
    CompletionCancellationToken,
    CompletionContext,
    CompletionItem,
    CompletionProvider,
    CompletionSuggestions,
)


def test_combined_completion_provider_uses_first_provider_with_suggestions(tmp_path: Path) -> None:
    from loushang.tui import CombinedCompletionProvider, PathCompletionProvider

    (tmp_path / "src").mkdir()
    provider = CombinedCompletionProvider(
        (
            CompletionProvider((CompletionItem(value="/help", label="/help", description="Show help"),)),
            PathCompletionProvider(base_path=tmp_path),
        )
    )

    command_suggestions = provider.get_suggestions(("/h",), 0, 2)
    assert command_suggestions is not None
    assert command_suggestions.prefix == "/h"
    assert command_suggestions.group == ""
    assert command_suggestions.items == (CompletionItem(value="/help", label="/help", description="Show help"),)

    path_suggestions = provider.get_suggestions(("open ./s",), 0, len("open ./s"))
    assert path_suggestions is not None
    assert path_suggestions.prefix == "./s"
    assert path_suggestions.group == "Files"
    assert path_suggestions.items == (CompletionItem(value="./src/", label="src/", description="./src/"),)


def test_combined_completion_provider_does_not_fall_back_from_unmatched_slash_command() -> None:
    from loushang.tui import (
        CombinedCompletionProvider,
        SlashCommand,
        SlashCommandCompletionProvider,
    )

    class RecordingPathProvider:
        called = False

        def get_suggestions(self, *_args: object, **_kwargs: object) -> CompletionSuggestions:
            self.called = True
            return CompletionSuggestions(
                prefix="/exit",
                items=(CompletionItem(value="/Applications/example", label="example"),),
                group="Files",
            )

    path_provider = RecordingPathProvider()
    provider = CombinedCompletionProvider(
        (
            SlashCommandCompletionProvider((SlashCommand(name="quit", description="Quit"),)),
            path_provider,
        )
    )

    suggestions = provider.get_suggestions(("/exit",), 0, len("/exit"))

    assert suggestions is not None
    assert suggestions.prefix == "/exit"
    assert suggestions.items == ()
    assert suggestions.group == "Commands"
    assert not path_provider.called


def test_path_completion_provider_does_not_scan_initial_absolute_slash_token(monkeypatch, tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    calls: list[str] = []

    def items_for_prefix(
        self: object,
        prefix: str,
        *,
        cancellation_token: CompletionCancellationToken | None = None,
    ) -> tuple[CompletionItem, ...]:
        del self, cancellation_token
        calls.append(prefix)
        return (CompletionItem(value="/Applications/example", label="example"),)

    monkeypatch.setattr(PathCompletionProvider, "_items_for_prefix", items_for_prefix)
    provider = PathCompletionProvider(base_path=tmp_path)

    assert provider.get_suggestions(("/exit",), 0, len("/exit")) is None
    assert calls == []


def test_combined_completion_provider_passes_context_to_providers_in_order() -> None:
    from loushang.tui import CombinedCompletionProvider

    class ContextProvider:
        def __init__(self, items: tuple[CompletionItem, ...]) -> None:
            self.items = items
            self.contexts: list[CompletionContext] = []

        def get_suggestions(self, context: CompletionContext) -> CompletionSuggestions:
            self.contexts.append(context)
            return CompletionSuggestions(prefix=context.lines[context.cursor_line][: context.cursor_col], items=self.items)

    empty = ContextProvider(())
    match = ContextProvider((CompletionItem(value="src/", label="src/"),))
    token = CompletionCancellationToken()
    provider = CombinedCompletionProvider((empty, match))

    suggestions = provider.get_suggestions(("s",), 0, 1, force=True, explicit=True, cancellation_token=token)

    assert suggestions is not None
    assert suggestions.items == (CompletionItem(value="src/", label="src/"),)
    assert empty.contexts[0] is match.contexts[0]
    assert match.contexts[0].force is True
    assert match.contexts[0].explicit is True
    assert match.contexts[0].cancellation_token is token


def test_combined_completion_provider_stops_when_context_is_cancelled() -> None:
    from loushang.tui import CombinedCompletionProvider

    class CancellingProvider:
        def get_suggestions(self, context: CompletionContext) -> None:
            context.cancellation_token.cancel("test")
            return None

    class RecordingProvider:
        called = False

        def get_suggestions(self, context: CompletionContext) -> CompletionSuggestions:
            self.called = True
            return CompletionSuggestions(prefix="", items=(CompletionItem(value="unused"),))

    token = CompletionCancellationToken()
    recorder = RecordingProvider()
    provider = CombinedCompletionProvider((CancellingProvider(), recorder))

    assert provider.get_suggestions(("s",), 0, 1, cancellation_token=token) is None
    assert not recorder.called
    assert token.reason == "test"


def test_completion_helper_passes_context_to_complete_provider() -> None:
    from loushang.tui import get_completion_suggestions

    class ContextCompleteProvider:
        context: CompletionContext | None = None

        def complete(self, prefix: str, *, context: CompletionContext) -> tuple[CompletionItem, ...]:
            self.context = context
            return (CompletionItem(value=f"{prefix}/"),)

    provider = ContextCompleteProvider()
    context = CompletionContext(lines=("src",), cursor_line=0, cursor_col=3, explicit=True)

    suggestions = get_completion_suggestions(provider, context)

    assert suggestions is not None
    assert suggestions.items == (CompletionItem(value="src/"),)
    assert provider.context is context


def test_path_completion_provider_suggests_relative_paths_on_forced_tab(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src").mkdir()
    (tmp_path / "script.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path)

    suggestions = provider.get_suggestions(("s",), 0, 1, force=True)

    assert suggestions is not None
    assert suggestions.prefix == "s"
    assert suggestions.group == "Files"
    assert suggestions.items == (
        CompletionItem(value="src/", label="src/", description="src/"),
        CompletionItem(value="script.py", label="script.py", description="script.py"),
    )


def test_path_completion_provider_applies_at_file_completion_with_space_suffix(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "README.md").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path)

    suggestions = provider.get_suggestions(("read @REA",), 0, len("read @REA"))
    assert suggestions is not None
    assert suggestions.prefix == "@REA"
    assert suggestions.group == "Files"
    assert suggestions.items == (CompletionItem(value="@README.md", label="README.md", description="README.md"),)

    application = provider.apply_completion(
        ("read @REA",),
        0,
        len("read @REA"),
        suggestions.items[0],
        suggestions.prefix,
    )

    assert application.lines == ("read @README.md ",)
    assert (application.cursor_line, application.cursor_col) == (0, len("read @README.md "))


def test_path_completion_provider_does_not_duplicate_existing_suffix_space(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "README.md").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path)

    suggestions = provider.get_suggestions(("read @REA next",), 0, len("read @REA"))
    assert suggestions is not None

    application = provider.apply_completion(
        ("read @REA next",),
        0,
        len("read @REA"),
        suggestions.items[0],
        suggestions.prefix,
    )

    assert application.lines == ("read @README.md next",)
    assert application.cursor_col == len("read @README.md")


def test_path_completion_provider_quotes_paths_with_spaces(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "notes folder").mkdir()
    (tmp_path / "notes folder" / "daily note.md").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path)

    suggestions = provider.get_suggestions(('attach @"notes folder/d',), 0, len('attach @"notes folder/d'))

    assert suggestions is not None
    assert suggestions.prefix == '@"notes folder/d'
    assert suggestions.group == "Files"
    assert suggestions.items == (
        CompletionItem(
            value='@"notes folder/daily note.md"',
            label="daily note.md",
            description="notes folder/daily note.md",
        ),
    )


def test_path_completion_provider_does_not_duplicate_space_after_existing_closing_quote(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "notes folder").mkdir()
    (tmp_path / "notes folder" / "daily note.md").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path)
    line = 'attach @"notes folder/d" after'
    cursor_col = len('attach @"notes folder/d')

    suggestions = provider.get_suggestions((line,), 0, cursor_col)
    assert suggestions is not None

    application = provider.apply_completion((line,), 0, cursor_col, suggestions.items[0], suggestions.prefix)

    assert application.lines == ('attach @"notes folder/daily note.md" after',)
    assert application.cursor_col == len('attach @"notes folder/daily note.md"')


def test_path_completion_provider_preserves_single_quoted_at_prefix(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "notes folder").mkdir()
    (tmp_path / "notes folder" / "daily note.md").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path)

    suggestions = provider.get_suggestions(("attach @'notes folder/d",), 0, len("attach @'notes folder/d"))

    assert suggestions is not None
    assert suggestions.prefix == "@'notes folder/d"
    assert suggestions.items == (
        CompletionItem(
            value="@'notes folder/daily note.md'",
            label="daily note.md",
            description="notes folder/daily note.md",
        ),
    )


def test_path_completion_provider_can_recursively_find_nested_file_matches(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src" / "tests").mkdir(parents=True)
    (tmp_path / "src" / "tests" / "test_completion.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "tools").mkdir()
    (tmp_path / "src" / "tools" / "compile.py").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True)

    suggestions = provider.get_suggestions(("@src/tes",), 0, len("@src/tes"))

    assert suggestions is not None
    assert suggestions.prefix == "@src/tes"
    assert suggestions.group == "Files"
    assert suggestions.items[0] == CompletionItem(
        value="@src/tests/test_completion.py",
        label="test_completion.py",
        description="src/tests/test_completion.py",
    )


def test_path_completion_provider_keeps_recursive_scan_bounded(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src").mkdir()
    for index in range(5):
        (tmp_path / "src" / f"target_{index}.py").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True, max_results=2)

    suggestions = provider.get_suggestions(("@target",), 0, len("@target"))

    assert suggestions is not None
    assert suggestions.group == "Files"
    assert len(suggestions.items) == 2


def test_path_completion_provider_ranks_recursive_at_matches_by_relevance_and_shorter_paths(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "helper.py").write_text("", encoding="utf-8")
    (tmp_path / "packages" / "feature").mkdir(parents=True)
    (tmp_path / "packages" / "feature" / "test.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "tests").mkdir(parents=True)
    (tmp_path / "src" / "test.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "tests" / "test_cli.py").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True, max_results=4)

    suggestions = provider.get_suggestions(("@test",), 0, len("@test"))

    assert suggestions is not None
    values = [item.value for item in suggestions.items]
    assert values[:3] == [
        "@src/test.py",
        "@packages/feature/test.py",
        "@src/tests/test_cli.py",
    ]
    assert values.index("@test/") > values.index("@src/test.py")


def test_path_completion_provider_drops_low_quality_recursive_at_noise_when_strong_matches_exist(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "test_api.py").write_text("", encoding="utf-8")
    (tmp_path / "noise").mkdir()
    (tmp_path / "noise" / "t_e_s_t_cache.txt").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True, max_results=10)

    suggestions = provider.get_suggestions(("@test",), 0, len("@test"))

    assert suggestions is not None
    assert [item.value for item in suggestions.items] == ["@src/test_api.py"]


def test_path_completion_provider_respects_gitignore_for_recursive_at_paths(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__/\nbuild/\n", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "module.cpython-313.pyc").write_bytes(b"cache")
    (tmp_path / "src" / "module.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "module.pyc").write_bytes(b"cache")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "module.py").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True)

    suggestions = provider.get_suggestions(("@module",), 0, len("@module"))

    assert suggestions is not None
    assert [item.value for item in suggestions.items] == ["@src/module.py"]

    assert provider.get_suggestions(("@build/module",), 0, len("@build/module")) is None


def test_path_completion_provider_uses_fd_for_recursive_at_paths(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    args_file = tmp_path / "fd-args.txt"
    fake_fd = tmp_path / "fd"
    fake_fd.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {args_file}\n"
        "printf 'src/module.py\\n'\n"
        "printf 'src/pkg/\\n'\n",
        encoding="utf-8",
    )
    fake_fd.chmod(0o755)

    # macOS takes ~0.3s to first-exec a freshly written script, exceeding the
    # provider's default 0.25s fd timeout; give the fake fd a generous budget.
    provider = PathCompletionProvider(
        base_path=tmp_path,
        recursive=True,
        fd_path=fake_fd,
        fd_timeout_seconds=5.0,
    )

    suggestions = provider.get_suggestions(("@module",), 0, len("@module"))

    assert suggestions is not None
    assert [item.value for item in suggestions.items] == ["@src/module.py"]
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--base-directory" in args
    assert str(tmp_path) in args
    assert "--hidden" in args
    assert "--exclude" in args


def test_path_completion_provider_falls_back_when_fd_is_missing(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("", encoding="utf-8")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True, fd_path=tmp_path / "missing-fd")

    suggestions = provider.get_suggestions(("@module",), 0, len("@module"))

    assert suggestions is not None
    assert [item.value for item in suggestions.items] == ["@src/module.py"]


def test_path_completion_provider_falls_back_when_fd_times_out(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("", encoding="utf-8")
    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nsleep 1\n", encoding="utf-8")
    fake_fd.chmod(0o755)
    provider = PathCompletionProvider(
        base_path=tmp_path,
        recursive=True,
        fd_path=fake_fd,
        fd_timeout_seconds=0.01,
    )

    suggestions = provider.get_suggestions(("@module",), 0, len("@module"))

    assert suggestions is not None
    assert [item.value for item in suggestions.items] == ["@src/module.py"]


def test_path_completion_provider_cancels_running_fd_search(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nsleep 2\nprintf 'src/module.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)
    token = CompletionCancellationToken()
    provider = PathCompletionProvider(
        base_path=tmp_path,
        recursive=True,
        fd_path=fake_fd,
        fd_timeout_seconds=5.0,
    )

    thread = threading.Thread(target=lambda: (time.sleep(0.05), token.cancel("test")), daemon=True)
    started_at = time.monotonic()
    thread.start()
    suggestions = provider.get_suggestions(("@module",), 0, len("@module"), cancellation_token=token)
    elapsed = time.monotonic() - started_at
    thread.join(timeout=1.0)

    assert suggestions is None
    assert token.cancelled
    assert elapsed < 1.0


def test_path_completion_provider_stops_when_cancellation_token_is_cancelled(tmp_path: Path) -> None:
    from loushang.tui import PathCompletionProvider

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("", encoding="utf-8")
    token = CompletionCancellationToken()
    token.cancel("test")
    provider = PathCompletionProvider(base_path=tmp_path, recursive=True)

    suggestions = provider.get_suggestions(("@module",), 0, len("@module"), cancellation_token=token)

    assert suggestions is None


def test_slash_command_completion_provider_completes_command_names() -> None:
    from loushang.tui import SlashCommand, SlashCommandCompletionProvider

    provider = SlashCommandCompletionProvider(
        (
            SlashCommand(name="model", description="Select model"),
            SlashCommand(name="models", description="List models"),
        )
    )

    suggestions = provider.get_suggestions(("/mo",), 0, len("/mo"))

    assert suggestions is not None
    assert suggestions.prefix == "/mo"
    assert suggestions.group == "Commands"
    assert suggestions.items == (
        CompletionItem(value="/model", label="/model", description="Select model"),
        CompletionItem(value="/models", label="/models", description="List models"),
    )

    application = provider.apply_completion(("/mo",), 0, len("/mo"), suggestions.items[0], suggestions.prefix)

    assert application.lines == ("/model ",)
    assert application.cursor_col == len("/model ")


def test_slash_command_completion_provider_includes_argument_hint_in_description() -> None:
    from loushang.tui import SlashCommand, SlashCommandCompletionProvider

    provider = SlashCommandCompletionProvider(
        (
            SlashCommand(name="model", description="Select model", argument_hint="<provider/model>"),
            SlashCommand(name="models", description="List models"),
        )
    )

    suggestions = provider.get_suggestions(("/mo",), 0, len("/mo"))

    assert suggestions is not None
    assert suggestions.items[0] == CompletionItem(
        value="/model",
        label="/model",
        description="<provider/model> - Select model",
    )


def test_slash_command_completion_provider_fuzzy_matches_command_names() -> None:
    from loushang.tui import SlashCommand, SlashCommandCompletionProvider

    provider = SlashCommandCompletionProvider(
        (
            SlashCommand(name="memory-status", description="Show memory status"),
            SlashCommand(name="model", description="Select model"),
            SlashCommand(name="permissions", description="Manage permissions"),
        )
    )

    suggestions = provider.get_suggestions(("/ms",), 0, len("/ms"))

    assert suggestions is not None
    assert suggestions.items[:1] == (
        CompletionItem(value="/memory-status", label="/memory-status", description="Show memory status"),
    )


def test_slash_command_completion_provider_does_not_duplicate_existing_argument_space() -> None:
    from loushang.tui import SlashCommand, SlashCommandCompletionProvider

    provider = SlashCommandCompletionProvider((SlashCommand(name="model", description="Select model"),))
    suggestions = provider.get_suggestions(("/mo moonshot",), 0, len("/mo"))

    assert suggestions is not None

    application = provider.apply_completion(("/mo moonshot",), 0, len("/mo"), suggestions.items[0], suggestions.prefix)

    assert application.lines == ("/model moonshot",)
    assert application.cursor_col == len("/model")


def test_generic_completion_provider_does_not_duplicate_slash_command_argument_space() -> None:
    provider = CompletionProvider((CompletionItem(value="/model", label="/model"),))
    suggestions = provider.get_suggestions(("/mo moonshot",), 0, len("/mo"))

    assert suggestions is not None

    application = provider.apply_completion(("/mo moonshot",), 0, len("/mo"), suggestions.items[0], suggestions.prefix)

    assert application.lines == ("/model moonshot",)
    assert application.cursor_col == len("/model")


def test_slash_command_completion_provider_completes_command_arguments() -> None:
    from loushang.tui import SlashCommand, SlashCommandCompletionProvider

    provider = SlashCommandCompletionProvider(
        (
            SlashCommand(
                name="model",
                description="Select model",
                argument_group="Models",
                argument_provider=CompletionProvider(
                    (
                        CompletionItem(value="moonshot/kimi-for-coding", label="moonshot/kimi-for-coding"),
                        CompletionItem(value="openai/gpt-5.4", label="openai/gpt-5.4"),
                    )
                ),
            ),
            SlashCommand(name="models", description="List models"),
        )
    )

    suggestions = provider.get_suggestions(("/model gpt",), 0, len("/model gpt"))

    assert suggestions is not None
    assert suggestions.prefix == "/model gpt"
    assert suggestions.group == "Models"
    assert suggestions.items == (
        CompletionItem(value="/model openai/gpt-5.4", label="openai/gpt-5.4"),
    )

    application = provider.apply_completion(("/model gpt",), 0, len("/model gpt"), suggestions.items[0], suggestions.prefix)

    assert application.lines == ("/model openai/gpt-5.4",)
    assert application.cursor_col == len("/model openai/gpt-5.4")


def test_slash_command_path_argument_completion_keeps_cursor_inside_quoted_directory(tmp_path: Path) -> None:
    from loushang.tui import (
        PathCompletionProvider,
        SlashCommand,
        SlashCommandCompletionProvider,
    )

    (tmp_path / "notes folder").mkdir()
    provider = SlashCommandCompletionProvider(
        (SlashCommand(name="read", argument_provider=PathCompletionProvider(base_path=tmp_path)),)
    )

    suggestions = provider.get_suggestions(("/read @not",), 0, len("/read @not"))
    assert suggestions is not None

    application = provider.apply_completion(("/read @not",), 0, len("/read @not"), suggestions.items[0], suggestions.prefix)

    assert application.lines == ('/read @"notes folder/"',)
    assert application.cursor_col == len('/read @"notes folder/')


def test_slash_command_path_argument_completion_reuses_existing_closing_quote(tmp_path: Path) -> None:
    from loushang.tui import (
        PathCompletionProvider,
        SlashCommand,
        SlashCommandCompletionProvider,
    )

    (tmp_path / "notes folder").mkdir()
    (tmp_path / "notes folder" / "daily note.md").write_text("", encoding="utf-8")
    provider = SlashCommandCompletionProvider(
        (SlashCommand(name="read", argument_provider=PathCompletionProvider(base_path=tmp_path)),)
    )
    line = '/read @"notes folder/d" after'
    cursor_col = len('/read @"notes folder/d')

    suggestions = provider.get_suggestions((line,), 0, cursor_col)
    assert suggestions is not None

    application = provider.apply_completion((line,), 0, cursor_col, suggestions.items[0], suggestions.prefix)

    assert application.lines == ('/read @"notes folder/daily note.md" after',)
    assert application.cursor_col == len('/read @"notes folder/daily note.md"')
