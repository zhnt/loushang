import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AttachmentImage } from "./SessionImages";
import { UiIcon } from "./UiIcon";
import { imageTypes, maxAttachments, supportedImage } from "./client/sessionResources";

interface ComposerProps {
  readonly images?: readonly File[];
  readonly onImagesChange?: (images: readonly File[]) => void;
  readonly title: string;
  readonly text: string;
  readonly onChange: (text: string) => void;
  readonly onSubmit: () => void;
  readonly onInterrupt?: () => void;
  readonly disabled?: boolean;
  readonly submitLabel?: string;
  readonly buttonDisabled: boolean;
  readonly fixture?: boolean;
  readonly leadingAction?: ReactNode;
  readonly model?: ReactNode;
  readonly notice?: ReactNode;
}

function resizeEditor(input: HTMLTextAreaElement) {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

export function MessageComposer({ title, text, onChange, onSubmit, onInterrupt, disabled,
  buttonDisabled, fixture, leadingAction, model, notice, submitLabel, images = [], onImagesChange }: ComposerProps) {
  const { t } = useTranslation("session");
  const editor = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const chooser = useRef<HTMLInputElement>(null);
  const [attachmentError, setAttachmentError] = useState(false);
  const canAttach = Boolean(onImagesChange && !disabled);
  function addImages(files: readonly File[]) {
    if (!canAttach || !files.length) return;
    const valid = files.filter(supportedImage);
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
  return (
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
        {images.map((file, index) => <div key={JSON.stringify([file.name, file.lastModified, index])}>
          <AttachmentImage blob={file} label={file.name || t("attachments.image")} />
          <button type="button" className="icon-button" disabled={!canAttach}
            aria-label={t("attachments.remove", { name: file.name || t("attachments.image") })}
            onClick={() => { setAttachmentError(false); onImagesChange?.(images.filter((_, i) => i !== index)); }}>
            <UiIcon name="close" />
          </button>
        </div>)}
      </div> : null}
      {attachmentError && onImagesChange ? <p role="alert">{t("attachments.invalid")}</p> : null}
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
          {onImagesChange ? <input hidden ref={chooser} type="file" accept={imageTypes.join(",")} multiple
            onChange={(event) => {
              addImages([...(event.currentTarget.files ?? [])]);
              event.currentTarget.value = "";
            }} /> : null}
          <button type="button" className="icon-button" aria-label={t(canAttach ? "attachments.add" : "composer.attachUnavailable")}
            title={t(canAttach ? "attachments.add" : "composer.attachHint")} disabled={!canAttach}
            onClick={() => chooser.current?.click()}>＋</button>
          {leadingAction}
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
  );
}
