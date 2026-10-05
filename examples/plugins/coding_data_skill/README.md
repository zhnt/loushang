# Coding data Skill Plugin

This example has one document-only Skill and no Python code or managed actions.
It uses Coding's **explicit, already cut over Product** path. Run it in a fresh
workspace with an installed Loushang CLI; do not run Product cutover on an
existing workspace merely to try the example.

From the Loushang repository root, set paths for the example and an empty
workspace you own:

```sh
example_dir="$(pwd)/examples/plugins/coding_data_skill"
workspace_dir="/absolute/path/to/fresh-workspace"
mkdir -m 700 "$workspace_dir"
loushang-package-cutover --workspace "$workspace_dir"
loushang-plugin build-coding-skill \
  "$example_dir/v1/skills/review/SKILL.md" \
  --plugin-id reviewpack --version 1 \
  --output-dir "$workspace_dir/dist"
cd "$workspace_dir"
loushang --install-package "$workspace_dir/dist/reviewpack-1-py3-none-any.whl" \
  --package-scope project
loushang --list-plugins --list-plugins-format json
loushang --enable-plugin reviewpack
loushang --list-skills --list-skills-format json
```

The first list should show `reviewpack` as `installed_disabled`; after enable,
the Skill list should show `review`. Start a **new** Coding Session and invoke
`/skill:review` to load its document. With a configured model, `loushang -p
"/skill:review Review this change"` enters the normal Model Input path. A
successful install or Skill list alone does not prove that the text reached a
model. The Product regression
`tests/coding/test_package_external_data_wheel.py::test_external_data_skill_enters_fenced_session_catalog`
checks the captured Catalog Skill, exact document load, revision pin, and new
Session behavior using a scripted model.

Build an updated wheel from the v2 document, then observe that an existing
Session keeps its v1 revision while a new Session uses v2:

```sh
loushang-plugin build-coding-skill \
  "$example_dir/v2/skills/review/SKILL.md" \
  --plugin-id reviewpack --version 2 \
  --output-dir "$workspace_dir/dist"
loushang --update-package "$workspace_dir/dist/reviewpack-2-py3-none-any.whl" \
  --package-scope project
loushang --list-plugins --list-plugins-format json
loushang --disable-plugin reviewpack
loushang --uninstall-package reviewpack --package-scope project
loushang --list-plugins --list-plugins-format json
```

The final list should show `desiredState: absent`. Uninstall, retirement, and
private-data deletion are distinct operations. This example does not enable
Prompt, Theme, Method, Asset, Source, or executable Plugin contributions.
