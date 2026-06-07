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
