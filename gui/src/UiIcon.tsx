export type UiIconName = "close" | "check" | "chevron-down" | "chevron-up" | "chevron-right" | "search" | "back" | "forward" | "folder" | "folder-closed" | "conversation" | "new-session" | "plus" | "goal" | "pull-request" | "scheduled" | "plugins" | "settings" | "account" | "host" | "pin" | "copy" | "paperclip" | "refresh" | "review";

// Shared presentation icons: fixed boxes avoid font-dependent glyph baselines.
export function UiIcon({ name }: { name: UiIconName }) {
  return <svg className="ui-icon" data-icon={name} aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    {name === "close" && <path d="m6 6 12 12M18 6 6 18" />}
    {name === "check" && <path d="m5 12 4 4L19 6" />}
    {name === "copy" && <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>}
    {name === "paperclip" && <path d="m9 12 6-6a2.5 2.5 0 0 1 3.5 3.5l-7.5 7.5a4 4 0 0 1-5.7-5.7l8-8M9 12a1.5 1.5 0 0 0 2.1 2.1l5.6-5.6" />}
    {name === "refresh" && <path d="M20 10a8 8 0 0 0-13-4L4 9m0-5v5h5m-5 5a8 8 0 0 0 13 4l3-3m-5 0h5v5" />}
    {name === "review" && <path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10zm0 0v7h7M8 14l2 2 4-4" />}
    {name === "chevron-down" && <path d="m7 10 5 5 5-5" />}
    {name === "chevron-up" && <path d="m7 14 5-5 5 5" />}
    {name === "chevron-right" && <path d="m10 7 5 5-5 5" />}
    {name === "search" && <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></>}
    {name === "back" && <path d="M20 12H4m6-6-6 6 6 6" />}
    {name === "forward" && <path d="M4 12h16m-6-6 6 6-6 6" />}
    {name === "folder" && <><path d="M3 9V6a1 1 0 0 1 1-1h6l2 3h8a1 1 0 0 1 1 1v2" /><path d="M3 10h18l-2 9H3z" /></>}
    {name === "folder-closed" && <path d="M3 6a1 1 0 0 1 1-1h6l2 3h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />}
    {name === "conversation" && <path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />}
    {name === "new-session" && <><path d="M10 5H5v14h14v-5M9 15l1-4L18 3l3 3-8 8zM16 5l3 3" /></>}
    {name === "plus" && <path d="M4 12h16M12 4v16" />}
    {name === "goal" && <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /></>}
    {name === "pull-request" && <><circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="19" r="2" /><path d="M6 7v10m8-13-3 3 3 3m-3-3h4a3 3 0 0 1 3 3v7" /></>}
    {name === "scheduled" && <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l-3 3" /></>}
    {name === "plugins" && <><path d="M9 3v4m6-4v4M7 7h10v5a5 5 0 0 1-10 0zm5 10v4" /></>}
    {name === "account" && <><circle cx="12" cy="8" r="3" /><path d="M5 20v-2a7 7 0 0 1 14 0v2" /></>}
    {name === "pin" && <path d="m15 3 6 6-3 1-4 4-1 4-3-3-5 5-1-1 5-5-3-3 4-1 4-4z" />}
    {name === "host" && <><rect x="4" y="5" width="16" height="11" rx="2" /><path d="M9 20h6m-3-4v4" /></>}
    {name === "settings" && <><path d="M9 3h6l.6 3 2 .9 2.8-.9 2 3.4-2.2 2v2.2l2.2 2-2 3.4-2.8-.9-2 .9-.6 3H9l-.6-3-2-.9-2.8.9-2-3.4 2.2-2v-2.2l-2.2-2 2-3.4 2.8.9 2-.9z" /><circle cx="12" cy="12" r="3" /></>}
  </svg>;
}
