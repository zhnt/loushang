# Plugin Authoring Guide

This guide starts with native resource files, then covers Plugin Wheels and
the stable PLC8 author SDK. A Plugin declares data and references; Loushang's
existing owners select, admit, bind, authorize, publish, and retire runtime
objects.

`loushang-plugin validate <package-tree>` checks the inert manifest and
declarations. Its JSON reports `productAdmission`, `productSelection`, and
`productUse` as `"not_checked"`, even when `valid` is true. The Coding wheel build
commands report the same three statuses alongside the artifact profile and
digest. The target Product must still admit the final wheel, and its actual
Session or Screen consumer must separately prove use.

The [support matrix](plugin-support-matrix.md) records the current route and
platform gates for each kind.

## Start With Native Resources

Use a native file when the resource belongs to one workspace and does not need
independent installation, enablement, version selection, or removal:

| Resource | File | Current consumer and limit |
| --- | --- | --- |
| Skill | `.loushang/skills/<name>/SKILL.md` | Coding discovers Skills with `loushang --list-skills`; a new Session can select one. Listing alone does not prove its text reached model input. |
| Prompt | `.loushang/prompts/<name>.md` | Coding's new Session command path exposes it as `/<name>` and expands the selected Prompt into model input. |
| Theme | `.loushang/themes/<name>.json` | Coding's native Theme Catalog can describe it. The current Screen applies only a Product-selected external Theme Wheel, so this native file does not change Screen colors. |
| Method | `methods/<name>/SKILL.md` | The Method loader exposes `--list-methods`, `--show-method`, and `--method` in non-interactive prompt/print/json runs. TUI and RPC Method execution are not supported. `METHOD.md` is not a Method entrypoint. |
| Extension | `.loushang/extensions/<name>.py` or `.loushang/extensions/<name>/extension.py` | Coding loads trusted Python in-process; `register(api)` can add tools, hooks, commands, flags, and dynamic resources. `/extensions` inspects loaded extensions. This has no Wheel Package lifecycle. |

`AGENTS.md` follows the separate instruction-file convention. It is not a
Plugin Resource declaration. Use a Wheel below when the resource needs a
separate Plugin lifecycle. The Wheel build and validation commands establish
artifact validity; the named Product consumer establishes actual use.
The first three paths are relative to the workspace root; user-wide Resource
files use the corresponding directories under the resolved Loushang platform
home. The Method loader uses the separate workspace `methods/` directory.
Wheel source trees below may also contain `skills/`, `prompts/`, or `themes/`,
but they are package inputs rather than auto-discovered workspace files.

For a small code extension, place a Python file in `.loushang/extensions/`
and define `register(api)`. `loushang-coding-extension init
.loushang/extensions/hello.py` creates a no-replace template and prints its
`smokeCommand`. The smoke copies that file into a disposable fenced Product
workspace, starts a real offline Coding Session, and calls its selected Tool.
The Extension still executes as trusted Python in the current process; the
disposable workspace is not a code sandbox. Neither command installs a Wheel
or admits executable Wheels. The
[runnable tool example](../../../../../examples/coding/extensions/03_custom_tool.py)
shows the `@tool`, `direct_tool(...)`, and `api.register_tool(...)` pattern. This is a trusted
same-process path. The old raw `--extension`/`-e` CLI arguments are removed;
use native discovery. A declared executable Extension in a Wheel does not
inherit this native route's Product admission.

## Short Skill/Prompt Author Journey

For a reusable document-only Resource, scaffold source, edit the Markdown,
build, and run a disposable Product smoke before installing in the target
workspace:

```text
loushang-plugin init-coding-skill ./reviewpack --resource-name review
# Edit ./reviewpack/skills/review/SKILL.md.
# Run buildCommand from the JSON result.
# Run smokeCommand from the JSON result.
```

