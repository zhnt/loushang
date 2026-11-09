import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type Resources from "./i18n/generated/resources";

export interface FrameActions {
  onNewSession?: () => void;
  onFocusComposer?: () => void;
  onToggleEnvironment?: () => void;
  onToggleDock?: () => void;
  dockOpen?: boolean;
  onBack?: () => void;
  onForward?: () => void;
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
  environmentOpen?: boolean;
  onClose?: () => void;
  onQuit?: () => void;
  onSettings?: () => void;
}

type MenuName = "file" | "edit" | "view" | "help";
const names: MenuName[] = ["file", "edit", "view", "help"];
type Label = { [Key in keyof Resources["shell"]]: Resources["shell"][Key] extends string ? Key : never }[keyof Resources["shell"]];
interface MenuEntry { label: Label; action?: () => void; shortcut?: string; checked?: boolean; submenu?: boolean }

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
    const shortcut = (event: KeyboardEvent) => {
      if (event.isComposing || event.repeat || event.altKey || !(event.ctrlKey || event.metaKey) || event.shiftKey) return;
      const key = event.key.toLowerCase();
      if (key === "," && actions.onSettings) {
        event.preventDefault();
        setOpen(null);
        actions.onSettings();
        return;
      }
      const action = key === "n" ? actions.onNewSession
        : key === "w" ? actions.onClose
          : key === "q" ? actions.onQuit
          : key === "j" ? actions.onToggleDock
            : key === "[" ? actions.onBack : key === "]" ? actions.onForward
              : key === "/" ? () => { setOpen(null); returnFocus.current = root.current?.querySelector<HTMLButtonElement>('[data-menu="help"]') ?? null; setHelp("shortcuts"); } : undefined;
      if (action) { event.preventDefault(); action(); }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [actions.onNewSession, actions.onClose, actions.onQuit, actions.onToggleDock, actions.onBack, actions.onForward, actions.onSettings]);

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
  const entry = (label: Label, action?: () => void, shortcut?: string, checked?: boolean): MenuEntry => ({ label, action, shortcut, checked });
  const groups: Record<MenuName, MenuEntry[][]> = {
    file: [
      [entry("newWindow"), entry("newSession", actions.onNewSession, "Ctrl+N"), entry("temporarySession", undefined, "Ctrl+Shift+N"), entry("newProject")],
      [entry("openFolder", undefined, "Ctrl+O"), entry("focusComposer", actions.onFocusComposer), entry("close", actions.onClose, "Ctrl+W")],
      [entry("settings", actions.onSettings, "Ctrl+,")],
      [entry("signOut"), entry("quitApp", actions.onQuit, "Ctrl+Q")],
    ],
    edit: [
      [entry("undo", undefined, "Ctrl+Z"), entry("redo", undefined, "Ctrl+Shift+Z")],
      [entry("cut", undefined, "Ctrl+X"), entry("copySelection", selection.current && typeof navigator.clipboard?.writeText === "function" ? () => { void copy(); } : undefined, "Ctrl+C"), entry("paste", undefined, "Ctrl+V"), entry("deleteSelection")],
      [entry("selectAll", selectAll, "Ctrl+A")],
    ],
    view: [
      [entry("toggleSidebar", actions.onToggleSidebar, "Ctrl+B", actions.sidebarOpen), entry("toggleDock", actions.onToggleDock, "Ctrl+J", actions.dockOpen ?? false), entry("pinPanel"), entry("openTerminal", undefined, "Ctrl+`"), entry("toggleEnvironment", actions.onToggleEnvironment, undefined, actions.environmentOpen ?? false), entry("toggleNavigation", undefined, "Ctrl+Shift+E"), entry("switchChatTabs")],
      [{ label: "browser", submenu: true }],
      [entry("find", undefined, "Ctrl+F")],
      [entry("back", actions.onBack, "Ctrl+["), entry("forward", actions.onForward, "Ctrl+]")],
      [entry("previousSidebarItem", undefined, "Alt+Ctrl+["), entry("nextSidebarItem", undefined, "Alt+Ctrl+]")],
      [entry("previousTab", undefined, "Ctrl+Shift+["), entry("nextTab", undefined, "Ctrl+Shift+]")],
      [entry("zoomIn", undefined, "Ctrl+Shift+="), entry("zoomOut", undefined, "Ctrl+-"), entry("actualSize", undefined, "Ctrl+0")],
      [entry("fullscreen", undefined, "F11")],
    ],
    help: [
      [entry("documentation"), entry("shortcuts", () => showHelp("shortcuts"), "Ctrl+/"), entry("whatsNew")],
      [entry("troubleshooting"), entry("systemStatus"), entry("feedback")],
      [entry("taskManager"), entry("performanceTrace")],
      [entry("about", () => showHelp("about"))],
    ],
  };
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
          {groups[name].map((group, index) => <div className="frame-menu-group" key={index}>
            {index > 0 ? <div role="separator" className="frame-menu-separator" /> : null}
            {group.map((item) => <button key={item.label} role={item.checked === undefined ? "menuitem" : "menuitemcheckbox"}
              aria-label={t(item.label)} aria-checked={item.checked} aria-haspopup={item.submenu ? "menu" : undefined}
              disabled={!item.action} title={!item.action ? t("actionUnavailable") : undefined}
              onClick={() => { if (item.action) run(item.action); }}>
              <span className="menu-check" aria-hidden="true">{item.checked ? "✓" : ""}</span>
              <span className="menu-label">{t(item.label)}</span>
              {item.shortcut ? <kbd aria-hidden="true">{item.shortcut}</kbd> : null}
              {item.submenu ? <span aria-hidden="true">›</span> : null}
            </button>)}
          </div>)}
        </div> : null}
      </div>)}
    </nav>
    {copyFailed ? <div role="alert" className="window-error"><span>{t("copyFailed")}</span><button onClick={() => setCopyFailed(false)}>{t("dismiss")}</button></div> : null}
    {help ? <dialog ref={dialog} className="frame-dialog" aria-labelledby="frame-dialog-title" onCancel={() => setHelp(null)} onClose={() => setHelp(null)}>
      <h2 id="frame-dialog-title">{help === "about" ? t("about") : t("shortcuts")}</h2>
      {help === "about" ? <><p>{t("aboutDescription")}</p><p>{t("aboutRuntime")}</p></> : <dl>
        <dt>{t("sidebarShortcut")}</dt><dd>{t("toggleSidebar")}</dd>
        <dt>{t("sendShortcut")}</dt><dd>{t("sendMessage")}</dd>
        <dt>{t("newlineShortcut")}</dt><dd>{t("insertNewline")}</dd>
        <dt>{t("arrowsShortcut")}</dt><dd>{t("menuNavigation")}</dd>
        <dt>{t("escapeShortcut")}</dt><dd>{t("dismissMenu")}</dd>
      </dl>}
      <button autoFocus onClick={() => setHelp(null)}>{t("dismiss")}</button>
    </dialog> : null}
  </>;
}
