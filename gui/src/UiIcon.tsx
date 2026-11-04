export type UiIconName = "close" | "chevron-down" | "chevron-up" | "search" | "back" | "forward" | "folder" | "new-session" | "pull-request" | "scheduled" | "plugins";

// Shared presentation icons: fixed boxes avoid font-dependent glyph baselines.
export function UiIcon({ name }: { name: UiIconName }) {
  return <svg className="ui-icon" data-icon={name} aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    {name === "close" && <path d="m6 6 12 12M18 6 6 18" />}
    {name === "chevron-down" && <path d="m7 10 5 5 5-5" />}
    {name === "chevron-up" && <path d="m7 14 5-5 5 5" />}
    {name === "search" && <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></>}
    {name === "back" && <path d="M20 12H4m6-6-6 6 6 6" />}
    {name === "forward" && <path d="M4 12h16m-6-6 6 6-6 6" />}
    {name === "folder" && <><path d="M3 9V6a1 1 0 0 1 1-1h6l2 3h8a1 1 0 0 1 1 1v2" /><path d="M3 10h18l-2 9H3z" /></>}
    {name === "new-session" && <><path d="M10 5H5v14h14v-5M9 15l1-4L18 3l3 3-8 8zM16 5l3 3" /></>}
    {name === "pull-request" && <><circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="19" r="2" /><path d="M6 7v10m8-13-3 3 3 3m-3-3h4a3 3 0 0 1 3 3v7" /></>}
    {name === "scheduled" && <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l-3 3" /></>}
    {name === "plugins" && <><path d="M9 3v4m6-4v4M7 7h10v5a5 5 0 0 1-10 0zm5 10v4" /></>}
  </svg>;
}
