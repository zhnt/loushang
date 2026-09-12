# G18 Linux Design Pilot

The subsequent wheel-based 400-sample A/A measurement is recorded separately in
[G18 Linux Installed-Entry Freeze](startup-performance-g18-linux-freeze.md).
This historical pilot is not overwritten or relabeled as the formal reference.

## Status And Scope

- Date: 2026-09-09 UTC
- Status: descriptive design evidence, **not** a reproducible performance gate
- Design: [G18 plan](startup-performance-plan.md)
- Source: `9bc69361494293595ae424be225c61e3226a9996`; product source and lock unchanged
- Branch: `harness/g18-startup-performance`
- Environment: Linux 7.0.0-29-generic, x86_64, glibc 2.43; one reported logical CPU
- Interpreter: CPython 3.11.15, Clang 21.1.4, private non-editable installation
- Lock SHA256: `556547755c39ef7063c8cb1c3624b322d13216fc8abe621daa6fe095d5b1146d`

The earlier startup proposal's historical measurements are not this baseline.
This pilot confirms the need to investigate current import/CLI paths; it does
not identify a causal per-module saving or establish an optimization result.
No current macOS/Windows performance measurements were taken.

## Isolation And Invocation

Task-local paths, relative to the Harness worktree:

- Interpreter: `.artifacts/g18-design/venv/bin/python`
- uv cache: `.artifacts/g18-design/uv-cache`
- Child cwd: `.artifacts/g18-design/empty-cwd`
- Probe and raw result: `.artifacts/g18-design/probe.py`, `.artifacts/g18-design/pilot.json`
- Source-test report: `.artifacts/g18-design/design-baseline.xml`

Setup and pilot invocation:

```bash
UV_PROJECT_ENVIRONMENT=.artifacts/g18-design/venv \
uv --cache-dir .artifacts/g18-design/uv-cache \
  sync --locked --extra dev --no-editable --python 3.11

uv --cache-dir .artifacts/g18-design/uv-cache run --no-project \
  --python .artifacts/g18-design/venv/bin/python \
  .artifacts/g18-design/probe.py
```

The probe captured `sys.prefix`, asserted `loushang.coding.__file__` under the private
environment's site-packages, and asserted distribution `direct_url.json` with
`dir_info.editable=false`. No ordinary `.venv` was rewritten. The install was
non-editable, but this pilot did not retain a wheel hash: G18.0's formal wheel
provenance requirement is therefore **not satisfied** by this evidence.

Each child used that interpreter with `-I -c CODE`, stdin DEVNULL, stdout/stderr
pipes, no TTY, and a 60-second diagnostic timeout. For imports CODE was an import
statement; for CLI cases it imported the installed entry module's `main` and
executed `raise SystemExit(main([...]))`. The cases below identify module/argv.
The parent recorded monotonic spawn-to-exit wall time, discarded exactly one
declared warmup per case, and retained the subsequent five samples in order.
Cases ran sequentially, not interleaved against a candidate. All children exited
zero; expected help/version text was **not** asserted, so this is timing pilot
evidence, not CLI output acceptance or console-script wrapper coverage.

Bytecode/page caches were **as found**, including the preceding identity probe;
this is neither absent-pyc nor OS-cold evidence. No user configuration fixture
was installed; child environment was inherited. Only imports and explicit help/version were invoked, not sessions
or native startup. The final benchmark must explicitly isolate configuration
and validate outputs/side-effect boundaries; `-I` alone does not isolate app data.

## Observations

Seconds, five retained fresh-process samples; no profiling instrumentation:

| Case | Raw samples in order | Median | Min–max |
| --- | --- | --- | --- |
| `import loushang.harness` | 0.115264, 0.123483, 0.139372, 0.146883, 0.144034 | 0.139372 | 0.115264–0.146883 |
| `import loushang.coding` | 9.880991, 8.766004, 8.840968, 8.665067, 9.623466 | 8.840968 | 8.665067–9.880991 |
| `import loushang.coding.cli.__main__` | 12.709122, 15.290549, 13.376270, 9.534874, 6.446404 | 12.709122 | 6.446404–15.290549 |
| CLI `__main__`, `--help` | 14.900875, 10.995728, 10.173868, 13.129681, 10.129719 | 10.995728 | 10.129719–14.900875 |
| CLI `__main__`, `--version` | 5.481997, 5.811140, 5.943345, 8.185973, 5.875757 | 5.875757 | 5.481997–8.185973 |
| CLI `hosted`, `--help` | 5.197721, 4.706129, 4.501929, 5.378497, 4.526971 | 4.706129 | 4.501929–5.378497 |
| CLI `hosted_client`, `--help` | 5.156575, 4.690848, 4.005546, 4.250691, 4.867013 | 4.690848 | 4.005546–5.156575 |
| CLI `mux`, `--help` | 3.968459, 5.017099, 5.025340, 5.926832, 12.816148 | 5.025340 | 3.968459–12.816148 |

Load averages (1/5/15 minutes) were approximately 4.23/2.40/1.32 before and
3.32/3.09/2.02 after. The machine was not dedicated; large within-case variation
makes this unsuitable for a hard timing threshold or subtracting one case's
median from another as a causal import cost. No p95, RSS improvement, user-ready
latency or speedup is claimed. No own pytest/build ran during the timed probe.

Probe SHA256: `02daf3995c75107b6ddbb253123f13056d16839f5eb2f81cfcaff523f537965a`.
Raw JSON SHA256: `566b5a6c32d37103b3a73640194c8cb9ee36a4406a4324a6816368e38a71549a`.
Local artifacts are disposable; the retained table/conditions are the durable
pilot record. A checked-in, tested runner and formal evidence schema remain G18.0 work.
The pilot writes its report only after all cases succeed; all did succeed here,
but incremental partial-failure persistence is another unimplemented G18.0 requirement.

## Baseline Functional Checks

Result: **11 passed in 79.59 s**, after the timed pilot completed. Command:

```bash
uv --cache-dir .artifacts/g18-design/uv-cache run --no-project \
  --python .artifacts/g18-design/venv/bin/python scripts/dev/run_pytest.py \
  tests/coding/test_sdk_surface.py \
  tests/coding/test_cli_extension_flags.py \
  tests/coding/test_ui_import_boundaries.py::test_importing_shared_screen_state_does_not_load_coding_ui \
  tests/coding/test_ui_import_boundaries.py::test_importing_non_ui_coding_owners_does_not_load_ui_layers \
  -q -m 'not live' --skip-host-runtime \
  --junitxml=.artifacts/g18-design/design-baseline.xml
```

These are source-mode, non-live SDK surface, extension-help/injection and two
import-boundary checks. They are separate from the installed pilot and do not
constitute native launch/readiness acceptance.