Use `init-coding-prompt` for a Prompt. Scaffold creation refuses to replace
an existing source directory. The JSON `buildCommand` makes a deterministic
Wheel and still reports Product admission/use as `not_checked`. The
`smokeCommand` calls the Coding-owned `loushang-coding-plugin-smoke` entrypoint
with that exact Wheel in a disposable, offline, fresh Coding Product workspace.
It installs and enables the Plugin, starts a new Session,
invokes the requested Resource, and checks the persisted prepared model input.
The result reports `productAdmission`, `productSelection`, and `productUse`
separately; a failed stage leaves later stages `not_checked`. It currently
requires the ordinary POSIX Product route and proves only that temporary
workspace. Install and enable the Wheel separately in the destination
workspace, then check its own Session. These Skill/Prompt commands do not open
the Theme or Worker candidate gates.

For the existing Screen Theme candidate, run `loushang-plugin
init-coding-theme ./themepack --resource-name dusk`, edit
`./themepack/themes/dusk.json`, then run its returned `buildCommand` and
`smokeCommand`. The Theme smoke installs and enables the exact Wheel in a
disposable fenced Product workspace, selects `theme: plugin:dusk`, and checks
the Coding Screen Theme consumer against the authored style tokens. This is
candidate evidence for that Wheel, not general Theme rollout, Hosted Mux
support, or admission in the destination workspace.

## Capability Provider

```python
from loushang.plugin import (
    PluginDefinitionBuilder,
    capability_provider,
    plugin_definition,
)


@plugin_definition
def declare(plugin: PluginDefinitionBuilder) -> None:
    plugin.add(
        capability_provider(
            contribution_id="echo-provider",
            capability="example.echo",
            provider_id="org.example.echo/default",
            implementation_version=1,
            contract=1,
            facets=("echo",),
            factory="provider.py:create_provider",
            disposer="provider.py:dispose_provider",
        )
    )
```

The referenced `provider.py` uses only the exact public provider-runtime ABI:

```python
from loushang.plugin.provider_runtime import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)


class EchoProvider:
    def __init__(self) -> None:
        self.closed = False

    def echo(self, value: str) -> str:
        return value

    async def close(self) -> None:
        self.closed = True


def create_provider(_context: CapabilityProviderContext) -> CapabilityBundleValue:
    return CapabilityBundleValue(
        facets=(CapabilityFacetBinding("echo", EchoProvider()),)
    )


async def dispose_provider(value: CapabilityBundleValue) -> None:
    provider = value.require("echo")
    if not isinstance(provider, EchoProvider):
        raise TypeError("echo facet has an unexpected value")
    await provider.close()
```

The Definition receives only the narrow builder. Provider source may directly
import Host API names only from the exact
`loushang.plugin.provider_runtime` module; broad author-SDK and Harness
Capability imports are rejected. This is a supported import/API boundary for
trusted host-equivalent Python, not an isolation boundary against reflection or
same-process introspection. The factory receives a
narrow `CapabilityProviderContext` and returns the exact declared facets in a
`CapabilityBundleValue`; the disposer receives that same bundle. Neither path
receives a Graph, Product registry, Approval store, Sandbox, secrets, or a
live owner/service locator.

## Coding Data Skill Wheel

For one independent, document-only Skill, the public author command creates
the exact wheel shape accepted by Coding's current external data Skill profile:
Run these commands from the author directory in an already fenced Coding
workspace; Product Source admission requires an absolute wheel path.

```text
loushang-plugin build-coding-skill skills/review/SKILL.md --plugin-id reviewpack --version 1 --output-dir dist
loushang --install-package "$(pwd)/dist/reviewpack-1-py3-none-any.whl" --package-scope project
loushang --enable-plugin reviewpack
```

The `SKILL.md` file stays in the author's source directory. The build command
generates the manifest, declaration document, wheel metadata, and RECORD. It
prints the artifact path and digest and refuses to overwrite an existing
wheel. Python authors may use `build_coding_data_skill_wheel()` for
deterministic bytes or `write_coding_data_skill_wheel()` for a new file.

This profile admits one Skill document, with no managed actions, executable
files, or dependencies. Coding Product still captures and revalidates the
final wheel during installation. Generic SDK package validity and Coding
Product compatibility are separate checks. Installation initially leaves the
Plugin disabled; enable it before expecting a new Session to select its Skill.

The [Coding data Skill example](../../../../../examples/plugins/coding_data_skill/README.md)
shows an explicit Product cutover, wheel build, install, new-Session Skill use,
update, disable, and uninstall. It distinguishes the CLI's installed/selected
facts from the separate persisted Model Input evidence.

