import { useEffect, useState } from "react";
import type { SessionModels } from "./client/model";
import type { DraftTarget } from "./useSessionCreation";

function draftModelLabel(load: DraftTarget["loadModels"], loaded: boolean, models: SessionModels | null) {
  if (!load) return "default";
  if (!loaded) return "loading";
  if (!models) return "unavailable";
  return models.models.length === 0 ? "empty" : "choose";
}

export function useDraftModels(target: DraftTarget | undefined, available: boolean) {
  const [result, setResult] = useState<{ target: DraftTarget; models: SessionModels | null }>();
  const load = target?.loadModels;
  useEffect(() => {
    if (!target || !load || !available) {
      setResult(undefined);
      return;
    }
    let active = true;
    setResult(undefined);
    void load().then((models) => {
      if (active) setResult({ target, models });
    }, () => {
      if (active) setResult({ target, models: null });
    });
    return () => { active = false; };
  }, [target, load, available]);

  const current = available && result?.target === target ? result : undefined;
  const models = current?.models ?? null;
  return {
    models,
    required: Boolean(load),
    label: draftModelLabel(load, Boolean(current), models),
    async select(id: string) {
      if (!current || !models?.models.some((model) => model.id === id)) return null;
      const next = { ...models, currentId: id };
      setResult({ ...current, models: next });
      return next;
    },
  } as const;
}
