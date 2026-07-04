import axios from "axios";
import { toast } from "sonner";
import { clearPassphrase, getPassphrase } from "@/lib/passphrase";
import type {
  AccessVerifyResponse,
  CleanedScriptCreateResponse,
  CleanedScriptDetail,
  CleanedScriptSummary,
  ModelOption,
  PromptTemplateOut,
  ScriptCreateResponse,
  ScriptDetail,
  ScriptSummary,
  SubtitleEraseJobCreateInput,
  SubtitleEraseJobOut,
  SubtitleEraseJobSummary,
  SubtitleEraseUploadUrlResponse,
  SubtitleJobOut,
  SubtitleJobSummary,
  SubtitleUploadUrlResponse,
  SuperResJobOut,
  SuperResJobSummary,
  SuperResUploadUrlResponse,
  TranslationDetail,
  TranslationVersionSummary,
  VideoJobOut,
  VideoJobSummary,
  VideoUploadUrlResponse,
} from "./types";

const client = axios.create({
  baseURL: "/api",
});

client.interceptors.request.use((config) => {
  const passphrase = getPassphrase();
  if (passphrase) {
    config.headers = config.headers ?? {};
    (config.headers as Record<string, string>)["X-Access-Passphrase"] = passphrase;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      const url: string = error?.config?.url ?? "";
      if (!url.includes("/access/verify")) {
        clearPassphrase();
        toast.error("访问密钥无效或已过期，请重新输入");
      }
    }
    return Promise.reject(error);
  }
);

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

