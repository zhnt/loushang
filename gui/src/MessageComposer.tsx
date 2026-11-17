import { useLayoutEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface ComposerProps {
  readonly title: string;
  readonly text: string;
  readonly onChange: (text: string) => void;
  readonly onSubmit: () => void;
  readonly onInterrupt?: () => void;
  readonly disabled?: boolean;
  readonly submitLabel?: string;
  readonly buttonDisabled: boolean;
  readonly fixture?: boolean;
  readonly model?: ReactNode;
  readonly notice?: ReactNode;
}

export function MessageComposer({ title, text, onChange, onSubmit, onInterrupt, disabled,
  buttonDisabled, fixture, model, notice, submitLabel }: ComposerProps) {
  const { t } = useTranslation("session");
  const editor = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  useLayoutEffect(() => {
    const input = editor.current;
    if (!input) return;
    const resize = () => {
      input.style.height = "auto";
      input.style.height = `${input.scrollHeight}px`;
    };
    resize();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(resize);
    if (input.parentElement) observer.observe(input.parentElement);
    return () => observer.disconnect();
  }, [text]);
  return (
    <form className="composer" onSubmit={(event) => { event.preventDefault(); onSubmit(); }}>
      <label className="visually-hidden" htmlFor="message-input">{t("composer.messageFor", { title })}</label>
      <textarea ref={editor} id="message-input" disabled={disabled} aria-describedby="message-keyboard-hint" rows={2}
        value={text} placeholder={t(fixture ? "composer.fixturePlaceholder" : "composer.livePlaceholder")}
        onChange={(event) => onChange(event.currentTarget.value)}
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
          <button type="button" className="icon-button" aria-label={t("composer.attachUnavailable")} title={t("composer.attachHint")} disabled>＋</button>
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
