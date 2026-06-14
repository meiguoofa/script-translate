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
