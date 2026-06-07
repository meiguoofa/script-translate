import type { ModelOption } from "./api/types";

const DOUBAO_MODEL_STORAGE_KEY = "script-translate.doubao-model";

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getSavedDoubaoModel(): string | null {
  if (!canUseStorage()) {
    return null;
  }

  return window.localStorage.getItem(DOUBAO_MODEL_STORAGE_KEY);
}

export function saveDoubaoModel(provider: string, model: string) {
  if (!canUseStorage() || provider !== "doubao" || !model) {
    return;
  }

  window.localStorage.setItem(DOUBAO_MODEL_STORAGE_KEY, model);
}

export function resolveInitialModelSelection(models: ModelOption[]) {
  const savedDoubaoModel = getSavedDoubaoModel();
  const savedDoubaoOption = savedDoubaoModel
    ? models.find((item) => item.provider === "doubao" && item.name === savedDoubaoModel)
    : undefined;

  if (savedDoubaoOption) {
    return {
      provider: savedDoubaoOption.provider,
      model: savedDoubaoOption.name,
    };
  }

  const defaultOption = models.find((item) => item.default) ?? models[0];
  if (!defaultOption) {
    return null;
  }

  return {
    provider: defaultOption.provider,
    model: defaultOption.name,
  };
}
