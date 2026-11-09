import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { UiIcon } from "./UiIcon";

interface SettingOption<Value extends string> {
  readonly value: Value;
  readonly label: string;
  readonly lang?: string;
}

export function SettingsSelect<Value extends string>({ id, label, description, value, options, onChange, busy = false }: {
  readonly id: string;
  readonly label: string;
  readonly description?: string;
  readonly value: Value;
  readonly options: readonly SettingOption<Value>[];
  readonly onChange: (value: Value) => void;
  readonly busy?: boolean;
}) {
  const listId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const selected = options.findIndex((option) => option.value === value);
  const open = active !== null;
  const dialog = open ? trigger.current?.closest("dialog") : null;
  const optionId = (index: number) => `${listId}-${index}`;

  useLayoutEffect(() => {
    const button = trigger.current;
    const menu = list.current;
    if (!open || !button || !menu || !dialog) return;
    const anchor = button.getBoundingClientRect();
    const bounds = dialog.getBoundingClientRect();
    const gap = 5;
    const inset = 6;
    const above = anchor.top - bounds.top - gap - inset;
    const below = bounds.bottom - anchor.bottom - gap - inset;
    menu.style.width = `${anchor.width}px`;
    menu.style.left = `${anchor.left}px`;
    const height = menu.getBoundingClientRect().height;
    const opensAbove = height > below && above > below;
    const available = Math.max(0, opensAbove ? above : below);
    menu.style.maxHeight = `${available}px`;
    menu.style.top = `${opensAbove ? anchor.top - gap - Math.min(height, available) : anchor.bottom + gap}px`;

    function dismissOutside(event: Event) {
      if (event.target instanceof Node && !button!.contains(event.target) && !menu!.contains(event.target)) setActive(null);
    }
    function dismiss() { setActive(null); }
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("scroll", dismissOutside, true);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("scroll", dismissOutside, true);
      window.removeEventListener("resize", dismiss);
    };
  }, [dialog, open]);

  function choose(index: number) {
    setActive(null);
    const option = options[index];
    if (option && option.value !== value) onChange(option.value);
  }

  function navigate(event: KeyboardEvent<HTMLButtonElement>) {
    if (busy) return;
    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      setActive(null);
    } else if (open && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      choose(active);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
        : active === null ? Math.max(0, selected)
        : Math.min(options.length - 1, Math.max(0, active + (event.key === "ArrowDown" ? 1 : -1)));
      setActive(next);
      if (list.current && list.current.scrollHeight > list.current.clientHeight) {
        document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" });
      }
    }
  }

  return <>
    <div className="settings-preference-label">
      <label htmlFor={id}>{label}</label>
      {description ? <p id={`${id}-description`}>{description}</p> : null}
    </div>
    <button type="button" id={id} ref={trigger} className="settings-select" role="combobox"
      aria-label={label} aria-describedby={description ? `${id}-description` : undefined}
      aria-expanded={open} aria-controls={open ? listId : undefined}
      aria-activedescendant={active === null ? undefined : optionId(active)}
      aria-disabled={busy || undefined} onBlur={() => setActive(null)} onKeyDown={navigate}
      onClick={() => {
        if (busy) return;
        trigger.current?.focus({ preventScroll: true });
        setActive(open ? null : Math.max(0, selected));
      }}>
      <span lang={options[selected]?.lang}>{options[selected]?.label}</span>
      <UiIcon name="chevron-down" />
    </button>
    {dialog && open ? createPortal(
      <div id={listId} ref={list} className="settings-select-options" role="listbox" aria-label={label}>
        {options.map((option, index) => <div key={option.value} id={optionId(index)}
          className="settings-select-option" role="option" aria-selected={option.value === value}
          data-active={index === active} onPointerMove={() => setActive(index)}
          onPointerDown={(event) => event.preventDefault()} onClick={() => choose(index)}>
          <span lang={option.lang}>{option.label}</span>
          {option.value === value ? <span aria-hidden="true">✓</span> : null}
        </div>)}
      </div>, dialog,
    ) : null}
  </>;
}
