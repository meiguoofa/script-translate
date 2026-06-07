import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createScript, getModels, startTranslation } from "../api/client";
import type { ModelOption } from "../api/types";
import { Dropzone } from "../components/Dropzone";
import { ModelSelector } from "../components/ModelSelector";
import { resolveInitialModelSelection, saveDoubaoModel } from "../modelPreferences";

const TARGET_LANG_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英语" },
  { value: "th", label: "泰语" },
  { value: "ar", label: "阿拉伯语" },
];

export function UploadPage() {
  const navigate = useNavigate();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rawText, setRawText] = useState("");
  const [targetLang, setTargetLang] = useState("zh");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getModels()
      .then((data) => {
        setModels(data);
        const initialSelection = resolveInitialModelSelection(data);
        if (initialSelection) {
          setProvider(initialSelection.provider);
          setModel(initialSelection.model);
          setError(null);
          return;
        }
        setError("当前没有可用模型，请先在后端配置豆包或其他 Provider。");
      })
      .catch(() => {
        setError("模型列表加载失败，请检查后端 Provider 配置。");
      });
  }, []);

  useEffect(() => {
    saveDoubaoModel(provider, model);
  }, [provider, model]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("title", title);
      if (file) {
        formData.append("file", file);
      } else {
        formData.append("raw_text", rawText);
      }

      const script = await createScript(formData);
      const translation = await startTranslation(script.script_id, {
        target_lang: targetLang,
        provider,
        model,
      });
      navigate(`/scripts/${script.script_id}?versionId=${translation.version_id}`);
    } catch (requestError) {
      setError("上传或翻译启动失败，请检查输入后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="stack">
      <div className="workspace-hero chrome-card">
        <div className="hero-copy">
          <p className="eyebrow">New Translation</p>
          <h2>把剧本翻译流程压缩成一个工作台</h2>
          <p className="hero-text">
            同时保留原文与口语化译文，适合短剧编剧、翻译和审校直接逐行对照处理。
          </p>
        </div>
        <div className="hero-metrics" aria-label="功能概览">
          <div className="metric-card">
            <strong>3 种输入</strong>
            <span>doc / docx / 纯文本</span>
          </div>
          <div className="metric-card">
            <strong>多模型切换</strong>
            <span>按豆包 API 可用模型即时切换</span>
          </div>
          <div className="metric-card">
            <strong>行内对照</strong>
            <span>原文与译文同屏查看与导出</span>
          </div>
        </div>
      </div>

      <div className="upload-layout">
      <form className="panel" onSubmit={handleSubmit}>
        <div className="panel-head">
          <div>
            <p className="eyebrow">Source Input</p>
            <h3>导入剧本</h3>
          </div>
          <span className="panel-tag">步骤 1 / 1</span>
        </div>

        <div className="field-group">
          <label>
            <span>剧本标题</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：火花瞬间燃点" required />
          </label>
          <Dropzone file={file} onFileChange={setFile} />
          <label>
            <span>纯文本剧本</span>
            <textarea
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              placeholder="如果不上传文件，可以直接粘贴剧本文本。"
              rows={10}
              disabled={Boolean(file)}
            />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <span>目标语言</span>
            <select value={targetLang} onChange={(event) => setTargetLang(event.target.value)}>
              {TARGET_LANG_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <ModelSelector
            models={models}
            provider={provider}
            model={model}
            onChange={(nextProvider, nextModel) => {
              setProvider(nextProvider);
              setModel(nextModel);
            }}
          />
        </div>

        {error ? <p className="error-text">{error}</p> : null}
        <button className="primary-button" type="submit" disabled={submitting || !provider || !model || (!file && !rawText.trim())}>
          {submitting ? "处理中..." : "开始翻译"}
        </button>
      </form>

      <aside className="stack">
        <div className="panel utility-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Current Setup</p>
              <h3>本次任务配置</h3>
            </div>
          </div>
          <div className="detail-list">
            <div className="detail-item">
              <span>输入源</span>
              <strong>{file ? "文件上传" : "纯文本粘贴"}</strong>
            </div>
            <div className="detail-item">
              <span>目标语言</span>
              <strong>{TARGET_LANG_OPTIONS.find((option) => option.value === targetLang)?.label ?? targetLang}</strong>
            </div>
            <div className="detail-item">
              <span>模型厂商</span>
              <strong>{provider || "未选择"}</strong>
            </div>
            <div className="detail-item">
              <span>模型名称</span>
              <strong>{model || "未选择"}</strong>
            </div>
          </div>
        </div>

        <div className="panel utility-panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Workflow</p>
              <h3>处理流程</h3>
            </div>
          </div>
          <ol className="workflow-list">
            <li>导入剧本并识别对话行</li>
            <li>按模型批量翻译人物对白</li>
            <li>在预览页逐行核对并导出 docx</li>
          </ol>
        </div>
      </aside>
      </div>
    </section>
  );
}
