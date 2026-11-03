# Coding Data Prompt Example

This example packages one Markdown Prompt as a data-only wheel for the current
POSIX fenced Coding Product path. The Product captures and validates the wheel
when it is installed; building the wheel alone does not select the Prompt.

From the repository root, choose a fresh workspace and build the wheel:

```sh
example_dir="$(pwd)/examples/plugins/coding_data_prompt"
workspace_dir="/absolute/path/to/fresh-workspace"
mkdir -m 700 "$workspace_dir"
loushang-package-cutover --workspace "$workspace_dir"
loushang-plugin build-coding-prompt \
  "$example_dir/prompts/review.md" \
  --plugin-id promptpack --version 1 --output-dir "$workspace_dir/dist"
loushang-plugin validate-coding-wheel \
  "$workspace_dir/dist/promptpack-1-py3-none-any.whl"
loushang-coding-plugin-smoke \
  "$workspace_dir/dist/promptpack-1-py3-none-any.whl" \
  --kind prompt --plugin-id promptpack --resource-name review
```

Only run cutover on a fresh workspace that you own. Install and enable the
generated wheel from that workspace:

```sh
cd "$workspace_dir"
loushang --install-package "$workspace_dir/dist/promptpack-1-py3-none-any.whl" --package-scope project
loushang --enable-plugin promptpack
loushang --list-plugins --list-plugins-format json
```

Start a new Coding Session in the same workspace and submit `/review` followed
by the change to inspect. The selected Prompt is expanded before the model
call. The persisted Model Input snapshot is the evidence that the expanded
text reached that call; installed or enabled status alone does not prove it.

Build and validate an updated Prompt, then start a new Session after the
update. An existing Session retains its pinned v1 Resource:

```sh
loushang-plugin build-coding-prompt \
  "$example_dir/v2/prompts/review.md" \
  --plugin-id promptpack --version 2 --prompt-name review \
  --output-dir "$workspace_dir/dist"
loushang-plugin validate-coding-wheel \
  "$workspace_dir/dist/promptpack-2-py3-none-any.whl"
loushang --update-package "$workspace_dir/dist/promptpack-2-py3-none-any.whl" \
  --package-scope project
loushang --disable-plugin promptpack
loushang --uninstall-package promptpack --package-scope project
loushang --list-plugins --list-plugins-format json
# After closing all Coding Sessions:
loushang-package-gc --workspace "$workspace_dir" prepare
loushang-package-gc --workspace "$workspace_dir" list
```

The profile accepts one Prompt file, no executable code or dependencies. Theme,
Method, Asset, and Source declarations remain outside this Product profile.
Wheel validation reports `productAdmission: not_checked`; it does not replace
the target install. The build JSON prints `validationCommand` and
`targetInstallCommand`. After install, its A2 operation ID can be inspected
with `loushang --explain-plugin-operation <operation-id>` if a handoff is
incomplete. If uninstall stops after `desired_absent`, inspect its A1 operation
ID and run the printed actor-owned repair command before checking retirement.
