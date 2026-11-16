import type { DraftBinding } from "./model";

export const TEMPORARY_WORKSPACE = "@temporary";

export interface ProjectChat {
  readonly id: string;
  readonly title: string;
  readonly scope: string;
  readonly pinned: boolean;
}

export interface ProjectDirectory {
  readonly projects: readonly { path: string; sessions: readonly ProjectChat[] }[];
  readonly temporarySessions: readonly ProjectChat[];
}

export function workspaceCreationError(error: unknown) {
  const code = error instanceof Error ? error.message : error;
  switch (code) {
    case "invalid_request":
    case "not_found":
    case "already_exists":
    case "permission_denied":
    case "workspace_registration_failed":
    case "operation_unavailable":
      return code;
    default:
      return "unknown";
  }
}

export type WorkspaceCreationError = ReturnType<typeof workspaceCreationError> | "refresh_failed";

export interface ProjectNavigationProps {
  readonly directory: ProjectDirectory;
  readonly available: boolean;
  readonly pending: boolean;
  readonly error: boolean;
  readonly folderInput: boolean;
  readonly selection: { workspace: string; id: string } | null;
  readonly openFolder: () => void;
  readonly closeFolder: () => void;
  readonly hostKey: string;
  readonly createWorkspace: (path: string) => Promise<WorkspaceCreationError | null>;
  readonly register: (path: string) => Promise<boolean>;
  readonly create: (path: string | null) => void;
  readonly togglePin: (chat: ProjectChat) => void;
  readonly select: (workspace: string, id: string) => void;
}

export interface ManagedProjectNavigation extends Omit<ProjectNavigationProps, "create"> {
  readonly createChat: (path: string | null, continuityId: string, title: string) => Promise<DraftBinding | null>;
}
