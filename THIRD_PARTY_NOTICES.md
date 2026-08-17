# Third-Party Notices

This file lists the direct runtime dependencies declared by this project's
`pyproject.toml`. It is an index for source distribution review, not a complete
notice bundle for packaged binaries or container images.

## Direct Runtime Dependencies

| Package | Version | License | Notice source |
|---|---:|---|---|
| `anthropic` | 0.89.0 | MIT | Package metadata |
| `authlib` | 1.7.2 | BSD-3-Clause | Package metadata; ships `LICENSE` |
| `httpx` | 0.28.1 | BSD-3-Clause | Package metadata |
| `markdown-it-py` | 4.2.0 | MIT | Package metadata; ships `LICENSE` and `LICENSE.markdown-it` |
| `openai` | 2.30.0 | Apache-2.0 | Package metadata |
| `pillow` | 12.2.0 | MIT-CMU | Package metadata; ships `LICENSE` with bundled component notices |
| `pygments` | 2.20.0 | BSD-2-Clause | Package metadata; ships `LICENSE` and `AUTHORS` |
| `wcwidth` | 0.8.2 | MIT | Package metadata; ships `LICENSE` |

## Distribution Guidance

For any bundled distribution artifact, regenerate third-party notices from the
resolved environment and include transitive dependencies and package-provided
license files. In an installed Python environment, those files are exposed
through package metadata such as `License-File` and are commonly installed under
each package's `.dist-info/licenses/` directory.

This project itself is licensed under Apache-2.0; see [LICENSE](LICENSE).
