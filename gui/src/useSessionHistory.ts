import { useEffect, useState } from "react";

/** UI-only navigation: Session facts still come exclusively from AppClient. */
export function useSessionHistory(owner: object | string, selectedId: string | null, available: Readonly<Record<string, unknown>>, select: (id: string) => void) {
  const [history, setHistory] = useState<{ owner: object | string; ids: string[]; index: number }>({ owner, ids: [], index: -1 });
  useEffect(() => {
    setHistory((previous) => {
      if (previous.owner !== owner) return { owner, ids: selectedId ? [selectedId] : [], index: selectedId ? 0 : -1 };
      if (!selectedId || previous.ids[previous.index] === selectedId) return previous;
      const ids = [...previous.ids.slice(0, previous.index + 1), selectedId].slice(-100);
      return { owner, ids, index: ids.length - 1 };
    });
  }, [owner, selectedId]);
  function target(direction: -1 | 1) {
    if (history.owner !== owner) return -1;
    for (let index = history.index + direction; index >= 0 && index < history.ids.length; index += direction) {
      if (Object.prototype.hasOwnProperty.call(available, history.ids[index]!)) return index;
    }
    return -1;
  }
  function navigate(index: number) {
    if (index < 0) return;
    setHistory({ ...history, index });
    select(history.ids[index]!);
  }
  const back = target(-1), forward = target(1);
  return { onBack: back < 0 ? undefined : () => navigate(back), onForward: forward < 0 ? undefined : () => navigate(forward) };
}
