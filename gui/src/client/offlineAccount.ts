import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { sharedSettings } from "./hostApi";

export interface OfflineAccount {
  readonly name: string;
  readonly id: string | null;
}

export function useOfflineAccount(): OfflineAccount | null {
  const [account, setAccount] = useState<OfflineAccount | null>(null);
  useEffect(() => {
    let active = true;
    const request = isTauri() ? invoke<OfflineAccount | null>("offline_account") : sharedSettings<OfflineAccount | null>({ operation: "account" });
    void request.then((value) => {
      if (active && typeof value?.name === "string" && value.name.trim()) {
        setAccount({ name: value.name, id: typeof value.id === "string" ? value.id : null });
      }
    }).catch(() => { /* An unavailable OS identity leaves the profile blank. */ });
    return () => { active = false; };
  }, []);
  return account;
}
