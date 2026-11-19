# Build a GUI package with GitHub Actions

Open **Actions → Package GUI → Run workflow**. Select `main` as the workflow
branch, choose a package target, and enter the branch, tag, or commit to build
under `source_ref`. GitHub enables this entry after the workflow reaches the
default branch.

| Target | Build environment | Artifact contents |
| --- | --- | --- |
| `linux-amd64-deb` | Ubuntu 24.04 x64 | DEB and SHA-256 checksum |
| `windows-x64-nsis` | Windows Server 2022 x64 | NSIS EXE and SHA-256 checksum |
| `macos-x64-pkg` | macOS 15 Intel | PKG, SHA-256 checksum, and native dependency manifest |

Run the same workflow from a terminal:

```sh
gh workflow run gui-package.yml --repo zhnt/loushang --ref main \
  -f platform=linux-amd64-deb -f source_ref=lane/gui
gh run list --repo zhnt/loushang --workflow gui-package.yml
gh run download <run-id> --repo zhnt/loushang
```

The artifact name includes the package target and full source commit. Actions
retains it for 14 days. The Linux job checks extracted package contents and
command entry points. See the [macOS instructions](macos-package.md) for
installed acceptance, and [GUI build instructions](../../gui/README.md) for
local build and platform requirements.

To add a target, add a platform choice, its runner, and the platform-specific
build steps in [gui-package.yml](../../.github/workflows/gui-package.yml). Write
the package and its checksum to `dist/gui-package` so it uses the same artifact
upload. A future `linux-x64-rpm` target needs a supported RPM distribution and
packaging recipe. A future `macos-arm64-pkg` target needs an arm64 runtime,
native dependency checks, and an arm64 package recipe.
