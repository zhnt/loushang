"""Language-extensible semantic code intelligence for the Coding product."""

from loushang.coding.lsp.binding import CodingLspBinding
from loushang.coding.lsp.catalog import LspCatalog
from loushang.coding.lsp.client import LspClient
from loushang.coding.lsp.discovery import (
    LspAdmissionRecord,
    LspCatalogSnapshot,
    coding_lsp_config_paths,
    default_global_lsp_config_path,
    default_lsp_environment,
    default_project_lsp_config_path,
    discover_lsp_catalog,
    product_default_lsp_definitions,
)
from loushang.coding.lsp.documents import DocumentSnapshot, LspDocumentManager
from loushang.coding.lsp.model import (
    CodeDiagnostic,
    CodeHover,
    CodeLocation,
    CodePosition,
    CodeQueryResult,
    CodeRange,
    CodeSymbol,
    DocumentOutlineResult,
    LspError,
    LspInvalidInputError,
    LspProtocolError,
    LspServerDefinition,
    LspServerKey,
    LspServerSelection,
    LspUnavailableError,
)
from loushang.coding.lsp.ports import (
    AuthorizedProcessLauncher,
    ProcessExit,
    ProcessHandle,
    ProcessLaunchRequest,
    ProcessStderrTail,
)
from loushang.coding.lsp.runtime import (
    CodingLspRuntime,
    DeferredCodingLspRuntime,
    ProcessLauncherBinder,
    bind_coding_lsp_runtime,
)
from loushang.coding.lsp.selector import LspSelector
from loushang.coding.lsp.status import (
    LspServerRuntimeState,
    LspServerRuntimeStatus,
    LspSessionStatus,
    disabled_lsp_session_status,
)
from loushang.coding.lsp.supervisor import LspRuntimeHandle, LspServerSupervisor
from loushang.coding.lsp.tool_pack import (
    CODING_LSP_TOOL_PACK,
    register_coding_lsp_tools,
)
from loushang.coding.lsp.tools import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
    MAX_DOCUMENT_OUTLINE_DEPTH,
    MAX_DOCUMENT_OUTLINE_RESULTS,
    MAX_HOVER_CONTENT_CHARACTERS,
    MAX_INSPECT_SYMBOL_RESULTS,
    CodingLspTools,
    create_document_outline_tool_definition,
    create_inspect_symbol_tool_definition,
)

__all__ = [
    "AuthorizedProcessLauncher",
    "CodeDiagnostic",
    "CodeHover",
    "CodeLocation",
    "CodePosition",
    "CodeQueryResult",
    "CodeRange",
    "CodeSymbol",
    "CodingLspBinding",
    "CodingLspRuntime",
    "CodingLspTools",
    "CODING_LSP_TOOL_PACK",
    "DeferredCodingLspRuntime",
    "DOCUMENT_OUTLINE_TOOL_NAME",
    "DocumentOutlineResult",
    "DocumentSnapshot",
    "INSPECT_SYMBOL_TOOL_NAME",
    "LspCatalog",
    "LspCatalogSnapshot",
    "LspAdmissionRecord",
    "LspClient",
    "LspDocumentManager",
    "LspError",
    "LspInvalidInputError",
    "LspProtocolError",
    "LspRuntimeHandle",
    "LspSelector",
    "LspServerDefinition",
    "LspServerKey",
    "LspServerSelection",
    "LspServerSupervisor",
    "LspServerRuntimeState",
    "LspServerRuntimeStatus",
    "LspSessionStatus",
    "LspUnavailableError",
    "MAX_INSPECT_SYMBOL_RESULTS",
    "MAX_HOVER_CONTENT_CHARACTERS",
    "MAX_DOCUMENT_OUTLINE_DEPTH",
    "MAX_DOCUMENT_OUTLINE_RESULTS",
    "ProcessExit",
    "ProcessHandle",
    "ProcessLauncherBinder",
    "ProcessLaunchRequest",
    "ProcessStderrTail",
    "bind_coding_lsp_runtime",
    "coding_lsp_config_paths",
    "create_document_outline_tool_definition",
    "create_inspect_symbol_tool_definition",
    "default_global_lsp_config_path",
    "default_lsp_environment",
    "default_project_lsp_config_path",
    "disabled_lsp_session_status",
    "discover_lsp_catalog",
    "product_default_lsp_definitions",
    "register_coding_lsp_tools",
]
