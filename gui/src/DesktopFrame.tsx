import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

export function PanelIcon({ side }: { side: "left" | "right" | "bottom" | "environment" }) {
  return <svg aria-hidden="true" viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.2">
    {side === "environment" ? <><circle cx="5" cy="5" r="1.5" /><circle cx="5" cy="14" r="1.5" /><path d="M10 5h6M10 14h6" /></>
      : <><rect x="3" y="3" width="14" height="14" rx="2" /><path d={side === "left" ? "M8 3v14" : side === "right" ? "M12 3v14" : "M3 12h14"} /></>}
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
      <button className="frame-icon" aria-label="Back" disabled>←</button>
      <button className="frame-icon" aria-label="Forward" disabled>→</button>
      <nav aria-label="Main menu"><span>File</span><span>Edit</span><span>View</span><span>Help</span></nav>
      <div className="window-drag-region" data-tauri-drag-region title="Drag window; double-click to maximize or restore" />
      <div className="window-controls">
        <button aria-label="Minimize window" disabled={!native} onClick={() => void control("minimize")}>─</button>
        <button aria-label={maximized ? "Restore window" : "Maximize window"} disabled={!native} onClick={() => void control("toggleMaximize")}>{maximized ? "❐" : "□"}</button>
        <button className="window-close" aria-label="Close window" disabled={!native} onClick={() => void control("close")}>×</button>
      </div>
    </header>
    {error ? <div role="alert" className="window-error">{error}</div> : null}
  </>;
}
