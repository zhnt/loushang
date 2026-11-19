import { useEffect, useState } from "react";
import type { SessionModels } from "./client/model";
import type { DraftTarget } from "./useSessionCreation";

function draftModelLabel(load: DraftTarget["loadModels"], loaded: boolean, models: SessionModels | null) {
  if (!load) return "default";
  if (!loaded) return "loading";
  if (!models) return "unavailable";
  return models.models.length === 0 ? "empty" : "choose";
}

async function loadDraftCatalog(load: NonNullable<DraftTarget["loadModels"]>): Promise<SessionModels> {
  const catalog = await load();
  const selected = catalog.models.find((model) => model.id === catalog.currentId);
  if (!selected?.supportsThinking || catalog.thinking) return catalog;
  const preview = await load(selected.id).catch(() => null);
  return preview?.currentId === selected.id ? { ...catalog, thinking: preview.thinking } : catalog;
}

export function useDraftModels(
  target: DraftTarget | undefined, available: boolean, preferredId?: string, thinking?: SessionModels["thinking"],
) {
  const [result, setResult] = useState<{ target: DraftTarget; models: SessionModels | null }>();
  const load = target?.loadModels;
  useEffect(() => {
    if (!target || !load || !available) {
      setResult(undefined);
      return;
    }
    let active = true;
    setResult(undefined);
    void loadDraftCatalog(load).then((models) => {
      if (active) setResult({ target, models });
    }, () => {
      if (active) setResult({ target, models: null });
    });
    return () => { active = false; };
  }, [target, load, available]);

  const current = available && result?.target === target ? result : undefined;
  const catalog = current?.models ?? null;
  const hasPreferred = catalog?.models.some((model) => model.id === preferredId);
  const models = preferredId && catalog
    ? { ...catalog, currentId: hasPreferred ? preferredId : null, thinking: hasPreferred ? thinking : undefined }
    : catalog;
  return {
    models,
    required: Boolean(load),
    label: draftModelLabel(load, Boolean(current), models),
  } as const;
}
