export type ModelOption = {
  provider: string;
  name: string;
  label: string;
  target_langs: string[];
  default: boolean;
};

export type ScriptLine = {
  id: string;
  line_no: number;
  raw_line: string;
  speaker: string | null;
  parenthetical: string | null;
  dialogue: string | null;
  is_dialogue: boolean;
};

export type ScriptSummary = {
  id: string;
  title: string;
  source_lang: string | null;
  source_type: string;
  created_at: string;
  version_count: number;
};

export type ScriptDetail = {
  id: string;
  title: string;
  source_lang: string | null;
  source_type: string;
  created_at: string;
  lines: ScriptLine[];
};

export type TranslationVersionSummary = {
  id: string;
  target_lang: string;
  model_provider: string;
  model_name: string;
  status: string;
  created_at: string;
  error_message: string | null;
};

export type TranslationDetail = {
  id: string;
  script_id: string;
  target_lang: string;
  model_provider: string;
  model_name: string;
  status: string;
  prompt_version: string;
  total_tokens: number | null;
  cost: number | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
  rendered_lines: string[];
};

export type ScriptCreateResponse = {
  script_id: string;
  title: string;
  line_count: number;
  source_lang: string | null;
};

export type CleanedScriptCreateResponse = {
  id: string;
  title: string;
  source_filename: string | null;
  output_filename: string;
  line_count: number;
  stripped_count: number;
  created_at: string;
};

export type CleanedScriptSummary = CleanedScriptCreateResponse;

export type CleanedScriptDetail = CleanedScriptSummary & {
  cleaned_preview: string[];
};

export type AccessVerifyResponse = {
  ok: boolean;
};

export type PromptTemplateOut = {
  id: string;
  name: string;
  content: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
};

export type VideoUploadEntry = {
  filename: string;
  presigned_url: string;
  public_url: string;
  tos_uri: string;
  key: string;
};

export type VideoUploadUrlResponse = {
  job_id: string;
  expires_in: number;
  entries: VideoUploadEntry[];
};

export type VideoJobStatus =
  | "pending"
  | "submitted"
  | "running"
  | "completed"
  | "failed";

export type VideoJobOut = {
  id: string;
  title: string;
  video_count: number;
  video_urls: string[];
  original_filenames: string[] | null;
  prompt_template_id: string | null;
  prompt_template_name: string | null;
  output_tos_path: string | null;
  las_task_id: string | null;
  status: VideoJobStatus;
  progress_message: string | null;
  error_message: string | null;
  generated_script_id: string | null;
  generated_script_preview: string[] | null;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type VideoJobSummary = {
  id: string;
  title: string;
  video_count: number;
  prompt_template_name: string | null;
  status: VideoJobStatus;
  generated_script_id: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

// ===== 视频超分辨 =====

export type SuperResUploadEntry = {
  filename: string;
  presigned_url: string;
  public_url: string;
  oss_uri: string;
  key: string;
};

export type SuperResUploadUrlResponse = {
  job_id: string;
  expires_in: number;
  entries: SuperResUploadEntry[];
};

export type SuperResItemStatus = "pending" | "running" | "succeeded" | "failed";

export type SuperResJobStatus = "pending" | "running" | "completed" | "failed";

export type SuperResJobItemOut = {
  index: number;
  filename: string;
  input_oss_uri: string;
  input_public_url: string;
  viapi_job_id: string | null;
  viapi_status: string | null;
  raw_output_url: string | null;
  output_oss_uri: string | null;
  output_public_url: string | null;
  status: SuperResItemStatus;
  error: string | null;
};

export type SuperResJobOut = {
  id: string;
  title: string;
  video_count: number;
  bit_rate: number;
  items: SuperResJobItemOut[];
  original_filenames: string[] | null;
  output_oss_prefix: string;
  status: SuperResJobStatus;
  progress_message: string | null;
  error_message: string | null;
  succeeded_count: number;
  failed_count: number;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type SuperResJobSummary = {
  id: string;
  title: string;
  video_count: number;
  bit_rate: number;
  status: SuperResJobStatus;
  succeeded_count: number;
  failed_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

// ===== 视频字幕提取-翻译-合并 =====

export type SubtitleUploadEntry = {
  filename: string;
  // 阿里云上海 OSS（VIAPI 用）
  oss_presigned_url: string;
  oss_public_url: string;
  oss_uri: string;
  oss_key: string;
  // 新加坡 TOS（烧录源 + 产物）
  tos_presigned_url: string;
  tos_public_url: string;
  tos_uri: string;
  tos_key: string;
};

export type SubtitleUploadUrlResponse = {
  job_id: string;
  expires_in: number;
  entries: SubtitleUploadEntry[];
};

export type SubtitleItemStatus =
  | "pending"
  | "extracting"
  | "extracted"
  | "translating"
  | "translated"
  | "burning"
  | "succeeded"
  | "failed";

export type SubtitleJobStatus = "pending" | "running" | "completed" | "failed";

export type SubtitleJobItemOut = {
  index: number;
  filename: string;
  input_oss_uri: string;
  input_oss_public_url: string;
  input_tos_uri: string;
  input_tos_public_url: string;
  viapi_job_id: string | null;
  viapi_status: string | null;
  srt_tos_uri: string | null;
  srt_tos_public_url: string | null;
  translated_srt_tos_uri: string | null;
  translated_srt_tos_public_url: string | null;
  output_video_tos_uri: string | null;
  output_video_tos_public_url: string | null;
  status: SubtitleItemStatus;
  error: string | null;
};

export type SubtitleJobOut = {
  id: string;
  title: string;
  video_count: number;
  subtitle_source: string;
  enable_translate: boolean;
  enable_burn: boolean;
  placement_mode: string;
  target_lang: string | null;
  model_provider: string | null;
  model_name: string | null;
  items: SubtitleJobItemOut[];
  original_filenames: string[] | null;
  output_tos_prefix: string;
  status: SubtitleJobStatus;
  progress_message: string | null;
  error_message: string | null;
  succeeded_count: number;
  failed_count: number;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type SubtitleJobSummary = {
  id: string;
  title: string;
  video_count: number;
  subtitle_source: string;
  enable_translate: boolean;
  enable_burn: boolean;
  status: SubtitleJobStatus;
  succeeded_count: number;
  failed_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};
