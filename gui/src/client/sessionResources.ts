import type { ResourceRefV1, ResourceV1, SessionResourceQueryV1, SessionResourceResultV1 } from "../../contracts/generated/bridge";
import type { HarnessClientUiPort } from "./model";

export type HostPathDraft = { readonly hostPath: string };
export type AttachmentDraft = File | HostPathDraft;

export const imageTypes = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const imageLimit = 4 * 1024 * 1024;
const textLimit = 1024 * 1024;
const textExtensions = [
  ".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
  ".xml", ".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".rs", ".go",
  ".c", ".h", ".cpp", ".java", ".sh", ".sql", ".log", ".ini", ".conf",
];
export const attachmentTypes = [...imageTypes, "text/plain", ...textExtensions];
const chunkSize = 192 * 1024;
export const maxAttachments = 4;

export function supportedImage(file: File) {
  return imageTypes.includes(file.type) && file.size > 0 && file.size <= imageLimit;
}

export function supportedAttachment(file: File) {
  if (supportedImage(file)) return true;
  return file.size > 0 && file.size <= textLimit
    && (file.type === "text/plain" || textExtensions.some((ext) => file.name.toLowerCase().endsWith(ext)));
}

export function resourceResult(value: SessionResourceResultV1 & { error?: string }) {
  if (value.error) throw new Error(value.error);
  if (!Array.isArray(value.resources) || value.resources.length > 256 || typeof value.data !== "string"
    || value.data.length > chunkSize / 3 * 4) throw new Error("resource_unavailable");
  return value;
}

function query(action: SessionResourceQueryV1["action"], fields: Partial<SessionResourceQueryV1> = {}): SessionResourceQueryV1 {
  return { action, resourceId: null, mediaType: "", offset: 0, totalBytes: 0, data: "", ...fields };
}

function encode(bytes: Uint8Array) {
  let ascii = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    ascii += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(ascii);
}

export async function uploadAttachments(client: HarnessClientUiPort, sessionId: string, files: readonly AttachmentDraft[]): Promise<ResourceRefV1[]> {
  const refs: ResourceRefV1[] = [];
  if (!files.length) return refs;
  if (!client.sessionResource || files.length > maxAttachments) throw new Error("resource_unavailable");
  for (const file of files) {
    if ("hostPath" in file) {
      const result = await client.sessionResource(sessionId, query("reference", { path: file.hostPath }));
      const resource = result.resources[0];
      if (!resource || resource.source !== "host_reference" || !/^[a-f0-9]{64}$/.test(resource.id)) {
        throw new Error("resource_unavailable");
      }
      if (!refs.some((ref) => ref.id === resource.id)) refs.push({ id: resource.id, sha256: resource.id });
      continue;
    }
    if (!supportedAttachment(file)) throw new Error("resource_unavailable");
    const image = supportedImage(file);
    const bytes = await file.arrayBuffer();
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    const id = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (refs.some((ref) => ref.id === id)) continue;
    for (let offset = 0; offset < bytes.byteLength; offset += chunkSize) {
      const result = await client.sessionResource(sessionId, query("upload", {
        resourceId: id, offset, totalBytes: bytes.byteLength, mediaType: image ? file.type : "text/plain",
        ...(image ? {} : { name: file.name }),
        data: encode(new Uint8Array(bytes, offset, Math.min(chunkSize, bytes.byteLength - offset))),
      }));
      if (result.resources.some((item) => item.id === id && item.sizeBytes === bytes.byteLength)) {
        refs.push({ id, sha256: id });
        break;
      }
    }
    if (!refs.some((ref) => ref.id === id)) throw new Error("resource_unavailable");
  }
  return refs;
}

export async function listResources(client: HarnessClientUiPort, sessionId: string): Promise<readonly ResourceV1[]> {
  const result = await client.sessionResource?.(sessionId, query("list"));
  return result?.resources ?? [];
}

export async function readResource(client: HarnessClientUiPort, sessionId: string, id: string, signal: AbortSignal): Promise<{ blob: Blob | null; resource: ResourceV1 }> {
  if (!client.sessionResource) throw new Error("resource_unavailable");
  const parts: Uint8Array<ArrayBuffer>[] = [];
  let resource: ResourceV1 | undefined;
  let offset = 0;
  do {
    signal.throwIfAborted();
    const reply = await client.sessionResource(sessionId, query("read", { resourceId: id, offset }));
    const item = reply.resources[0];
    if (item?.id === id && item.source === "host_reference" && offset === 0 && reply.data === "") {
      return { blob: null, resource: item };
    }
    if (!item || item.id !== id || item.kind !== "file" || item.source !== "managed"
      || (!imageTypes.includes(item.mediaType) && item.mediaType !== "text/plain")
      || !Number.isInteger(item.sizeBytes)
      || item.sizeBytes > (item.mediaType === "text/plain" ? textLimit : imageLimit) || item.sizeBytes <= offset
      || (resource && (item.mediaType !== resource.mediaType || item.sizeBytes !== resource.sizeBytes))) {
      throw new Error("resource_unavailable");
    }
    resource = item;
    const bytes = Uint8Array.from(atob(reply.data), (letter) => letter.charCodeAt(0));
    if (!bytes.length || bytes.length > chunkSize || offset + bytes.length > item.sizeBytes) throw new Error("resource_unavailable");
    parts.push(bytes);
    offset += bytes.length;
  } while (offset < resource.sizeBytes);
  return { blob: new Blob(parts, { type: resource.mediaType }), resource };
}
