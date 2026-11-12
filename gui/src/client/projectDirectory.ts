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

export interface ProjectNavigationProps {
  readonly directory: ProjectDirectory;
  readonly available: boolean;
  readonly pending: boolean;
  readonly error: boolean;
  readonly folderInput: boolean;
  readonly selection: { workspace: string; id: string } | null;
  readonly openFolder: () => void;
  readonly closeFolder: () => void;
  readonly register: (path: string) => Promise<boolean>;
  readonly create: (path: string | null) => void;
  readonly togglePin: (chat: ProjectChat) => void;
  readonly select: (workspace: string, id: string) => void;
}
