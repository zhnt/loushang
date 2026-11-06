import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface FrameActions {
  onNewSession?: () => void;
  onFocusComposer?: () => void;
  onToggleEnvironment?: () => void;
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
  environmentOpen?: boolean;
  onClose?: () => void;
}

type MenuName = "file" | "edit" | "view" | "help";
const names: MenuName[] = ["file", "edit", "view", "help"];

export function FrameMenu(actions: FrameActions) {
  const { t } = useTranslation("shell");
  const [open, setOpen] = useState<MenuName | null>(null);
  const [help, setHelp] = useState<"about" | "shortcuts" | null>(null);
  const [copyFailed, setCopyFailed] = useState(false);
  const root = useRef<HTMLElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const selection = useRef("");
  const editor = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const capture = (event: FocusEvent) => {
      const field = event.target;
      if (field instanceof HTMLTextAreaElement || (field instanceof HTMLInputElement && field.type !== "password")) {
        editor.current = field;
        selection.current = field.value.slice(field.selectionStart ?? 0, field.selectionEnd ?? 0);
      } else if (!root.current?.contains(field as Node)) {
        editor.current = null;
        selection.current = window.getSelection()?.toString() ?? "";
      }
    };
    document.addEventListener("focusout", capture);
    return () => document.removeEventListener("focusout", capture);
  }, []);

  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLButtonElement>('[role="menu"] button:not(:disabled)')?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(null);
    };
    const blur = () => setOpen(null);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("blur", blur);
    return () => { document.removeEventListener("pointerdown", outside); window.removeEventListener("blur", blur); };
  }, [open]);

  useEffect(() => {
    if (!help) return;
    dialog.current?.showModal();
    return () => { dialog.current?.close(); returnFocus.current?.focus(); };
  }, [help]);

  function rememberSelection() {
    const active = document.activeElement;
    editor.current = active instanceof HTMLTextAreaElement || (active instanceof HTMLInputElement && active.type !== "password") ? active : null;
    const field = editor.current;
    selection.current = field ? field.value.slice(field.selectionStart ?? 0, field.selectionEnd ?? 0) : window.getSelection()?.toString() ?? "";
  }
  function close(restore = true) {
    if (restore) root.current?.querySelector<HTMLButtonElement>(`[data-menu="${open}"]`)?.focus();
    setOpen(null);
  }
  function run(action: () => void) { close(); action(); }
  function showHelp(kind: "about" | "shortcuts") {
    returnFocus.current = root.current?.querySelector<HTMLButtonElement>('[data-menu="help"]') ?? null;
    setHelp(kind);
  }
  function selectAll() {
    if (editor.current) { editor.current.focus(); editor.current.select(); }
    else {
      const content = document.querySelector(".app-shell");
      if (content) { const range = document.createRange(); range.selectNodeContents(content); const selected = window.getSelection(); selected?.removeAllRanges(); selected?.addRange(range); }
    }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(selection.current); setCopyFailed(false); }
    catch { setCopyFailed(true); }
  }
  return <>
    <nav ref={root} className="frame-menus" aria-label={t("mainMenu")}
      onKeyDown={(event) => {
        if (!open) return;
        if (event.key === "Escape") { event.preventDefault(); close(); }
        if (event.key === "Tab") close();
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault(); setOpen(names[(names.indexOf(open) + (event.key === "ArrowRight" ? 1 : 3)) % names.length]!);
        }
      }}>
      {names.map((name) => <div className="frame-menu" key={name}>
        <button data-menu={name} aria-haspopup="menu" aria-expanded={open === name} aria-controls={`frame-menu-${name}`}
          onPointerDown={() => { if (!open) rememberSelection(); }}
          onClick={() => setOpen(open === name ? null : name)}
          onKeyDown={(event) => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(name); } }}
          onPointerEnter={() => { if (open) setOpen(name); }}>{t(name)}</button>
        {open === name ? <div id={`frame-menu-${name}`} role="menu" aria-label={t(name)} className="frame-menu-popup"
          onKeyDown={(event) => {
            if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
            const index = items.indexOf(document.activeElement as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
            items[next]?.focus();
          }}>
          {name === "file" ? <>
            <button role="menuitem" disabled={!actions.onNewSession} onClick={() => run(() => actions.onNewSession?.())}>{t("newSession")}</button>
            <button role="menuitem" disabled={!actions.onFocusComposer} onClick={() => run(() => actions.onFocusComposer?.())}>{t("focusComposer")}</button>
            {actions.onClose ? <button role="menuitem" onClick={() => run(() => actions.onClose?.())}>{t("close")}</button> : null}
          </> : null}
          {name === "edit" ? <>
            <button role="menuitem" disabled={!selection.current || !navigator.clipboard?.writeText} onClick={() => run(() => { void copy(); })}>{t("copySelection")}</button>
            <button role="menuitem" onClick={() => run(selectAll)}>{t("selectAll")}</button>
          </> : null}
          {name === "view" ? <>
            <button role="menuitemcheckbox" aria-checked={actions.sidebarOpen} onClick={() => run(actions.onToggleSidebar)}>{t("toggleSidebar")}<kbd>{t("sidebarShortcut")}</kbd></button>
            <button role="menuitemcheckbox" aria-checked={actions.environmentOpen ?? false} disabled={!actions.onToggleEnvironment} onClick={() => run(() => actions.onToggleEnvironment?.())}>{t("toggleEnvironment")}</button>
          </> : null}
          {name === "help" ? <>
            <button role="menuitem" onClick={() => run(() => showHelp("shortcuts"))}>{t("shortcuts")}</button>
            <button role="menuitem" onClick={() => run(() => showHelp("about"))}>{t("about")}</button>
          </> : null}
        </div> : null}
      </div>)}
    </nav>
    {copyFailed ? <div role="alert" className="window-error"><span>{t("copyFailed")}</span><button onClick={() => setCopyFailed(false)}>{t("dismiss")}</button></div> : null}
    {help ? <dialog ref={dialog} className="frame-dialog" aria-labelledby="frame-dialog-title" onCancel={() => setHelp(null)} onClose={() => setHelp(null)}>
      <h2 id="frame-dialog-title">{help === "about" ? t("about") : t("shortcuts")}</h2>
      {help === "about" ? <><p>{t("aboutDescription")}</p><p>{t("aboutRuntime")}</p></> : <dl>
        <dt>{t("sidebarShortcut")}</dt><dd>{t("toggleSidebar")}</dd>
        <dt>{t("sendShortcut")}</dt><dd>{t("sendMessage")}</dd>
        <dt>{t("arrowsShortcut")}</dt><dd>{t("menuNavigation")}</dd>
        <dt>{t("escapeShortcut")}</dt><dd>{t("dismissMenu")}</dd>
      </dl>}
      <button autoFocus onClick={() => setHelp(null)}>{t("dismiss")}</button>
    </dialog> : null}
  </>;
}
