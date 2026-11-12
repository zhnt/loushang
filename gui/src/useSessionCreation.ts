import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientSnapshot, HarnessClientUiPort } from "./client/model";

const CONFIRMATION_TIMEOUT_MS = 15_000;

type CreationNotice = "notice.creating" | "notice.createFailed" | "notice.createSyncFailed";

interface Creation {
  client: HarnessClientUiPort;
  sessionId?: string;
  timer?: number;
}

export function useSessionCreation(
  client: HarnessClientUiPort,
  setNotice: (notice: { key: CreationNotice }) => void,
) {
  const current = useRef<Creation | null>(null);
  const [pendingClient, setPendingClient] = useState<HarnessClientUiPort | null>(null);

  useEffect(() => {
    setPendingClient(null);
    return () => {
      window.clearTimeout(current.current?.timer);
      current.current = null;
    };
  }, [client]);

  const confirm = useCallback((source: HarnessClientUiPort, snapshot: ClientSnapshot) => {
    const attempt = current.current;
    const id = attempt?.sessionId;
    if (attempt?.client !== source || !id || !snapshot.sessions.some((session) => session.id === id)) return;
    window.clearTimeout(attempt.timer);
    current.current = null;
    setPendingClient(null);
    return id;
  }, []);

  async function create(sourceSessionId: string | undefined, title: string) {
    const previous = current.current;
    if (!client.createSession || (previous?.client === client &&
      (previous.sessionId === undefined || previous.timer !== undefined))) return;
    const attempt: Creation = { client };
    current.current = attempt;
    setPendingClient(client);
    try {
      const receipt = await client.createSession({ sourceSessionId, title });
      if (current.current !== attempt) return;
      attempt.sessionId = receipt.sessionId;
    } catch {
      if (current.current !== attempt) return;
      current.current = null;
      setPendingClient(null);
      setNotice({ key: "notice.createFailed" });
      return;
    }

    setNotice({ key: "notice.creating" });
    function confirmationFailed() {
      if (current.current !== attempt || attempt.timer === undefined) return;
      window.clearTimeout(attempt.timer);
      attempt.timer = undefined;
      // Keep the receipt so a later snapshot can still select the Session.
      setPendingClient(null);
      setNotice({ key: "notice.createSyncFailed" });
    }
    attempt.timer = window.setTimeout(confirmationFailed, CONFIRMATION_TIMEOUT_MS);
    // The automatic reconnect can publish before the create reply arrives.
    try {
      await client.requestResync?.();
    } catch {
      confirmationFailed();
    }
  }

  return { create, confirm, pending: pendingClient === client };
}
