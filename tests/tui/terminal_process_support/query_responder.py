from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TerminalQueryResponder:
    """Minimal incremental responder for blocking headless terminal queries."""

    rows: int
    columns: int
    respond_to_cell_size: bool = False
    unknown_queries: list[str] = field(default_factory=list)
    _control: str = ""

    def feed(self, text: str) -> tuple[str, ...]:
        responses: list[str] = []
        for character in text:
            if not self._control:
                if character == "\x1b":
                    self._control = character
                continue
            self._control += character
            if self._control == "\x1b" and character != "[":
                self._control = "\x1b" if character == "\x1b" else ""
                continue
            if not self._control.startswith("\x1b["):
                continue
            if len(self._control) == 2:
                continue
            if "@" <= character <= "~":
                responses.extend(self._response_for(self._control))
                self._control = ""
            elif len(self._control) > 64:
                self._control = ""
        return tuple(responses)

    def _response_for(self, sequence: str) -> tuple[str, ...]:
        if sequence in {"\x1b[c", "\x1b[0c"}:
            return ("\x1b[?1;0c",)
        if sequence == "\x1b[5n":
            return ("\x1b[0n",)
        if sequence == "\x1b[6n":
            return ("\x1b[1;1R",)
        if sequence == "\x1b[16t" and self.respond_to_cell_size:
            return (f"\x1b[6;{self.rows};{self.columns}t",)
        if sequence in {"\x1b[?u", "\x1b[16t"}:
            return ()
        if sequence.endswith("n"):
            self.unknown_queries.append(sequence)
        return ()
