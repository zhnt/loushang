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

The profile accepts one Prompt file, no executable code or dependencies. Theme,
Method, Asset, and Source declarations remain outside this Product profile.