## Coding Data Prompt Wheel

For one Markdown Prompt file, use the separately gated Coding profile on the
current POSIX fenced Product path:

```text
loushang-plugin build-coding-prompt prompts/review.md --plugin-id promptpack --version 1 --output-dir dist
loushang --install-package "$(pwd)/dist/promptpack-1-py3-none-any.whl" --package-scope project
loushang --enable-plugin promptpack
```

The command creates a deterministic wheel containing `prompts/review.md`,
the manifest, declaration document, and wheel metadata. Python authors may
call `build_coding_data_prompt_wheel()` or `write_coding_data_prompt_wheel()`.
The data declaration helper is `resource.prompt(contribution_id="review-prompt",
locator="prompts/review.md")`. Coding Product admits one Prompt per wheel in
this profile; executable files, dependencies, and other Resource kinds remain
outside it. A selected Prompt becomes available to a new Coding Session as
`/review`. Product Session evidence, not wheel validation alone, proves the
expanded Prompt reached the model input. Method, Asset, and Source still
have no corresponding public Coding wheel profile.

The [Coding data Prompt example](../../../../../examples/plugins/coding_data_prompt/README.md)
contains a source file and the complete build/install/use sequence.

## Candidate Coding Screen Theme Wheel

The Theme profile is a candidate pending its separate Product owner rollout
decision. It accepts one `themes/dusk.json` style document such as:

```json
{"schemaVersion":1,"tokens":{"welcome.title":{"color":"red"},"transcript.error":{"color":"bright_yellow"}}}
```

```text
loushang-plugin build-coding-theme themes/dusk.json --plugin-id themepack --version 1 --output-dir dist
loushang --install-package "$(pwd)/dist/themepack-1-py3-none-any.whl" --package-scope project
loushang --enable-plugin themepack
```

Set the Coding project setting `theme` to `plugin:dusk` and start a new Coding
Screen Session. `resource.theme(contribution_id="dusk-theme",
locator="themes/dusk.json")` and the `build_coding_data_theme_wheel()` Python
recipe create the same declaration profile. The Product admits the verified
wheel and the Resource owner selects its exact Store revision before the Screen
reads the Catalog descriptor. The Screen changes its visible styles; Theme
never enters model input. Disabling the Plugin restores built-in styles after
starting a new Session and restarting its Screen. Duplicate names block
composition, and invalid JSON is refused.
Hosted Mux and live Theme refresh do not consume this candidate.

The [Coding Screen Theme example](../../../../../examples/plugins/coding_data_theme/README.md)
contains the source document and the explicit build, install, selection, and
fallback sequence for this candidate.

## Default-dark Coding Worker Candidate Wheel

The Worker author recipe packages one native executable as a bounded,
reproducible Wheel. It does not launch the executable or approve it for Product
use. On Linux x86-64, the input must be an accepted static ELF; on Windows
amd64, it must be an accepted PE executable. The current profile contains one
read-only `capability.query` Provider with no requested authorities. An
optional, repeatable `--dependency dependency==1` writes up to three distinct
exact pins into Wheel metadata in canonical order.

```text
loushang-plugin build-coding-worker-candidate build/query-worker \
  --plugin-id reviewworker --version 1 \
  --contribution-id query-provider --owner-id coding \
  --native-platform linux-x86_64 --output-dir dist
```

The command defaults to the matching platform Wheel tag, refuses symlinks,
changed input bytes, oversized sources, invalid native format, and replacing
an existing output. Its JSON reports
`profile: "coding-local-worker-candidate-v1"`,
`productAdmission: "not_checked"`, and `productUse: "not_checked"`.
Python authors can use `build_coding_local_worker_candidate_wheel()` for bytes
or `write_coding_local_worker_candidate_wheel()` for a new file. The Coding
Product still requires its explicit Worker candidate policy, installation,
enabled selected revision, per-install opt-in, approved native closure, and
a Product-issued receipt before a Worker Session can use the package. Coding
Sessions select this candidate only when the caller explicitly supplies
`worker_candidate_plugin_id` on Linux. Dependency-bearing Worker
Wheels require a separately admitted Wheel for each dependency in the Product
Source. The current Package Product admission policy permits bounded
direct-dependency closures of up to four nodes, with pure-Python dependency
members only and no
transitive dependency edges. The real Product regression covers two dependency
Wheels and a non-pure dependency refusal. Product can capture and recheck the
selected dependency closure as bounded inert bytes under one GC read guard;
the earlier single-dependency reader still refuses larger closures. Product
refuses Worker opt-in and activation because no native dependency execution
profile has been approved. The author command does not install dependencies
or claim Product use.

