import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useContextMenu } from "./ContextMenu";
import { AttachmentImage, AttachmentLabel, AttachmentText } from "./SessionResources";
import { workspaceName } from "./client/projectDirectory";
import { UiIcon } from "./UiIcon";
import { attachmentTypes, maxAttachments, supportedAttachment, supportedImage, type AttachmentDraft, type DirectoryPicker } from "./client/sessionResources";

interface ComposerProps {
  readonly hostReferences?: boolean;
  readonly attachmentScope?: string;
  readonly pickClientDirectory?: DirectoryPicker;
  readonly revokeClientDirectory?: (id: string) => Promise<boolean>;
  readonly images?: readonly AttachmentDraft[];
  readonly onImagesChange?: (images: readonly AttachmentDraft[]) => void;
  readonly title: string;
  readonly text: string;
  readonly onChange: (text: string) => void;
  readonly onSubmit: () => void;
  readonly onInterrupt?: () => void;
  readonly disabled?: boolean;
  readonly submitLabel?: string;
  readonly buttonDisabled: boolean;
  readonly fixture?: boolean;
  readonly goalAction?: { label: string; run: () => void };
  readonly model?: ReactNode;
  readonly notice?: ReactNode;
}

function resizeEditor(input: HTMLTextAreaElement) {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

export function MessageComposer({ title, text, onChange, onSubmit, onInterrupt, disabled,
  buttonDisabled, fixture, goalAction, model, notice, submitLabel, images = [], onImagesChange, hostReferences, attachmentScope, pickClientDirectory, revokeClientDirectory }: ComposerProps) {
  const { t } = useTranslation("session");
  const editor = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const menu = useContextMenu();
  const hostPathDialog = useRef<HTMLDialogElement>(null);
  const [hostPath, setHostPath] = useState("");
  const chooser = useRef<HTMLInputElement>(null);
  const [attachmentError, setAttachmentError] = useState(false);
  const canAttach = Boolean(onImagesChange && !disabled);
  const hasActions = canAttach || Boolean(goalAction);
  const [clientDirectoryError, setClientDirectoryError] = useState(false);
  const picking = useRef(false);
  const attachmentTarget = useRef({ scope: attachmentScope, images, change: onImagesChange, enabled: canAttach });
  useLayoutEffect(() => {
    attachmentTarget.current = { scope: attachmentScope, images, change: onImagesChange, enabled: canAttach };
  }, [attachmentScope, images, onImagesChange, canAttach]);
  useLayoutEffect(() => {
    if (hostPathDialog.current?.open) hostPathDialog.current.close();
    setClientDirectoryError(false);
  }, [attachmentScope]);
  useLayoutEffect(() => () => {
    attachmentTarget.current.enabled = false;
  }, []);
  async function attachClientDirectory() {
    if (!pickClientDirectory || picking.current) return;
    const scope = attachmentScope;
    picking.current = true;
    setClientDirectoryError(false);
    try {
      const grant = await pickClientDirectory({
        title: t("attachments.shareDirectory"), accept: t("attachments.shareReadOnly"), cancel: t("attachments.cancel"),
      });
      if (!grant) return;
      const target = attachmentTarget.current;
      const full = target.images.length >= maxAttachments;
      if (target.scope === scope && target.enabled && !full) {
        target.change?.([...target.images, grant]);
      } else {
        void revokeClientDirectory?.(grant.grantId).catch(() => {});
        if (target.scope === scope) setAttachmentError(full);
      }
    } catch {
      if (attachmentTarget.current.scope === scope) setClientDirectoryError(true);
    } finally {
      picking.current = false;
    }
  }
  function addImages(files: readonly File[]) {
    if (!canAttach || !files.length) return;
    const valid = files.filter(supportedAttachment);
    const next = [...images, ...valid];
    setAttachmentError(valid.length !== files.length || next.length > maxAttachments);
    onImagesChange?.(next.slice(0, maxAttachments));
  }
  useLayoutEffect(() => {
    const input = editor.current;
    if (input) resizeEditor(input);
  }, [text]);
  useLayoutEffect(() => {
    const input = editor.current;
    const composer = input?.parentElement;
    if (!input || !composer || typeof ResizeObserver === "undefined") return;
    let width: number | undefined;
    let frame: number | undefined;
    const observer = new ResizeObserver(([entry]) => {
      const nextWidth = entry?.contentRect.width;
      // The editor changes the composer's height. Only width can rewrap the draft.
      if (nextWidth === undefined || nextWidth === width) return;
      width = nextWidth;
      if (frame !== undefined) return;
      // Set height outside observer delivery so reflow cannot feed back in this frame.
      frame = requestAnimationFrame(() => {
        frame = undefined;
        resizeEditor(input);
      });
    });
    observer.observe(composer);
    return () => {
      observer.disconnect();
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, []);
  return (<>
    <form className="composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}
      onDragOver={(event) => {
        if (canAttach && event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDrop={(event) => {
        if (!canAttach || !event.dataTransfer.files.length) return;
        event.preventDefault();
        addImages([...event.dataTransfer.files]);
      }}>
      {images.length ? <div className="attachment-list">
        {images.map((file, index) => {
          const image = !("grantId" in file) && !("hostPath" in file) && supportedImage(file);
          const name = "hostPath" in file ? workspaceName(file.hostPath) : file.name;
          const key = "grantId" in file ? file.grantId : "hostPath" in file ? file.hostPath : name;
          return <div className={image ? undefined : "attachment-item"} key={JSON.stringify([key, index])}>
            {"grantId" in file ? <AttachmentLabel label={file.name} folder />
              : "hostPath" in file ? <AttachmentLabel label={name} title={file.hostPath} />
              : image ? <AttachmentImage blob={file} label={name || t("attachments.image")} />
              : <AttachmentText blob={file} label={name || t("attachments.file")} />}
            <button type="button" className="icon-button" disabled={!canAttach}
              aria-label={t("attachments.remove", { name: name || t(image ? "attachments.image" : "attachments.file") })}
              onClick={() => {
                setAttachmentError(false);
                if ("grantId" in file) void revokeClientDirectory?.(file.grantId).catch(() => {});
                onImagesChange?.(images.filter((_, i) => i !== index));
              }}>
              <UiIcon name="close" />
            </button>
          </div>;
        })}
      </div> : null}
      {attachmentError && onImagesChange ? <p role="alert">{t("attachments.invalid")}</p> : null}
      {clientDirectoryError ? <p role="alert">{t("attachments.unavailable")}</p> : null}
      <label className="visually-hidden" htmlFor="message-input">{t("composer.messageFor", { title })}</label>
      <textarea ref={editor} id="message-input" disabled={disabled} aria-describedby="message-keyboard-hint" rows={2}
        value={text} placeholder={t(fixture ? "composer.fixturePlaceholder" : "composer.livePlaceholder")}
        onChange={(event) => onChange(event.currentTarget.value)}
        onPaste={(event) => {
          const files = [...event.clipboardData.files];
          if (!canAttach || !files.length) return;
          event.preventDefault();
          addImages(files);
        }}
        onCompositionStart={() => { composing.current = true; }}
        onCompositionEnd={() => { composing.current = false; }}
        onBlur={() => { composing.current = false; }}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
          if (event.ctrlKey && !event.altKey && !event.metaKey) {
            event.preventDefault();
            const input = event.currentTarget;
            input.setRangeText("\n", input.selectionStart, input.selectionEnd, "end");
            onChange(input.value);
          } else if (!event.shiftKey && !event.altKey && !event.metaKey) {
            event.preventDefault();
            if (!event.repeat && !buttonDisabled && !onInterrupt) onSubmit();
          }
        }} />
      <span id="message-keyboard-hint" className="visually-hidden">{t("composer.keyboardHint")}</span>
      <div className="composer-actions">
        <div className="composer-permissions">
          {onImagesChange ? <input hidden ref={chooser} type="file" accept={attachmentTypes.join(",")} multiple
            onChange={(event) => {
              addImages([...(event.currentTarget.files ?? [])]);
              event.currentTarget.value = "";
            }} /> : null}
          <button type="button" className="icon-button" aria-label={t(hasActions ? "attachments.actions" : "composer.attachUnavailable")}
            title={t(hasActions ? "attachments.actions" : "composer.attachHint")} aria-haspopup="menu" disabled={!hasActions}
            onClick={(event) => menu(event, [
              ...(canAttach ? [
                { label: t("attachments.addFile"), run: () => chooser.current?.click() },
                ...(pickClientDirectory ? [{ label: t("attachments.addFolder"), run: attachClientDirectory }] : []),
                ...(hostReferences ? [{ label: t("attachments.referenceHostPath"), run: () => hostPathDialog.current?.showModal() }] : []),
              ] : []),
              ...(goalAction ? [goalAction] : []),
            ])}>＋</button>
          {fixture ? <span className="permission-label">◉ {t("composer.fixtureAccess")}</span> : null}
        </div>
        {notice}
        {model ?? <span />}
        <button className="composer-submit" type={onInterrupt ? "button" : "submit"}
          aria-label={submitLabel ?? t(onInterrupt ? "composer.interrupt" : "composer.send")}
          title={submitLabel ?? t(onInterrupt ? "composer.stopHint" : "composer.sendHint")}
          disabled={buttonDisabled} onClick={onInterrupt}>
          {onInterrupt ? <svg aria-hidden="true" viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor" /></svg>
            : <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 18V6m-5 5 5-5 5 5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>}
        </button>
      </div>
    </form>
    {hostReferences ? <dialog ref={hostPathDialog} className="frame-dialog" aria-label={t("attachments.referenceHostPath")}>
      <div className="settings-header">
        <h2>{t("attachments.referenceHostPath")}</h2>
        <button type="button" className="icon-close" aria-label={t("attachments.close")}
          onClick={() => hostPathDialog.current?.close()}><UiIcon name="close" /></button>
      </div>
      <form className="local-host-card" onSubmit={(event) => {
        event.preventDefault();
        const value = hostPath.trim();
        if (!value || !canAttach) return;
        const full = images.length >= maxAttachments;
        setAttachmentError(full);
        if (!full) onImagesChange?.([...images, { hostPath: value }]);
        setHostPath("");
        hostPathDialog.current?.close();
      }}>
        <label>{t("attachments.hostPath")}<input required maxLength={4096} value={hostPath}
          onChange={(event) => setHostPath(event.currentTarget.value)} /></label>
        <div className="local-host-actions"><button disabled={!hostPath.trim()}>{t("attachments.reference")}</button></div>
      </form>
    </dialog> : null}
  </>);
}
