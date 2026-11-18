export type WorkspacePreview =
  | { readonly kind: "file"; readonly path: string; readonly text: string }
  | {
      readonly kind: "directory";
      readonly path: string;
      readonly entries: readonly { readonly name: string; readonly kind: "directory" | "file" }[];
      readonly limited: boolean;
    };

export interface WorkspacePreviewScope {
  readonly sessionId: string;
  readonly connectionEpoch: string;
  readonly serviceInstanceId: string;
}

export interface WorkspacePreviewRequest extends WorkspacePreviewScope {
  readonly reference: string;
  readonly base: string;
}

export type ReadWorkspacePreview = (request: WorkspacePreviewRequest) => Promise<WorkspacePreview>;
