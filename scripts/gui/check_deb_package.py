"""Opt-in acceptance of the actual deb payload; no model requests or installation."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deb", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="loushang-deb-check-") as directory:
        root = Path(directory)
        subprocess.run(
            ["dpkg-deb", "-x", str(args.deb.resolve()), str(root / "extracted")],
            check=True,
        )
        package = root / "extracted/opt/loushang"
        launcher = root / "extracted/usr/bin/loushang"
        assert launcher.resolve() == package / "loushang"
        for name, flags, expected in (
            ("loushang-mux", ("service", "--help"), "restart"),
            ("loushang-tui", ("--help",), "--connection-root"),
        ):
            entry = root / "extracted/usr/bin" / name
            assert entry.resolve() == package / name
            help_text = subprocess.check_output(
                [str(entry), *flags],
                cwd=root,
                env={"PATH": "/nonexistent"},
                text=True,
                timeout=15,
            )
            assert expected in help_text
        unit = root / "extracted/usr/lib/systemd/user/loushang-host.service"
        assert "ExecStart=/usr/bin/loushang-mux " in unit.read_text()
        assert (package / "web/index.html").is_file()
        for name in ("loushang", "bin/harness-gui", "bin/loushang-web"):
            with (package / name).open("rb") as binary:
                assert binary.read(4) == b"\x7fELF"
        print(
            "PASS: extracted Debian GUI, bundled Web, TUI/mux, user unit and managed AppHost"
        )


if __name__ == "__main__":
    main()
