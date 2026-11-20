import type { ResourceRefV1, ResourceV1, SessionResourceQueryV1, SessionResourceResultV1 } from "../../contracts/generated/bridge";
import type { HarnessClientUiPort } from "./model";

export const imageTypes = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const imageLimit = 4 * 1024 * 1024;
const chunkSize = 192 * 1024;
export const maxAttachments = 4;

export function supportedImage(file: File) {
  return imageTypes.includes(file.type) && file.size > 0 && file.size <= imageLimit;
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

export async function uploadImages(client: HarnessClientUiPort, sessionId: string, files: readonly File[]): Promise<ResourceRefV1[]> {
  const refs: ResourceRefV1[] = [];
  if (!files.length) return refs;
  if (!client.sessionResource || files.length > maxAttachments) throw new Error("resource_unavailable");
  for (const file of files) {
    if (!supportedImage(file)) throw new Error("resource_unavailable");
    const bytes = await file.arrayBuffer();
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    const id = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (refs.some((ref) => ref.id === id)) continue;
    for (let offset = 0; offset < bytes.byteLength; offset += chunkSize) {
      const result = await client.sessionResource(sessionId, query("upload", {
        resourceId: id, offset, totalBytes: bytes.byteLength, mediaType: file.type,
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

export async function listImages(client: HarnessClientUiPort, sessionId: string): Promise<readonly ResourceV1[]> {
  const result = await client.sessionResource?.(sessionId, query("list"));
  return result?.resources ?? [];
}

export async function readImage(client: HarnessClientUiPort, sessionId: string, id: string, signal: AbortSignal): Promise<Blob> {
  if (!client.sessionResource) throw new Error("resource_unavailable");
  const parts: Uint8Array<ArrayBuffer>[] = [];
  let resource: ResourceV1 | undefined;
  let offset = 0;
  do {
    signal.throwIfAborted();
    const reply = await client.sessionResource(sessionId, query("read", { resourceId: id, offset }));
    const item = reply.resources[0];
    if (!item || item.id !== id || item.kind !== "file" || item.source !== "managed" || !imageTypes.includes(item.mediaType)
      || !Number.isInteger(item.sizeBytes) || item.sizeBytes > imageLimit || item.sizeBytes <= offset
      || (resource && (item.mediaType !== resource.mediaType || item.sizeBytes !== resource.sizeBytes))) {
      throw new Error("resource_unavailable");
    }
    resource = item;
    const bytes = Uint8Array.from(atob(reply.data), (letter) => letter.charCodeAt(0));
    if (!bytes.length || bytes.length > chunkSize || offset + bytes.length > item.sizeBytes) throw new Error("resource_unavailable");
    parts.push(bytes);
    offset += bytes.length;
  } while (offset < resource.sizeBytes);
  return new Blob(parts, { type: resource.mediaType });
}