This Worker Wheel recipe is currently a developer candidate, not a self-service
install flow. `loushang --install-package` admits the supported data Resource
Wheels; `loushang-worker-native install` installs an approved Hosting native
release, not the author's Worker Plugin. On Linux, a Product operator can
capture the exact inert Worker candidate through the fenced Product owner:

```text
loushang-worker-native --workspace PATH candidate-capture \
  --wheel dist/reviewworker-1-py3-none-manylinux_2_17_x86_64.whl \
  --contribution-id query-provider --owner-id coding \
  --native-platform linux-x86_64
```

The result identifies the captured digest and reports
`productAdmission: not_checked` and `productUse: not_checked`. On Linux the
operator can then install that exact candidate disabled, and enable the
installed revision using the returned inventory revision:

```text
loushang-worker-native --workspace PATH candidate-install \
  --plugin-id reviewworker --artifact-digest DIGEST \
  --operation-id install-reviewworker-1
loushang-worker-native --workspace PATH candidate-enable \
  --plugin-id reviewworker --artifact-digest DIGEST \
  --operation-id enable-reviewworker-1 \
  --expected-inventory-revision REVISION
```

The install result reports Product admission for that exact Wheel and returns
`alreadyInstalled: true` when a retry finds the same installed revision. The
enable result reports the Desired State operation. Neither proves Session use.
Per-install opt-in and an approved native release are still separate Product
decisions before a query or Python SDK Session can use the Worker. A successful
build or capture alone does not make the Worker usable.

To stop and remove a selected candidate, revoke its per-install opt-in, then
disable and remove the exact installed revision using the latest inventory
revision for each Desired State operation:

```text
loushang-worker-native --workspace PATH candidate-revoke \
  --plugin-id reviewworker --operation-id revoke-reviewworker-1 \
  --expected-generation GENERATION
loushang-worker-native --workspace PATH candidate-disable \
  --plugin-id reviewworker --artifact-digest DIGEST \
  --operation-id disable-reviewworker-1 \
  --expected-inventory-revision REVISION
loushang-worker-native --workspace PATH candidate-remove \
  --plugin-id reviewworker --artifact-digest DIGEST \
  --operation-id remove-reviewworker-1 \
  --expected-inventory-revision NEXT_REVISION
```

`candidate-remove` changes Desired State to absent after opt-in revocation.
It reports `packageRetirement: not_checked`; physical Package GC and any
pinned Session retirement require separate Product evidence.

On Linux, a Product operator can inspect or change per-install Worker opt-in
with `loushang-worker-native --workspace PATH candidate-status`,
`candidate-allow`, and `candidate-revoke`, each with `--plugin-id PLUGIN`.
Allow and revoke also require an operation ID and expected generation; allow
can set `--require-worker`. The Product derives the selected candidate and
requires an approved installed native release. These commands do not change
default Coding Session routing. `candidate-status` reports
`ordinarySessionRouting: "python_sdk_explicit_linux"` and
`defaultSessionRouting: "closed"`. Its `candidateSelection` is a read-only,
partial observation of the selected Worker version and executable digest;
`productUse` remains `not_checked`, and a changed snapshot is reported as
`stale_evidence`.
The ordinary Session opt-in is available through the Python SDK only; Coding
CLI, RPC, TUI, and Screen do not offer the same Worker selection switch.

