# GUI interface localization delivery

Date: 2026-11-06 (Asia/Shanghai)
Branch: `feature/gui-i18n`, based on GUI delivery head `e870ad1ee` (includes
`lane/gui` and the already committed icon work). Delivery is on the task branch;
integration into `lane/gui` remains a separate step.

## Implemented scope

- i18next 26.7.2, react-i18next 17.1.13, i18next-cli 1.85.1; JSON resources in
  five functional namespaces, en-US baseline and zh-CN translation.
- Sidebar language preference, startup resolution, persistence, readable fallback,
  localized React menu/window controls, UI labels, accessibility and async notices.
- OS locale through official Tauri plugin-os 2.3.1, permission limited to locale;
  retained existing Tauri framework versions. No Rust dictionary or new menu system.
- Stable UI notice keys/parameters, localized product error explanation and raw
  diagnostic detail. Runtime contracts and existing content remain unchanged.
- Official generated resource types, string-key convention and local quality
  commands. No new required CI route or PR gate.

## Execution log

1. Read repository and ub-mode instructions; inspected clean GUI lane, settings,
   rendering and native boundaries. Created task branch preserving existing work.
2. Added language and interaction tests before implementation; confirmed failure
   for missing resolver and language selector.
3. Built startup/selection/persistence and native-frame integration. Pilot passed
   26 tests and type checking, including drafts, async results and subscription
   preservation. Existing native-menu row was verified as React, so no native
   menu subsystem was invented.
4. Migrated UI text and dynamic labels. Read-only review caught a mechanical
   action-string replacement, corrected before acceptance; internal reducer
   actions remain unchanged.
5. Resolved review findings: neutral activity counts, formatted diff counts,
   diagnostic separation, resource organization and dependency scope.
6. Probed actual tool behavior. Wrong keys/parameter names fail TypeScript, but
   entirely omitted options are not reliably rejected. Official CLI call-site
   lookup misses custom namespaces. Added only the narrow missing-options check
   plus nonempty/key/plural checks. Six negative probes reject missing options,
   missing plural count, empty translation, missing key, missing plural form and
   wrong placeholder. Restored all probe edits afterward.
7. Ran GUI tests/coverage, browser layout and native checks. Inspected screenshots;
   corrected long-label wrapping and tested narrow-screen overlay navigation.
   Expanded-text screenshot review exposed an implicit grid column overflow;
   reproduced it with control-boundary assertions, fixed the column sizing, and
   reran all 13 browser scenarios successfully.
8. Ran ub-mode complexity, duplication and language mutation checks. Generated
   reports remain local and ignored; removed accidental root test cache/report
   files from the repository. Existing long-lived worktree remains in use.
9. Recorded reviewer acceptance and remaining platform limitations below.
10. On user request, scoped non-test `dead_code` exemptions to the two reserved
    connection-lifecycle declarations. Kept global `-D warnings` and reran
    `check:full` successfully; no runtime behavior changed.
11. Repeated the complete audit on user request. Actual Tauri packaging exposed
    npm API 2.12.4 versus Rust 2.11.5, which `check:full` did not detect. Restored
    the original API 2.11.1 and pinned it exactly. The native build then passed.
12. Added browser startup tests for zh-CN, zh-SG, zh-TW, en-GB and de-DE, plus
    a complete 11-event playback with repeated language switching and open
    review/task/agent panels. Verified raw diffs, selected details and drafts.
13. Added absent-native-locale fallback and live-UI rejected-submission tests.
    Verified localized product explanation, unchanged raw diagnostic/content,
    and draft preservation. Repeated six resource fault probes and restored all
    temporary changes.
14. Launched the actual Linux fixture executable with isolated XDG directories.
    Used AT-SPI to verify Chinese startup, zh/en switching, maximize/restore,
    saved Chinese preference after restart under an English locale, and returning
    to follow-system. Reviewed rendered screenshots after WebView repaint and
    closed the test windows. Existing user data/configuration were not changed.

