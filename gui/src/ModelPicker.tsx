import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import type { SessionModels } from "./client/model";

type ModelChoice = SessionModels["models"][number];

export function ModelPicker({ models, disabled, onSelect }: {
  readonly models: SessionModels | null;
  readonly disabled: boolean;
  readonly onSelect: (id: string) => void;
}) {
  const { t } = useTranslation("session");
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const current = models?.models.find((choice) => choice.id === models.currentId);
  const visible = open && !disabled;

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (visible) {
      const item = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
        ?? menu.current?.querySelector<HTMLButtonElement>("button");
      item?.focus();
    }
  }, [visible]);

  function label(choice: ModelChoice) {
    return t(choice.supportsThinking ? "models.reasoningOption" : "models.option", {
      provider: choice.provider,
      model: choice.modelId,
    });
  }

  function close() {
    trigger.current?.focus();
    setOpen(false);
  }

  function navigate(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = Array.from(event.currentTarget.querySelectorAll("button"));
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : (index + delta + items.length) % items.length;
    event.preventDefault();
    items[next]?.focus();
  }

  return (
    <div className="model-picker" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
      <button
        type="button"
        ref={trigger}
        className="model-trigger"
        aria-label={t("models.label")}
        aria-haspopup="menu"
        aria-expanded={visible}
        aria-controls={visible ? menuId : undefined}
        aria-describedby="model-current-label model-effort-status"
        disabled={disabled}
        title={current ? label(current) : t("models.none")}
        onClick={() => setOpen(!visible)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span id="model-current-label">{current ? label(current) : t("models.none")}</span>
        {!disabled ? <span className="model-chevron" aria-hidden="true">⌄</span> : null}
      </button>
      {visible ? <div ref={menu} id={menuId} className="model-menu" role="menu" aria-label={t("models.label")} onKeyDown={navigate}>
        {models?.models.map((choice) => <button
          type="button"
          key={choice.id}
          role="menuitemradio"
          aria-checked={choice.id === models.currentId}
          tabIndex={-1}
          onClick={() => {
            close();
            if (choice.id !== models.currentId) onSelect(choice.id);
          }}
        >
          <span>{label(choice)}</span>
          <small>{t("models.endpoint", { endpoint: choice.endpointId })}</small>
        </button>)}
      </div> : null}
    </div>
  );
}