The Python SDK exposes the same selected read-only query through an ordinary
Coding Session. For a direct Session, first create a persisted
`SessionManager` with `defer_materialization=False`, then pass that manager to
`create_agent_session(..., worker_candidate_plugin_id="reviewworker")`.
The caller can query the selected Worker with
`await session.query_worker_symbol("review")` and must dispose the Session
when done. For a hosted first Session, use
`create_agent_session_runtime(..., persist=True,
worker_candidate_plugin_id="reviewworker")`, then
`await runtime.create_session(cwd=...)` and query the returned Session in the
same way. The hosted transcript owner materializes that new Session before
issuing its Product receipt. The Product still checks the selected installed
revision, native approval, current receipt, and per-install opt-in. These
entrypoints do not enable Worker routing for other Sessions or on Windows.

For an already persisted Coding Session in that workspace, the explicit Linux
query Consumer can use the selected Worker after native release approval,
installation, and candidate opt-in:

```text
loushang-worker-native --workspace PATH query \
  --plugin-id reviewworker --session-file EXISTING_SESSION.jsonl --symbol review
```

The command returns JSON under `workerQuery.text`. It binds the existing
Session identity and current Product receipt, starts the installed Worker under
the native gate, and retires the Worker after the bounded query. It does not
create a Session, call a model, or route ordinary Coding turns. A Worker that
only implements this query contract does not provide Coding LSP tools or
diagnostics; those require their own Product and owner acceptance. This
explicit candidate has finite receipt and start-gate journals and is not a
general high-volume Worker route.
`loushang-worker-native --workspace PATH list-gated-attempts` lists retained
Product start-gate attempt IDs and phases for recovery triage; it does not
authorize a repair.

## Read-only Coding Preview

In a POSIX workspace that has completed the fenced Product cutover, inspect
the currently enabled data Resource composition without creating a Session:

```text
loushang --preview-current-plugins --preview-composition-set coding-standard
```

The JSON reports Product admission, projected Skill/Prompt names, stable
blocking codes, and explicit evidence gaps. `compiledPluginIds` covers the
data Resource compilation path; it does not claim a Capability Provider was
activated or that a Resource reached model input. The result is
`partial_evidence` because Session invocation options and an actual Catalog
generation are not captured. Persisted global/project disabled-Skill settings
are applied and identified by `disabledSkillSettingsRevision`; session-local overrides
remain in the invocation gap. An unfenced workspace returns
`plugin_preview_product_not_fenced` without creating Plugin state.
Coding's JSONL RPC Host also accepts `preview_current_plugins` with explicit
`productId`, `scopeId`, and `compositionSetId`; obtain the opaque `scopeId`
from the CLI result. Its `data` field uses the same preview schema and describes
a prospective new Session, not a change to the active RPC Session.
The optional `plugin_management_snapshot_v1` RPC query accepts `productId`,
`scopeId`, and an optional sorted `pluginIds` list. It reads only a fenced
Product workspace and returns the management projection, including verified
`backupRetention` when available. It does not submit a command or authorize
private-data deletion.
In the Coding Screen or plain TUI, `/plugins` presents the same read-only,
partial `coding-standard` preview in the local UI. It shows compiled Plugin
IDs, projected Catalog resources, blockers, and evidence gaps. `/plugins list`
reads the management owner's Installation and Desired State projection,
including convergence, unknown dimensions, and pending operation IDs. In an
already fenced workspace, `/plugins enable ID`, `/plugins disable ID`, and
`/plugins remove ID` submit exact Desired State commands under the Coding TUI
actor. Each result shows its operation ID; `/plugins repair OPERATION_ID`
resumes only a pending operation from that same actor. A stale Desired State
revision is reported for a fresh user decision. Changes reach new Sessions;
the active Session keeps its selected generation. Package install/update and
A2 repair use separate owner paths. For a Package A2 operation, the local TUI
accepts `/plugins repair-package ACTION OPERATION_ID` and delegates to the
same exact Product repair SDK as the offline CLI. `inspect-staging` activates
Product recovery; a committed repair affects only new Sessions. Coding's
optional JSONL RPC uses `repair_plugin_package_v1` with `productId`, `scopeId`,
`action`, and `operationId` and validates the Product scope before execution.
`/plugins explain OPERATION_ID` reads the existing A2 Package, A1 Management,
and Product handoff evidence by Package operation ID. It reports the joined
status and missing owner evidence as a partial read; it does not repair A2 or
claim that a new Session selected the result.

