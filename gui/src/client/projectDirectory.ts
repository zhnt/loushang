import type { DraftBinding, SessionModels } from "./model";

export const TEMPORARY_WORKSPACE = "@temporary";

export function workspaceName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

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
  readonly create: (path: string | null) => void;
  readonly deleteChat?: (path: string, chat: ProjectChat) => Promise<boolean>;
  readonly togglePin: (chat: ProjectChat) => void;
  readonly select: (workspace: string, id: string) => void;
}

export interface ManagedProjectNavigation extends Omit<ProjectNavigationProps, "create"> {
  readonly inspectWorkspace?: (path: string, fingerprint: string, sessionId?: string) => Promise<import("../WorkspaceInspection").Inspection>;
  readonly openProjectPath?: (path: string, fingerprint: string, file?: string) => Promise<void>;
  readonly draftModels?: (path: string | null) => Promise<SessionModels>;
  readonly createChat: (path: string | null, continuityId: string, title: string) => Promise<DraftBinding | null>;
}
