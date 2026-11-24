import type { DraftBinding, HarnessClientUiPort, SessionModels } from "./model";

export const TEMPORARY_WORKSPACE = "@temporary";

export function workspaceName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

export interface ProjectChat {
  readonly id: string;
  readonly continuityId?: string;
  readonly title: string;
  readonly scope: string;
  readonly pinned: boolean;
}

export interface WorkspacePath {
  readonly id: string;
  readonly alias: string;
  readonly path: string;
  readonly status: "available" | "missing" | "unsafe" | "not_directory" | "permission_denied";
}

export interface ProjectEntry {
  readonly id?: string;
  readonly name?: string;
  readonly path: string | null;
  readonly paths?: readonly WorkspacePath[];
  readonly defaultPathId?: string | null;
  readonly sessions: readonly ProjectChat[];
}

export function projectKey(project: ProjectEntry): string {
  return project.id ?? project.path ?? "";
}

export type WorkspaceEdit =
  | { action: "create-workspace"; name: string }
  | { action: "rename-workspace"; workspaceId: string; name: string }
  | { action: "delete-workspace-with-history"; workspaceId: string }
  | { action: "add-path" | "update-path"; workspaceId: string; pathId?: string; alias: string; path: string }
  | { action: "remove-path" | "set-default-path"; workspaceId: string; pathId?: string };

export interface ProjectDirectory {
  readonly projects: readonly ProjectEntry[];
  readonly temporarySessions: readonly ProjectChat[];
}

export interface ProjectNavigationProps {
  readonly directory: ProjectDirectory;
  readonly available: boolean;
  readonly pending: boolean;
  readonly error: boolean;
  readonly folderInput: boolean;
  readonly selection: { workspace: string; id?: string } | null;
  readonly openFolder: () => void;
  readonly closeFolder: () => void;
  readonly hostKey: string;
  readonly register: (path: string) => Promise<boolean>;
  readonly editWorkspace?: (edit: WorkspaceEdit) => Promise<void>;
  readonly create: (path: string | null) => void;
  readonly createDisabled?: boolean;
  readonly deleteChat?: (path: string, chat: ProjectChat) => Promise<boolean>;
  readonly togglePin: (chat: ProjectChat) => void;
  readonly select: (workspace: string, id: string) => void;
}

export interface ManagedProjectNavigation extends Omit<ProjectNavigationProps, "create" | "createDisabled"> {
  readonly inspectWorkspace?: (path: string, fingerprint: string, sessionId?: string) => Promise<import("../WorkspaceInspection").Inspection>;
  readonly openProjectPath?: (path: string, fingerprint: string, file?: string) => Promise<{ fileMissing: boolean }>;
  readonly clientDirectories?: Pick<HarnessClientUiPort, "pickClientDirectory" | "revokeClientDirectory">;
  readonly draftModels?: (path: string | null, modelId?: string) => Promise<SessionModels>;
  readonly createChat: (path: string | null, continuityId: string, title: string) => Promise<DraftBinding | null>;
}
