"""Real Product/PTY Markdown path with the existing synthetic model fixture."""

from ._g18_native_probe import _replay_embedded_output
from .test_mux_product_terminal import _command, _product, _see, _terminal


def test_installed_hosted_markdown_survives_detach_and_snapshot(tmp_path):
    def rendered(driver, *, after=0):
        def witness(output):
            end = output.rfind("\x1b[?2026l")
            if end < after:
                return False
            screen = _replay_embedded_output(output[:end + len("\x1b[?2026l")])
            text = "\n".join(screen.visible_lines)

            def styled_token(token, *, bold=False):
                for row, line in enumerate(screen.visible_lines):
                    column = line.find(token)
                    if column >= 0:
                        styles = screen.cell_styles[row][column:column + len(token)]
                        return all(style.foreground is not None and (not bold or style.bold) for style in styles)
                return False

            return (
                "Render witness" in text and "bold witness" in text and "code witness" in text
                and "## Render witness" not in text and "**bold witness**" not in text
                # Shared Markdown deliberately retains styled code fences.
                # Plain raw Markdown must still fail the heading/code styles.
                and styled_token("Render witness", bold=True)
                and styled_token("```python") and styled_token("print")
                and "*1 |" in text
            )
        driver.read_until(witness, timeout=35)

    # Test helper supplies only a synthetic transport; Product, IPC, installed
    # terminal renderer and session persistence are real. No network model IO.
    with _product(tmp_path) as (server, environment):
        _command(tmp_path, environment, "create", "markdown-review")
        with _terminal(tmp_path, environment, "markdown-review") as driver:
            driver.write("/new user_home Markdown\r")
            _see(driver, "*1")
            offset = len(driver.raw_output)
            driver.write("markdown\r")
            rendered(driver, after=offset)
            driver.write("\x02d")
            assert driver.wait(timeout=15) == 0, driver.diagnostics
        assert server.poll() is None
        with _terminal(tmp_path, environment, "markdown-review") as reattached:
            rendered(reattached)
            reattached.write("\x02d")
            assert reattached.wait(timeout=15) == 0, reattached.diagnostics
        _command(tmp_path, environment, "stop")
        assert server.wait(timeout=20) == 0
