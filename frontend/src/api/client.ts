import axios from "axios";
import type {
  ModelOption,
  ScriptCreateResponse,
  ScriptDetail,
  ScriptSummary,
  TranslationDetail,
  TranslationVersionSummary,
} from "./types";

const client = axios.create({
  baseURL: "/api",
});

export async function getModels() {
  const response = await client.get<ModelOption[]>("/models");
  return response.data;
}

export async function createScript(formData: FormData) {
  const response = await client.post<ScriptCreateResponse>("/scripts", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

export async function getScripts() {
  const response = await client.get<ScriptSummary[]>("/scripts");
  return response.data;
}

export async function getScript(scriptId: string) {
  const response = await client.get<ScriptDetail>(`/scripts/${scriptId}`);
  return response.data;
}

export async function getVersions(scriptId: string) {
  const response = await client.get<TranslationVersionSummary[]>(`/scripts/${scriptId}/versions`);
  return response.data;
}

export async function startTranslation(scriptId: string, payload: { target_lang: string; provider: string; model: string }) {
  const response = await client.post<{ version_id: string; status: string }>(`/scripts/${scriptId}/translate`, payload);
  return response.data;
}

export async function getTranslation(versionId: string) {
  const response = await client.get<TranslationDetail>(`/translations/${versionId}`);
  return response.data;
}

export function getDownloadUrl(versionId: string) {
  return `/api/translations/${versionId}/download`;
}
