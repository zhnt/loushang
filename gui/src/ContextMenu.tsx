import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { UiIcon, type UiIconName } from "./UiIcon";

type Item = { label: string; run: () => void | Promise<void>; disabled?: boolean; danger?: boolean; icon?: UiIconName };
type Entry = Item | { label: string; items: readonly Item[] };
type Menu = { anchor: HTMLElement; x: number; y: number; entries: readonly Entry[]; above?: boolean };
const OpenMenu = createContext<(event: MouseEvent<HTMLElement>, entries: readonly Entry[], above?: boolean) => void>(() => {});
export const useContextMenu = () => useContext(OpenMenu);

function editorAt(target: HTMLElement) {
  const field = target.closest("input, textarea");
  if (field instanceof HTMLTextAreaElement) return field.disabled ? null : field;
  return field instanceof HTMLInputElement && !field.disabled && ["text", "search", "tel", "url"].includes(field.type) ? field : null;
}

type Editor = NonNullable<ReturnType<typeof editorAt>>;

function replaceSelection(field: Editor, value: string, start: number, end: number, text: string) {
  if (!field.isConnected || document.activeElement !== field || field.disabled || field.readOnly || field.value !== value) return;
  field.setSelectionRange(start, end);
  if (document.execCommand?.(text ? "insertText" : "delete", false, text)) return;
  field.setRangeText(text, start, end, "end");
  field.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
}

function at(target: HTMLElement, x: number, y: number, entries: readonly Entry[], above?: boolean): Menu {
  const bounds = target.getBoundingClientRect();
  return { anchor: target, x: x || bounds.left, y: y || bounds.bottom, entries, above };
}

export function ContextMenuProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation("common");
  const [menu, setMenu] = useState<Menu | null>(null);
  const [failed, setFailed] = useState(false);
  const popup = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(event: globalThis.MouseEvent) {
      if (event.defaultPrevented) return;
      event.preventDefault();
      setMenu(null);
      setFailed(false);
      if (!(event.target instanceof HTMLElement)) return;
      const field = editorAt(event.target);
      const selection = window.getSelection();
      if (!field) {
        const text = selection?.toString();
        if (text && selection?.containsNode(event.target, true)) {
          setMenu(at(event.target, event.clientX, event.clientY, [
            { label: t("clipboard.copy"), run: () => navigator.clipboard.writeText(text) },
          ]));
        }
        return;
      }
      const { value, selectionStart, selectionEnd } = field;
      const start = selectionStart ?? 0;
      const end = selectionEnd ?? start;
      const text = value.slice(start, end);
      setMenu(at(field, event.clientX, event.clientY, [
        { label: t("clipboard.copy"), disabled: !text, run: () => navigator.clipboard.writeText(text) },
        { label: t("clipboard.cut"), disabled: !text || field.readOnly, run: async () => {
          await navigator.clipboard.writeText(text);
          replaceSelection(field, value, start, end, "");
        } },
        { label: t("clipboard.paste"), disabled: field.readOnly, run: async () => {
          const pasted = await navigator.clipboard.readText();
          if (pasted) replaceSelection(field, value, start, end, pasted);
        } },
        { label: t("clipboard.selectAll"), disabled: !value, run: () => field.select() },
      ]));
    }
    document.addEventListener("contextmenu", handle);
    return () => document.removeEventListener("contextmenu", handle);
  }, [t]);

  useLayoutEffect(() => {
    if (!menu || !popup.current) return;
    const element = popup.current;
    let { x, y } = menu;
    if (menu.above) {
      const anchor = menu.anchor.getBoundingClientRect();
      const top = anchor.top - element.offsetHeight - 6;
      x = anchor.left;
      y = top >= 4 ? top : anchor.bottom + 6;
    }
    element.style.left = `${Math.max(4, Math.min(x, window.innerWidth - element.offsetWidth - 4))}px`;
    element.style.top = `${Math.max(4, Math.min(y, window.innerHeight - element.offsetHeight - 4))}px`;
    // Keep the editor and its text selection active for clipboard operations.
    if (!editorAt(menu.anchor)) element.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [menu]);

  useEffect(() => {
    if (!menu) return;
    const dismiss = () => setMenu(null);
    const outside = (event: PointerEvent) => {
      if (!popup.current?.contains(event.target as Node)) dismiss();
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" || event.key === "Tab") {
        if (event.key === "Escape") {
          event.preventDefault();
          menu.anchor.focus({ preventScroll: true });
        }
        dismiss();
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const items = [...(popup.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? [])];
        if (!items.length) return;
        const index = items.findIndex((item) => item === document.activeElement);
        const offset = event.key === "ArrowDown" ? 1 : items.length - 1;
        items[index < 0 ? (event.key === "ArrowDown" ? 0 : items.length - 1) : (index + offset) % items.length]?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keyboard);
    window.addEventListener("blur", dismiss);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", keyboard);
      window.removeEventListener("blur", dismiss);
      window.removeEventListener("resize", dismiss);
    };
  }, [menu]);

  function renderItem(item: Item, anchor: HTMLElement) {
    return <button key={item.label} type="button" role="menuitem"
      disabled={item.disabled} className={item.danger ? "context-menu-danger" : undefined}
      onMouseDown={(event) => event.preventDefault()}
      onClick={async () => {
        setMenu(null);
        anchor.focus({ preventScroll: true });
        try { await item.run(); } catch { setFailed(true); }
      }}>{item.icon ? <UiIcon name={item.icon} /> : null}{item.label}</button>;
  }

  return <OpenMenu.Provider value={(event, entries, above) => {
    event.preventDefault();
    setFailed(false);
    setMenu(at(event.currentTarget, event.clientX, event.clientY, entries, above));
  }}>
    {children}
    {menu ? createPortal(<div ref={popup} className="app-context-menu" role="menu" aria-label={t("contextMenu")}>
      {menu.entries.map((entry) => "items" in entry
        ? <div key={entry.label} role="group" aria-label={entry.label} className="context-menu-group">
          <div className="section-label" aria-hidden="true">{entry.label}</div>
          {entry.items.map((item) => renderItem(item, menu.anchor))}
        </div>
        : renderItem(entry, menu.anchor))}
    </div>, menu.anchor.closest("dialog[open]") ?? document.body) : null}
    {failed ? <p className="context-menu-error" role="alert">{t("clipboard.unavailable")}</p> : null}
  </OpenMenu.Provider>;
}