## Validation

| Check | Observed result |
| --- | --- |
| TypeScript + GUI coverage run | 12 files, 75 tests passed in the final audit |
| `make check-changed` | Selected GUI and documentation checks passed |
| `build:web` | TypeScript and production bundle passed |
| `check:i18n` | 5 namespaces; all 198 required Chinese entries present; no empty entries or placeholder errors |
| Resource failure probes | 6 invalid cases rejected; temporary changes restored |
| Browser layout and interaction | 19 passed, including en/zh, 700/1100/1440 widths, five startup locales, reload persistence, expanded text and full playback; screenshots reviewed |
| Locked default and fixture cargo check | Passed with pre-existing dead-code warnings |
| Offline Rust library tests | 7 passed in each of default and fixture-bridge configurations |
| `check:full` | Passed after the scoped warning exemptions and API version alignment: build, 75 GUI tests, rustfmt, default/fixture Clippy and cargo check |
| Native build | `npm exec -- tauri build --debug --no-bundle --features fixture-bridge` passed |
| Native Linux execution | Actual packaged WebView, locale detection, switching, persistence, maximize/restore and close passed; screenshots reviewed |
| ub-mode mutation | All 8 language resolver mutation sites killed |
| ub-mode duplication | No candidates at threshold 0.8 in new i18n/native-frame/checker scope |
| ub-mode CRAP | New i18n/runtime functions and native-frame functions at or below 7.4 with collected coverage |

Metrics focus on the new language mechanism and the touched native frame.
The existing large App component was not redesigned to satisfy a numerical
metric; runtime/session orchestration refactoring is outside this delivery.
Screenshots and reports live under ignored `gui/test-results/`, `gui/coverage/`
and `gui/.metrics/`. The full terminal execution logs are local under
`/tmp/loushang-i18n/`, not repository artifacts.

## Review and limitations

The read-only `i18n_review` agent reviewed the actual implementation, including
React integration, resource boundaries, persistence and supplementary checking.
It confirmed the plural-base omission fix in a final read-only review and
accepted the current implementation scope. Its role was `/root/i18n_review`;
the reviewed artifact was the uncommitted task-branch diff, not a released build. This is internal
technical acceptance, not a statement of user desktop acceptance.

`npm run check:full` initially failed on existing Linux dead-code errors:
`Phase::Reading` and `ConnectionLifecycle::start` in
`src-tauri/src/connection_lifecycle.rs`. On the user's subsequent request, these
two reserved declarations received `cfg_attr(not(test), allow(dead_code))` with
an explanation that production admission is not yet wired. Global `-D warnings`
remains active, and test builds retain dead-code checks. The complete command
now passes on Linux. Remove these exemptions when production admission uses
the entry point. This follow-up was validated locally after the agent review.

The final audit now includes actual Linux/X11 (XWayland) window acceptance using
the debug fixture build with bundled production frontend assets. Locale inputs
were controlled with process environment variables; the user's OS settings were
not changed. The executable SHA-256 was
`da28248f25c6944ffd6e52aa8e659646da28c165699e5eb3c0cd47848e464ac5`.
Evidence is in ignored `gui/test-results/native-i18n/` and
`/tmp/loushang-i18n/native-*.{log,json,png,py}`. Native draft editing was unavailable
through this machine's AT-SPI EditableText interface; draft preservation was
verified through component and browser tests, not claimed as native input coverage.

Real macOS/Windows visual behavior, OS scaling, native IME/clipboard and
platform-provided menus still require platform-specific acceptance. The Linux
run does not establish release installer/signing or real provider integration.
The live-UI test uses the accepted client interface with local data and makes no
network calls. Resource completeness (198/198) is not a percentage proof of every
possible UI state; source review, runtime paths and platform evidence are reported
separately.
No new tray, notification, multi-window or dynamic system-language mechanism is
claimed. Follow-system is resolved at startup and when selected.
