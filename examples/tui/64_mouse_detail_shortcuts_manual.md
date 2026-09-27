# Mouse and detail manual exercise

Run the companion script from this checkout. In the Linux development worktree:

```sh
PYTHONPATH=src /home/dev/lsspace/loushang/.venv/bin/python examples/tui/64_mouse_detail_shortcuts_manual.py
```

On macOS or Windows, use that checkout's Python environment and set
`PYTHONPATH=src`. The script makes no network calls.

Check these interactions in each environment:

1. Press F4, then Up/Down, Enter and Space. The focused control changes and
   Show Detail/Show Less toggles without inserting Space into the draft.
2. Press Esc to return to the composer. Ctrl+T opens and closes the reader.
   Ctrl+O copies the latest completed answer; reader `d`/`r` still change the
   whole-view detail/raw modes.
3. When mouse reporting is active, click and release on a control, then drag
   transcript text and copy it. A drag starting on a control must not toggle it.
   A copied range spanning tools must omit Show Detail/Show Less labels.
4. With a selection, Ctrl+C copies; Esc clears selection; Ctrl+C without a
   selection resumes the usual cancel behavior. A failed copy must report its
   failure and leave the selection available.
5. Enter `/quit` to exit and confirm the terminal's selection behavior has
   been restored.

| Environment | Setup | Expected mouse ownership |
| --- | --- | --- |
| Direct Linux desktop | X11/Wayland clipboard command available | Application in `auto`; click and drag work. |
| Headless Linux | No display/clipboard command | Terminal in `auto`; keyboard detail works. |
| macOS terminal | `pbcopy` available | Application in `auto`. |
| tmux mouse on | `tmux set -g mouse on` and user clipboard route | Application in `auto`. |
| tmux mouse off | `tmux set -g mouse off` | Terminal in `auto`; select/copy via tmux or host, F4 still works. |
| SSH | Default settings | Terminal in `auto`; native terminal selection remains. |
| SSH with OSC 52 | `LOUSHANG_TUI_OSC52=1` and terminal permits OSC 52 | Application in `auto` if tmux permits; copy reports unconfirmed send. |
| Windows Terminal/ConPTY | Native VT input and `clip.exe` available | Application in `auto`; Unicode copy works. |
| Windows VT input denied | VT input unavailable | Terminal selection remains active. |

Use `--mouse-policy terminal` and `--mouse-policy application` to compare both
paths regardless of automatic detection. Set `LOUSHANG_TUI_MOUSE_POLICY` to
the same values when exercising the real conversation CLI. The `/terminal`
diagnostic view reports the resolved owner, tmux probe and whether a mouse
event reached the app. A missing event does not reveal whether the terminal
rejected mouse reporting or the user declined a permission prompt.

Observed in this worktree: Linux pseudo-terminal startup, Ctrl+T reader open,
Ctrl+O dispatch, reader close, `/quit`, and terminal cleanup. Other host rows
are a manual checklist for those systems.
