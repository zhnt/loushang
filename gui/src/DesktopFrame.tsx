import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { UiIcon } from "./UiIcon";

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

export function DesktopFrame({ sidebarOpen, onToggleSidebar }: { sidebarOpen: boolean; onToggleSidebar: () => void }) {
  const native = isTauri();
  const [maximized, setMaximized] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!native) return;
    let active = true;
    let unlisten: (() => void) | undefined;
    const window = getCurrentWindow();
    const update = async () => { const value = await window.isMaximized(); if (active) setMaximized(value); };
    void update().catch(() => { if (active) setError("Window state unavailable"); });
    void window.onResized(() => { void update().catch(() => {}); }).then((stop) => {
      if (active) unlisten = stop; else stop();
    }).catch(() => { if (active) setError("Window resize notifications unavailable"); });
    return () => { active = false; unlisten?.(); };
  }, [native]);
  async function control(action: "minimize" | "toggleMaximize" | "close") {
    try { await getCurrentWindow()[action](); setError(""); }
    catch { setError("Window action failed. Please retry."); }
  }
  return <>
    <header className="native-frame" aria-label="Application menu">
      <button className="frame-icon" aria-label="Toggle sidebar" title="Toggle sidebar (Ctrl+B)" aria-pressed={sidebarOpen} onClick={onToggleSidebar}><PanelIcon side="left" /></button>
      <button className="frame-icon" aria-label="Back" disabled><UiIcon name="back" /></button>
      <button className="frame-icon" aria-label="Forward" disabled><UiIcon name="forward" /></button>
      <nav aria-label="Main menu"><span>File</span><span>Edit</span><span>View</span><span>Help</span></nav>
      <div className="window-drag-region" data-tauri-drag-region title="Drag window; double-click to maximize or restore" />
      <div className="window-controls">
        <button aria-label="Minimize window" disabled={!native} onClick={() => void control("minimize")}><WindowIcon action="minimize" /></button>
        <button aria-label={maximized ? "Restore window" : "Maximize window"} disabled={!native} onClick={() => void control("toggleMaximize")}><WindowIcon action={maximized ? "restore" : "maximize"} /></button>
        <button className="window-close" aria-label="Close window" disabled={!native} onClick={() => void control("close")}><WindowIcon action="close" /></button>
      </div>
    </header>
    {error ? <div role="alert" className="window-error">{error}</div> : null}
  </>;
}
