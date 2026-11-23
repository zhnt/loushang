import { invoke, isTauri } from "@tauri-apps/api/core";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";
import type { HarnessClientUiPort } from "./client/model";
import { listResources, readResource } from "./client/sessionResources";

export function AttachmentImage({ blob, label }: { blob: Blob; label: string }) {
  const { t } = useTranslation("session");
  const dialog = useRef<HTMLDialogElement>(null);
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);

  if (!url) return null;
  return <>
    <button type="button" className="attachment-thumb" aria-label={t("attachments.preview", { name: label })}
      onClick={() => dialog.current?.showModal()}>
      <img src={url} alt={label} width={64} height={64} />
    </button>
    <dialog ref={dialog} className="frame-dialog" aria-label={label}>
      <div className="settings-header">
        <h2>{label}</h2>
        <button type="button" className="icon-close" aria-label={t("attachments.close")}
          onClick={() => dialog.current?.close()}><UiIcon name="close" /></button>
      </div>
      <img className="attachment-preview" src={url} alt={label} />
    </dialog>
  </>;
}

export function AttachmentLabel({ label, folder, title = label }: { label: string; folder?: boolean; title?: string }) {
  return <span className="attachment-label" data-tooltip={title}>
    {folder ? <UiIcon name="folder" /> : null}
    <span>{label}</span>
  </span>;
}

export function AttachmentText(props: { blob: Blob; label: string }) {
  return isTauri() ? <DesktopTextAttachment {...props} /> : <WebTextAttachment {...props} />;
}

function DesktopTextAttachment({ blob, label }: { blob: Blob; label: string }) {
  const { t } = useTranslation("session");
  const [failed, setFailed] = useState(false);
  const [opening, setOpening] = useState(false);
  async function open() {
    setFailed(false);
    setOpening(true);
    try {
      const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await blob.arrayBuffer());
      await invoke("open_text_attachment", { name: label, text });
    } catch {
      setFailed(true);
    } finally {
      setOpening(false);
    }
  }
  return <>
    <button type="button" className="attachment-label" data-tooltip={label}
      aria-label={t("attachments.open", { name: label })} disabled={opening}
      onClick={() => { void open(); }}><span>{label}</span></button>
    {failed ? <span role="status">{t("attachments.openFailed")}</span> : null}
  </>;
}

function WebTextAttachment({ blob, label }: { blob: Blob; label: string }) {
  const { t } = useTranslation("session");
  const dialog = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState("");
  useEffect(() => {
    let active = true;
    void blob.slice(0, 64 * 1024).text().then((text) => {
      if (active) setPreview(text);
    });
    return () => { active = false; };
  }, [blob]);
  return <>
    <button type="button" className="attachment-label" data-tooltip={label}
      aria-label={t("attachments.preview", { name: label })} onClick={() => dialog.current?.showModal()}><span>{label}</span></button>
    <dialog ref={dialog} className="frame-dialog" aria-label={label}>
      <div className="settings-header">
        <h2>{label}</h2>
        <button type="button" className="icon-close" aria-label={t("attachments.close")}
          onClick={() => dialog.current?.close()}><UiIcon name="close" /></button>
      </div>
      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{preview}</pre>
    </dialog>
  </>;
}

type StoredProps = { client: HarnessClientUiPort; sessionId: string; id: string; allowRevoke?: boolean };
export function StoredResource({ client, sessionId, id, allowRevoke }: StoredProps) {
  const { t } = useTranslation("session");
  const [revoked, setRevoked] = useState(false);
  const [result, setResult] = useState<Awaited<ReturnType<typeof readResource>> | "unavailable" | null>(null);
  useEffect(() => {
    const cancellation = new AbortController();
    setResult(null);
    void readResource(client, sessionId, id, cancellation.signal).then(
      (value) => { if (!cancellation.signal.aborted) setResult(value); },
      () => { if (!cancellation.signal.aborted) setResult("unavailable"); },
    );
    return () => cancellation.abort();
  }, [client, sessionId, id]);
  if (result === "unavailable") return <span role="status">{t("attachments.unavailable")}</span>;
  if (!result) return null;
  if (!result.blob) return <span className="attachment-item">
    <AttachmentLabel label={result.resource.name ?? t("attachments.file")} folder={result.resource.kind === "directory"} />
    {allowRevoke && result.resource.source === "client_reference" && client.revokeClientDirectory && !revoked ? <button
      type="button" className="icon-button" data-tooltip={t("attachments.stopSharing")} aria-label={t("attachments.stopSharing")}
      onClick={() => { void client.revokeClientDirectory?.(id).then(() => setRevoked(true)).catch(() => {}); }}>
      <UiIcon name="close" />
    </button> : null}
    {revoked ? <span role="status">{t("attachments.sharingStopped")}</span> : null}
  </span>;
  return result.resource.mediaType === "text/plain"
    ? <AttachmentText blob={result.blob} label={result.resource.name ?? t("attachments.file")} />
    : <AttachmentImage blob={result.blob} label={t("attachments.image")} />;
}

export function SessionResources({ client, sessionId, version }: Omit<StoredProps, "id"> & { version: string }) {
  const { t } = useTranslation("session");
  const [open, setOpen] = useState(false);
  const [ids, setIds] = useState<readonly string[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setFailed(false);
    void listResources(client, sessionId).then(
      (resources) => {
        if (active) setIds(resources.map((item) => item.id));
      },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, [client, sessionId, version, open]);

  return <details className="project-navigation" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="section-label">{t("attachments.sessionResources")}</summary>
    {open ? <div className="attachment-list">
      {failed ? <span role="status">{t("attachments.unavailable")}</span>
        : ids?.length ? ids.map((id) => <StoredResource key={id} allowRevoke client={client} sessionId={sessionId} id={id} />)
        : ids ? <span>{t("attachments.empty")}</span> : null}
    </div> : null}
  </details>;
}