## Local Management SDK

The local Coding management SDK is separate from the Plugin author SDK. It
works on an already fenced workspace without starting a Session. Read and
command clients use the same Product owner projection:

```python
from loushang.coding.plugin_management_read_sdk import (
    open_coding_plugin_management_read_client,
)
from loushang.coding.plugin_management_command_sdk import (
    open_coding_plugin_management_command_client,
)

workspace = "/absolute/path/to/workspace"
read = open_coding_plugin_management_read_client(workspace)
management = read.management_snapshot(correlation_id="author:inspect")
preview = read.preview_current(correlation_id="author:preview")

commands = open_coding_plugin_management_command_client(workspace)
snapshot = commands.snapshot(
    correlation_id="author:before", plugin_ids=("reviewpack",)
)
result = commands.submit_desired(
    plugin_id="reviewpack",
    action="enable",
    expected_inventory_revision=snapshot["ownerRevisions"]["desiredState"],
    operation_id="author:enable:reviewpack:1",
    correlation_id="author:enable",
)
```

Use a new operation ID for a new command; reuse the same ID only to retry that
exact command. A stale Desired State revision requires a new snapshot and a
new decision. `commands.operation(operation_id, correlation_id=...)` observes
the durable result, and `commands.repair_own_desired_operation(...)` resumes
only a pending command issued by that SDK actor. The read client also exposes
`explain_operation(...)`. Neither client installs a Wheel or proves a new
Session consumed its Resource. Package A2 repair uses the separate Product
repair SDK.

## Skill Resource And Managed Action

```python
from hashlib import sha256

from loushang.plugin import (
    package, resource, skill_action, skill_action_effect, write_package_tree,
)

script = b"print('review')\n"
review = resource.skill(
    contribution_id="review-skill",
    locator="skills/review",
    actions=(
        skill_action(
            id="review",
            script="scripts/review.py",
            script_digest=sha256(script).hexdigest(),
            runtime="python",
            argv=("--check",),
            effects=(
                skill_action_effect(
                    kind="filesystem.read",
                    target="workspace",
                ),
            ),
        ),
    ),
)
generated = package(
    id="org.example.review",
    version="1.0.0",
    contributions=(review,),
)

validation = write_package_tree(
    "my-plugin",
    generated,
    content_files={
        "skills/review/SKILL.md": b"# Review\n",
        "skills/review/scripts/review.py": script,
    },
)
assert validation.valid, validation.diagnostics
```

`write_package_tree` requires a new destination, rejects escaping paths and
file collisions before writing, and returns inert validation diagnostics. It
does not make the generic package Product-compatible; use the Coding data wheel
recipe for that narrower installed artifact route.

`SKILL.md` remains the Resource identity; the generated `actions.json` is only
its managed-action sidecar. Environment literals have an author-enforced
non-secret precondition—validation does not classify arbitrary strings or
resolve secrets. Execution always requires Host Approval and required
containment. PLC8 managed execution is currently admitted only on Linux with
the Harness-owned Bubblewrap backend, immutable sealed-executable support, and
Bubblewrap's `--ro-bind-data` plus `--ro-bind-fd` features. A Linux host missing
those two managed-bind features may still use ordinary Sandbox execution, but
it cannot acquire managed-action start authority.
Managed actions are also available only from the exact graph-owned Resource
generation. That owner derives the immutable action facts and constructs the
canonical Skill consumer atomically; it accepts no caller-provided capture,
consumer, or transferable grant. Copying Catalog fields into another consumer
does not create action-owner authority, and no owner-construction capability is
part of the public author SDK.
Other hosts may compile, inspect, and validate the declaration, but execution
fails closed until they provide an equally strong owner-admitted mechanism.

## Validate Before Execution

```text
loushang-plugin validate ./my-plugin
```

Validation is safe for inspection: it does not import or execute Definition
code. To run developer conformance in the current same-trust process, use the
separate explicit command:

```text
loushang-plugin conformance ./my-plugin --approve-execution
```

The conformance command executes package Python. Use it only for code you
trust. It is not activation Approval, containment, or a substitute for the
runtime Plugin lifecycle.
