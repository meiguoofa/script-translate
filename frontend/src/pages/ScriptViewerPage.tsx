import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useParams } from "react-router-dom";
import { getDownloadUrl, getModels, getScript, getTranslation, getVersions, startTranslation } from "../api/client";
import type { ModelOption, ScriptDetail, TranslationDetail, TranslationVersionSummary } from "../api/types";
import { DownloadButton } from "../components/DownloadButton";
import { ModelSelector } from "../components/ModelSelector";
import { ScriptLineRow } from "../components/ScriptLineRow";
import { TranslationStatus } from "../components/TranslationStatus";
import { resolveInitialModelSelection, saveDoubaoModel } from "../modelPreferences";

export function ScriptViewerPage() {
  const { scriptId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const versionId = searchParams.get("versionId");
  const [script, setScript] = useState<ScriptDetail | null>(null);
  const [translation, setTranslation] = useState<TranslationDetail | null>(null);
  const [versions, setVersions] = useState<TranslationVersionSummary[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [targetLang, setTargetLang] = useState("zh");
  const [busy, setBusy] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  useEffect(() => {
    getModels()
      .then((data) => {
        setModels(data);
        const initialSelection = resolveInitialModelSelection(data);
        if (initialSelection) {
          setProvider(initialSelection.provider);
          setModel(initialSelection.model);
          setModelError(null);
          return;
        }
        setModelError("当前没有可用模型，请先在后端配置豆包或其他 Provider。");
      })
      .catch(() => {
        setModelError("模型列表加载失败，请检查后端 Provider 配置。");
      });
  }, []);

  useEffect(() => {
    saveDoubaoModel(provider, model);
  }, [provider, model]);

  useEffect(() => {
    getScript(scriptId).then(setScript);
    getVersions(scriptId).then(setVersions);
  }, [scriptId]);

  useEffect(() => {
    if (!versionId) {
      setTranslation(null);
      return;
    }

    const activeVersionId = versionId;
    let cancelled = false;
    let timer: number | undefined;

    async function load() {
      const payload = await getTranslation(activeVersionId);
      if (cancelled) {
        return;
      }
      setTranslation(payload);
      if (payload.status === "running") {
        timer = window.setTimeout(load, 2000);
      } else {
        getVersions(scriptId).then(setVersions);
      }
    }

    load();
    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [scriptId, versionId]);

  const renderedMap = useMemo(() => {
    if (!script || !translation) {
      return new Map<number, string>();
    }
    const map = new Map<number, string>();
    script.lines.forEach((line, index) => {
      map.set(line.line_no, translation.rendered_lines[index] ?? line.raw_line);
    });
    return map;
  }, [script, translation]);

  async function handleRetranslate() {
    setBusy(true);
    const next = await startTranslation(scriptId, { target_lang: targetLang, provider, model });
    setSearchParams({ versionId: next.version_id });
    setBusy(false);
  }

  if (!script) {
    return <div className="panel">加载中...</div>;
  }

  return (
    <div className="viewer-layout">
      <aside className="sidebar">
        <div className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Script Summary</p>
              <h2>{script.title}</h2>
            </div>
            <span className="panel-tag">#{script.lines.length}</span>
          </div>
          <div className="detail-list">
            <div className="detail-item">
              <span>源语言</span>
              <strong>{script.source_lang ?? "未知"}</strong>
            </div>
            <div className="detail-item">
              <span>输入方式</span>
              <strong>{script.source_type}</strong>
            </div>
            <div className="detail-item">
              <span>总行数</span>
              <strong>{script.lines.length}</strong>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">New Version</p>
              <h3>生成新版本</h3>
            </div>
          </div>
          <label>
            <span>目标语言</span>
            <select value={targetLang} onChange={(event) => setTargetLang(event.target.value)}>
              <option value="zh">中文</option>
              <option value="en">英语</option>
              <option value="th">泰语</option>
              <option value="ar">阿拉伯语</option>
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
          {modelError ? <p className="error-text">{modelError}</p> : null}
          <button className="primary-button" onClick={handleRetranslate} disabled={busy || !provider || !model}>
            {busy ? "提交中..." : "生成新版本"}
          </button>
        </div>

        <div className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Version History</p>
              <h3>历史版本</h3>
            </div>
          </div>
          <div className="version-list">
            {versions.map((item) => (
              <button
                key={item.id}
                className={`version-item ${item.id === versionId ? "is-active" : ""}`}
                onClick={() => setSearchParams({ versionId: item.id })}
              >
                <strong>{item.model_provider}</strong>
                <span>{item.target_lang} / {item.model_name}</span>
                <span>{item.status}</span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <section className="panel viewer-panel">
        <div className="viewer-toolbar">
          <div>
            <p className="eyebrow">行内对照预览</p>
            <h3>{translation ? `${translation.model_provider} · ${translation.model_name}` : "请选择一个版本"}</h3>
            <p className="muted-text">对白保留原文，译文以内联附注方式呈现，便于逐行审校。</p>
          </div>
          {translation ? (
            <div className="toolbar-actions">
              <TranslationStatus status={translation.status} errorMessage={translation.error_message} />
              <DownloadButton
                versionId={translation.id}
                href={getDownloadUrl(translation.id)}
                disabled={translation.status !== "done"}
              />
            </div>
          ) : null}
        </div>
        <div className="script-lines">
          {script.lines.map((line) => (
            <ScriptLineRow
              key={line.id}
              lineNo={line.line_no}
              rawLine={line.raw_line}
              renderedLine={renderedMap.get(line.line_no)}
              isDialogue={line.is_dialogue}
            />
          ))}
        </div>
      </section>
    </div>
  );
}
