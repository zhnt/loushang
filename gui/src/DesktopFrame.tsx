import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { UiIcon } from "./UiIcon";
import { FrameMenu, type FrameActions } from "./FrameMenu";

const resizeEdges = ["North", "South", "West", "East", "NorthWest", "NorthEast", "SouthWest", "SouthEast"] as const;

export function PanelIcon({ side }: { side: "left" | "right" | "bottom" | "environment" }) {
  return <svg aria-hidden="true" viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.2">
    {side === "environment" ? <><circle cx="5" cy="5" r="1.5" /><circle cx="5" cy="14" r="1.5" /><path d="M10 5h6M10 14h6" /></>
      : <><rect x="3" y="3" width="14" height="14" rx="2" /><path d={side === "left" ? "M8 3v14" : side === "right" ? "M12 3v14" : "M3 12h14"} /></>}
  </svg>;
}

function WindowIcon({ action }: { action: "minimize" | "maximize" | "restore" | "close" }) {
  return <svg aria-hidden="true" focusable="false" viewBox="0 0 12 12" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1">
    {action === "minimize" ? <path d="M1 6.5h10" /> : null}
    {action === "maximize" ? <rect x="1.5" y="1.5" width="9" height="9" /> : null}
    {action === "restore" ? <><path d="M3.5 3.5v-2h7v7h-2" /><rect x="1.5" y="3.5" width="7" height="7" /></> : null}
    {action === "close" ? <path d="m1.5 1.5 9 9m0-9-9 9" /> : null}
  </svg>;
}

function useNativeWindow(native: boolean) {
  const [maximized, setMaximized] = useState(false);
  const [error, setError] = useState<"stateUnavailable" | "resizeUnavailable" | "actionFailed" | null>(null);
  useEffect(() => {
    if (!native) return;
    let active = true;
    let unlisten: (() => void) | undefined;
    const window = getCurrentWindow();
    const update = async () => { const value = await window.isMaximized(); if (active) setMaximized(value); };
    void update().catch(() => { if (active) setError("stateUnavailable"); });
    void window.onResized(() => { void update().catch(() => {}); }).then((stop) => {
      if (active) unlisten = stop; else stop();
    }).catch(() => { if (active) setError("resizeUnavailable"); });
    return () => { active = false; unlisten?.(); };
  }, [native]);
  return { maximized, error, setError };
}

export function DesktopFrame({ onBack, onForward, ...actions }: FrameActions & { onBack?: () => void; onForward?: () => void }) {
  const { t } = useTranslation("shell");
  const native = isTauri();
  const { maximized, error, setError } = useNativeWindow(native);
  async function control(action: "minimize" | "toggleMaximize" | "close") {
    try { await getCurrentWindow()[action](); setError(null); }
    catch { setError("actionFailed"); }
  }
  async function quit() {
    try { await invoke("quit_app"); }
    catch { setError("actionFailed"); }
  }
  if (!native) return null;
  return <>
    <header className="native-frame" aria-label={t("applicationMenu")}>
      <button className="frame-icon" aria-label={t("back")} title={t("back")} disabled={!onBack} onClick={onBack}><UiIcon name="back" /></button>
      <button className="frame-icon" aria-label={t("forward")} title={t("forward")} disabled={!onForward} onClick={onForward}><UiIcon name="forward" /></button>
      <FrameMenu {...actions} onBack={onBack} onForward={onForward} onClose={() => { void control("close"); }} onQuit={() => { void quit(); }} />
      <div className="window-drag-region" data-tauri-drag-region title={t("dragWindow")} />
      <div className="window-controls">
        <button aria-label={t("minimize")} disabled={!native} onClick={() => void control("minimize")}><WindowIcon action="minimize" /></button>
        <button aria-label={maximized ? t("restore") : t("maximize")} disabled={!native} onClick={() => void control("toggleMaximize")}><WindowIcon action={maximized ? "restore" : "maximize"} /></button>
        <button className="window-close" aria-label={t("close")} disabled={!native} onClick={() => void control("close")}><WindowIcon action="close" /></button>
      </div>
    </header>
    {!maximized ? resizeEdges.map((edge) => (
      <div key={edge} className="window-resize-edge" data-edge={edge} aria-hidden="true" onPointerDown={(event) => {
        if (event.button !== 0 || event.pointerType !== "mouse") return;
        event.preventDefault();
        void getCurrentWindow().startResizeDragging(edge).catch(() => setError("actionFailed"));
      }} />
    )) : null}
    {error ? <div role="alert" className="window-error">{t(error)}</div> : null}
  </>;
}
