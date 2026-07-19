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


// ===== 字幕擦除 + 翻译（IMS/ICE） =====

export type SubtitleEraseUploadEntry = {
  filename: string;
  presigned_url: string;
  public_url: string;
  oss_uri: string;
  key: string;
};

export type SubtitleEraseUploadUrlResponse = {
  job_id: string;
  expires_in: number;
  entries: SubtitleEraseUploadEntry[];
};

export type SubtitleEraseMultipartPartInfo = {
  part_number: number;
  offset: number;
  size: number;
  presigned_url: string;
};

export type SubtitleEraseMultipartUploadUrlResponse = {
  job_id: string;
  upload_id: string;
  key: string;
  oss_uri: string;
  public_url: string;
  part_size: number;
  parts: SubtitleEraseMultipartPartInfo[];
  expires_in: number;
};

export type SubtitleEraseCompleteMultipartInput = {
  job_id: string;
  key: string;
  upload_id: string;
  parts: { part_number: number; etag: string }[];
};

export type SubtitleEraseCompleteMultipartResponse = {
  public_url: string;
  oss_uri: string;
};

export type SubtitleEraseItemStage =
  | "pending"
  | "extracting"
  | "cleaning"
  | "translating"
  | "burning"
  | "done";

export type SubtitleEraseItemStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed";

export type SubtitleEraseTranslationItemOut = {
  translated_srt_oss_uri: string | null;
  translated_srt_public_url: string | null;
  output_video_oss_uri: string | null;
  output_public_url: string | null;
  translation_job_id: string | null;
  translation_status: string | null;
  mps_job_id: string | null;
  burn_ass_oss_uri: string | null;
  output_video_tos_uri: string | null;
  output_video_tos_public_url: string | null;
  output_video_bj_tos_uri: string | null;
  output_video_bj_tos_public_url: string | null;
  bj_fetch_error: string | null;
  stage: SubtitleEraseItemStage;
  status: SubtitleEraseItemStatus;
  error: string | null;
};

export type SubtitleEraseJobItemOut = {
  index: number;
  drama_index: number;
  episode_index: number;
  filename: string;
  input_oss_uri: string;
  input_public_url: string;
  // 跨语言共享产物(擦除 + 字幕提取)
  caption_job_id: string | null;
  caption_status: string | null;
  source_srt_oss_uri: string | null;
  source_srt_public_url: string | null;
  cleaned_srt_oss_uri: string | null;
  cleaned_srt_public_url: string | null;
  detext_job_id: string | null;
  detext_status: string | null;
  clean_video_oss_uri: string | null;
  clean_video_public_url: string | null;
  warning: string | null;
  // 每语言独立产物
  translations: Record<string, SubtitleEraseTranslationItemOut>;
  // item 级汇总状态
  stage: SubtitleEraseItemStage;
  status: SubtitleEraseItemStatus;
  error: string | null;
  // 视频时长(秒),ffprobe 探测后填充
  duration_seconds: number | null;
};