export async function createCleanedScript(formData: FormData) {
  const response = await client.post<CleanedScriptCreateResponse>("/cleaned-scripts", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

export async function getCleanedScripts() {
  const response = await client.get<CleanedScriptSummary[]>("/cleaned-scripts");
  return response.data;
}

export async function getCleanedScript(id: string) {
  const response = await client.get<CleanedScriptDetail>(`/cleaned-scripts/${id}`);
  return response.data;
}

export function getCleanedScriptDownloadUrl(id: string) {
  return `/api/cleaned-scripts/${id}/download`;
}

export function getScriptDownloadUrl(scriptId: string) {
  return `/api/scripts/${scriptId}/download`;
}

export async function verifyPassphrase(passphrase: string) {
  const response = await client.post<AccessVerifyResponse>("/access/verify", { passphrase });
  return response.data;
}

export async function listPromptTemplates() {
  const response = await client.get<PromptTemplateOut[]>("/prompt-templates");
  return response.data;
}

export async function createPromptTemplate(payload: { name: string; content: string }) {
  const response = await client.post<PromptTemplateOut>("/prompt-templates", payload);
  return response.data;
}

export async function updatePromptTemplate(
  id: string,
  payload: { name?: string; content?: string }
) {
  const response = await client.put<PromptTemplateOut>(`/prompt-templates/${id}`, payload);
  return response.data;
}

export type VideoUploadUrlInput = {
  files: { filename: string; content_type: string }[];
};

export async function requestVideoUploadUrls(payload: VideoUploadUrlInput) {
  const response = await client.post<VideoUploadUrlResponse>("/video-jobs/upload-url", payload);
  return response.data;
}

export type VideoJobCreateInput = {
  job_id: string;
  title: string;
  video_urls: string[];
  original_filenames?: string[];
  prompt_template_id: string;
};

export async function createVideoJob(payload: VideoJobCreateInput) {
  const response = await client.post<VideoJobOut>("/video-jobs", payload);
  return response.data;
}

export async function getVideoJob(jobId: string) {
  const response = await client.get<VideoJobOut>(`/video-jobs/${jobId}`);
  return response.data;
}

export async function listVideoJobs(params?: { limit?: number; offset?: number }) {
  const response = await client.get<VideoJobSummary[]>("/video-jobs", { params });
  return response.data;
}

// ===== 视频超分辨 =====

export type SuperResUploadUrlInput = {
  files: { filename: string; content_type: string }[];
};

export async function requestSuperResUploadUrls(payload: SuperResUploadUrlInput) {
  const response = await client.post<SuperResUploadUrlResponse>(
    "/super-resolution/upload-url",
    payload
  );
  return response.data;
}

export type SuperResJobItemInput = {
  filename: string;
  oss_uri: string;
  public_url: string;
  key: string;
};

export type SuperResJobCreateInput = {
  job_id: string;
  title: string;
  bit_rate: number;
  items: SuperResJobItemInput[];
  original_filenames?: string[];
};

export async function createSuperResJob(payload: SuperResJobCreateInput) {
  const response = await client.post<SuperResJobOut>("/super-resolution", payload);
  return response.data;
}

export async function getSuperResJob(jobId: string) {
  const response = await client.get<SuperResJobOut>(`/super-resolution/${jobId}`);
  return response.data;
}

export async function retrySuperResJob(jobId: string) {
  const response = await client.post<SuperResJobOut>(`/super-resolution/${jobId}/retry`);
  return response.data;
}

export async function listSuperResJobs(params?: { limit?: number; offset?: number }) {
  const response = await client.get<SuperResJobSummary[]>("/super-resolution", { params });
  return response.data;
}

// ===== 视频字幕提取-翻译-合并 =====

export type SubtitleUploadUrlInput = {
  files: { filename: string; content_type: string }[];
};

export async function requestSubtitleUploadUrls(payload: SubtitleUploadUrlInput) {
  const response = await client.post<SubtitleUploadUrlResponse>(
    "/subtitle/upload-url",
    payload
  );
  return response.data;
}

export type SubtitleJobItemInput = {
  filename: string;
  oss_uri: string;
  oss_public_url: string;
  oss_key: string;
  tos_uri: string;
  tos_public_url: string;
  tos_key: string;
};

export type SubtitleJobCreateInput = {
  job_id: string;
  title: string;
  subtitle_source: string;
  enable_translate: boolean;
  enable_burn: boolean;
  placement_mode: string;
  target_lang?: string | null;
  model_provider?: string | null;
  model_name?: string | null;
  items: SubtitleJobItemInput[];
  original_filenames?: string[];
};

export async function createSubtitleJob(payload: SubtitleJobCreateInput) {
  const response = await client.post<SubtitleJobOut>("/subtitle", payload);
  return response.data;
}

export async function getSubtitleJob(jobId: string) {
  const response = await client.get<SubtitleJobOut>(`/subtitle/${jobId}`);
  return response.data;
}

export async function retrySubtitleJob(jobId: string) {
  const response = await client.post<SubtitleJobOut>(`/subtitle/${jobId}/retry`);
  return response.data;
}

export async function listSubtitleJobs(params?: { limit?: number; offset?: number }) {
  const response = await client.get<SubtitleJobSummary[]>("/subtitle", { params });
  return response.data;
}

// ===== 字幕擦除 + 翻译（IMS/ICE） =====

export type SubtitleEraseUploadUrlInput = {
  files: { filename: string; content_type: string }[];
};

export async function requestSubtitleEraseUploadUrls(payload: SubtitleEraseUploadUrlInput) {
  const response = await client.post<SubtitleEraseUploadUrlResponse>(
    "/subtitle-erase/upload-url",
    payload
  );
  return response.data;
}

export async function createSubtitleEraseJob(payload: SubtitleEraseJobCreateInput) {
  const response = await client.post<SubtitleEraseJobOut>("/subtitle-erase", payload);
  return response.data;
}

export async function getSubtitleEraseJob(jobId: string) {
  const response = await client.get<SubtitleEraseJobOut>(`/subtitle-erase/${jobId}`);
  return response.data;
}

export async function retrySubtitleEraseJob(jobId: string) {
  const response = await client.post<SubtitleEraseJobOut>(`/subtitle-erase/${jobId}/retry`);
  return response.data;
}

export async function listSubtitleEraseJobs(params?: { limit?: number; offset?: number }) {
  const response = await client.get<SubtitleEraseJobSummary[]>("/subtitle-erase", { params });
  return response.data;
}
