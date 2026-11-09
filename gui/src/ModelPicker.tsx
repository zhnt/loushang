import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { UiIcon } from "./UiIcon";
import type { ModelChoice, SessionModels, ThinkingLevel } from "./client/model";

export function ModelPicker({ models, disabled, busy, onSelect }: {
  readonly models: SessionModels | null;
  readonly disabled: boolean;
  readonly busy: boolean;
  readonly onSelect: (id: string, level?: ThinkingLevel) => Promise<SessionModels | null>;
}) {
  const { t } = useTranslation("session");
  const [stage, setStage] = useState<"model" | "thinking" | null>(null);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const current = models?.models.find((choice) => choice.id === models.currentId);
  const thinking = models?.thinking;
  const open = stage !== null && !disabled;

  useEffect(() => {
    if (disabled) setStage(null);
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const item = menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      ?? menu.current?.querySelector<HTMLButtonElement>("button");
    item?.focus();
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setStage(null);
    }
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open, stage]);

  function label(choice: ModelChoice) {
    return t("models.option", { provider: choice.provider, model: choice.modelId });
  }

  function close() {
    trigger.current?.focus({ preventScroll: true });
    setStage(null);
  }

  function navigate(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
    const index = items.findIndex((item) => item === document.activeElement);
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
      : (index + delta + items.length) % items.length;
    event.preventDefault();
    items[next]?.focus();
  }

  async function chooseModel(id: string) {
    if (busy) return;
    const result = id === current?.id ? models : await onSelect(id);
    if (!result) return;
    if ((result.thinking?.availableLevels.length ?? 0) > 1) {
      setStage((previous) => previous === "model" ? "thinking" : previous);
    } else {
      close();
    }
  }

  async function chooseLevel(level: ThinkingLevel) {
    if (!current || busy) return;
    if (level === thinking?.currentLevel || await onSelect(current.id, level)) close();
  }

  return <div ref={root} className="model-picker" onBlur={(event) => {
    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) setStage(null);
  }}>
    <button type="button" ref={trigger} className="model-trigger" aria-label={t("models.label")}
      aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
      aria-describedby="model-current-label" aria-disabled={busy || undefined} disabled={disabled}
      title={current ? label(current) : t("models.none")}
      onClick={() => { if (!busy) setStage(open ? null : "model"); }}
      onKeyDown={(event) => {
        if (!busy && !open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          event.preventDefault();
          setStage("model");
        }
      }}>
      <span id="model-current-label" className="model-current-label">
        <span>{current ? label(current) : t("models.none")}</span>
        {thinking ? <span className="thinking-badge">{t(`models.levels.${thinking.currentLevel}`)}</span> : null}
      </span>
      {!disabled ? <UiIcon name="chevron-down" /> : null}
    </button>
    {open ? <div ref={menu} id={menuId} className="model-menu" role="menu"
      aria-label={t(stage === "thinking" ? "models.thinking" : "models.label")} aria-busy={busy} onKeyDown={navigate}>
      {stage === "thinking" ? <>
        <button type="button" role="menuitem" tabIndex={-1} className="model-back" onClick={() => setStage("model")}>
          <span aria-hidden="true">‹</span>{t("models.back")}
        </button>
        <div className="model-menu-heading" aria-hidden="true">{t("models.thinking")}</div>
        <div className="model-menu-list" role="group">
          {thinking?.availableLevels.map((level) => <button type="button" key={level} role="menuitemradio"
            aria-checked={level === thinking.currentLevel} tabIndex={-1} onClick={() => void chooseLevel(level)}>
            <span>{t(`models.levels.${level}`)}</span>
          </button>)}
        </div>
      </> : <>
        <div className="model-menu-heading" aria-hidden="true">{t("models.label")}</div>
        <div className="model-menu-list" role="group">
          {models?.models.map((choice) => <button type="button" key={choice.id} role="menuitemradio"
            aria-checked={choice.id === current?.id} tabIndex={-1} onClick={() => void chooseModel(choice.id)}>
            <span>{label(choice)}</span>
            <small>{t("models.endpoint", { endpoint: choice.endpointId })}</small>
          </button>)}
        </div>
      </>}
    </div> : null}
  </div>;
}