export type SubtitleEraseJobOut = {
  id: string;
  title: string;
  drama_count: number;
  video_count: number;
  detext_mode: "basic" | "advanced";
  translate_mode: "aliyun" | "llm";
  burn_mode: "local" | "aliyun" | "mps";
  placement_mode: "safe_bottom" | "simple_bottom";
  source_lang: string | null;
  target_langs: string[];
  model_provider: string | null;
  model_name: string | null;
  qps: number;
  caption_fps: number;
  caption_lang: string;
  caption_track: string;
  caption_roi: string | null;
  caption_sep: boolean;
  detext_limit_region: string | null;
  burn_font_size: number;
  burn_font_color: string;
  burn_font_color_opacity: number;
  burn_x: number;
  burn_y: number;
  burn_text_width: number;
  items: SubtitleEraseJobItemOut[];
  original_filenames: string[] | null;
  output_oss_prefix: string;
  output_tos_prefix: string | null;
  status: "pending" | "running" | "completed" | "failed";
  progress_message: string | null;
  error_message: string | null;
  succeeded_count: number;
  failed_count: number;
  detexted_count: number;
  captioned_count: number;
  total_duration_seconds: number;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type SubtitleEraseJobSummary = {
  id: string;
  title: string;
  drama_count: number;
  video_count: number;
  detext_mode: "basic" | "advanced";
  translate_mode: "aliyun" | "llm";
  burn_mode: "local" | "aliyun" | "mps";
  target_langs: string[];
  status: "pending" | "running" | "completed" | "failed";
  succeeded_count: number;
  failed_count: number;
  detexted_count: number;
  captioned_count: number;
  total_duration_seconds: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type SubtitleEraseJobItemInput = {
  filename: string;
  oss_uri: string;
  public_url: string;
  key?: string | null;
  drama_index?: number;
  episode_index?: number;
};

export type SubtitleEraseJobCreateInput = {
  job_id: string;
  title: string;
  detext_mode: "basic" | "advanced";
  translate_mode: "aliyun" | "llm";
  burn_mode: "local" | "aliyun" | "mps";
  placement_mode: "safe_bottom" | "simple_bottom";
  source_lang?: string | null;
  target_langs: string[];
  model_provider?: string | null;
  model_name?: string | null;
  qps: number;
  caption_fps: number;
  caption_lang: string;
  caption_track: string;
  caption_roi?: string | null;
  caption_sep: boolean;
  detext_limit_region?: string | null;
  burn_font_size: number;
  burn_font_color: string;
  burn_font_color_opacity: number;
  burn_x: number;
  burn_y: number;
  burn_text_width: number;
  items: SubtitleEraseJobItemInput[];
  original_filenames?: string[] | null;
};

export type SubtitleEraseRerunRequest = {
  detext_mode: "basic" | "advanced";
  translate_mode: "aliyun" | "llm";
  burn_mode: "local" | "aliyun" | "mps";
  placement_mode: "safe_bottom" | "simple_bottom";
  source_lang?: string | null;
  target_langs: string[];
  model_provider?: string | null;
  model_name?: string | null;
  qps: number;
  caption_fps: number;
  caption_lang: string;
  caption_track: string;
  caption_roi?: string | null;
  caption_sep: boolean;
  detext_limit_region?: string | null;
  burn_font_size: number;
  burn_font_color: string;
  burn_font_color_opacity: number;
  burn_x: number;
  burn_y: number;
  burn_text_width: number;
  // 强制重做共享阶段(默认 false,自动复用已成功产物)
  force_redetext?: boolean;
  force_recaption?: boolean;
};


// ===== 百度云 VOD 视频翻译(字幕擦除 + 翻译 + 语音翻译)=====

export type BaiduVodUploadEntry = {
  filename: string;
  presigned_url: string;
  public_url: string;
  bos_uri: string;
  key: string;
};

export type BaiduVodUploadUrlResponse = {
  job_id: string;
  expires_in: number;
  entries: BaiduVodUploadEntry[];
};

export type BaiduVodMultipartPartInfo = {
  part_number: number;
  offset: number;
  size: number;
  presigned_url: string;
};

export type BaiduVodMultipartUploadUrlResponse = {
  job_id: string;
  upload_id: string;
  key: string;
  bos_uri: string;
  public_url: string;
  part_size: number;
  parts: BaiduVodMultipartPartInfo[];
  expires_in: number;
};

export type BaiduVodCompletePart = {
  part_number: number;
  etag: string;
};

export type BaiduVodCompleteMultipartInput = {
  job_id: string;
  key: string;
  upload_id: string;
  parts: BaiduVodCompletePart[];
};

export type BaiduVodCompleteMultipartResponse = {
  public_url: string;
  bos_uri: string;
};

export type BaiduVodJobItemInput = {
  filename: string;
  oss_uri: string;
  public_url: string;
  key?: string | null;
  drama_index?: number;
  episode_index?: number;
};

export type BaiduVodOcrArea = {
  x: number;
  y: number;
  width: number;
  height: number;
  start?: number;
};

export type BaiduVodFontConfig = {
  family: string;
  alignment: string;
  size: number;
  bold: boolean;
  color: string;
  outline_thickness: number;
  outline_color: string;
  padding: number;
};

export type BaiduVodJobCreateInput = {
  job_id: string;
  title: string;
  project_type: "ShortSeries" | "Ecommerce";
  source_language: string;
  target_langs: string[];
  translation_type_list: string[];
  voice_mode?: string | null;
  recognition_type: string;
  text_type_list: string[];
  target_subtitle_compose: boolean;
  desubtitle_enabled: boolean;
  desubtitle_model: string;
  desubtitle_type: string;
  ocr_area_list?: BaiduVodOcrArea[] | null;
  font_config: BaiduVodFontConfig;
  items: BaiduVodJobItemInput[];
  original_filenames?: string[] | null;
};

export type BaiduVodRerunRequest = {
  project_type: "ShortSeries" | "Ecommerce";
  source_language: string;
  target_langs: string[];
  translation_type_list: string[];
  voice_mode?: string | null;
  recognition_type: string;
  text_type_list: string[];
  target_subtitle_compose: boolean;
  desubtitle_enabled: boolean;
  desubtitle_model: string;
  desubtitle_type: string;
  ocr_area_list?: BaiduVodOcrArea[] | null;
  font_config: BaiduVodFontConfig;
  force_reregister?: boolean;
};

export type BaiduVodRuntimeLimits = {
  global_qps: number;
  max_concurrent_jobs: number;
  max_concurrent_episodes: number;
};

export type BaiduVodTranslationItemOut = {
  baidu_task_id: string | null;
  status: string;
  stage: string;
  error: string | null;
  final_video_url: string | null;
  desubtitle_video_url: string | null;
  cover_url: string | null;
  source_srt_url: string | null;
  target_srt_url: string | null;
};

export type BaiduVodJobItemOut = {
  index: number;
  drama_index: number;
  episode_index: number;
  filename: string;
  input_oss_uri: string;
  input_public_url: string;
  input_bos_key: string | null;
  input_bos_uri: string | null;
  baidu_media_id: string | null;
  baidu_upload_task_id: string | null;
  duration_seconds: number | null;
  warning: string | null;
  translations: Record<string, BaiduVodTranslationItemOut>;
  stage: string;
  status: string;
  error: string | null;
};

export type BaiduVodJobOut = {
  id: string;
  title: string;
  drama_count: number;
  video_count: number;
  baidu_project_id: string | null;
  project_type: "ShortSeries" | "Ecommerce";
  source_language: string;
  target_langs: string[];
  translation_config: Record<string, unknown>;
  subtitle_config: Record<string, unknown>;
  qps: number;
  items: BaiduVodJobItemOut[];
  original_filenames: string[] | null;
  output_bos_prefix: string;
  status: "pending" | "running" | "completed" | "failed";
  progress_message: string | null;
  error_message: string | null;
  succeeded_count: number;
  failed_count: number;
  registered_count: number;
  total_duration_seconds: number;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BaiduVodJobSummary = {
  id: string;
  title: string;
  drama_count: number;
  video_count: number;
  project_type: "ShortSeries" | "Ecommerce";
  source_language: string;
  target_langs: string[];
  status: "pending" | "running" | "completed" | "failed";
  succeeded_count: number;
  failed_count: number;
  registered_count: number;
  total_duration_seconds: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};
