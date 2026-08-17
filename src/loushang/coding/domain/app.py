"""Coding profile bound to the shared Method domain runtime."""

from __future__ import annotations

from pathlib import Path

from loushang.method import (
    MethodCompiler,
    MethodDomainProfile,
    MethodDomainRuntime,
    MethodLoader,
    MethodProjector,
)

DEFAULT_GUIDANCE_TEMPLATE = "{guidance}\n\nUser request:\n\n{user_input}"

CODING_METHOD_DOMAIN_PROFILE = MethodDomainProfile(
    domain="coding",
    guidance_template=DEFAULT_GUIDANCE_TEMPLATE,
)


class CodingDomainApp(MethodDomainRuntime):
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        method_loader: MethodLoader | None = None,
        method_compiler: MethodCompiler | None = None,
        method_projector: MethodProjector | None = None,
    ) -> None:
        super().__init__(
            profile=CODING_METHOD_DOMAIN_PROFILE,
            cwd=cwd,
            method_loader=method_loader,
            method_compiler=method_compiler,
            method_projector=method_projector,
        )


__all__ = [
    "CODING_METHOD_DOMAIN_PROFILE",
    "CodingDomainApp",
    "DEFAULT_GUIDANCE_TEMPLATE",
]
