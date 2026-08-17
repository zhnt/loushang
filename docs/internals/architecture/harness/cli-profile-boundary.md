# Harness CLI Profile Boundary

`loushang.harness.cli` owns the product-neutral command-line grammar contract:

- `CliArgumentSpec` and `CliCommandSpec` describe flags and commands;
- `CliProfile.augment()` composes a standard profile with Product additions;
- `parse_args()` returns an ownership-separated `CliInvocation`.

The composition rule is additive. A Product may add a new flag, command, or
command argument, but may not replace an existing argument ID, destination,
flag, command ID, or command alias. Ambiguous composition fails at startup with
`CliProfileError`. A changed meaning requires an explicit profile or protocol
version rather than a silent override.

Ownership is intentionally split:

| Layer | Responsibility |
| --- | --- |
| `harness.cli` | grammar, validation, parsing, standard values |
| `channel` | transport selection, framing, stdio lifecycle and delivery |
| `harnesstui.cli` | TUI-specific host adapter and presentation setup |
| Product package | Product command additions, domain handlers, wording and output contract |

The profile does not construct a session or execute a command. Product hosts
consume `CliInvocation`, bind their own ports, and select the runtime. This
keeps Coding, Design, PPT and Research on one standard grammar without making
Harness understand any Product domain.
