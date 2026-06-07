import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getScripts, getVersions } from "../api/client";
import type { ScriptSummary, TranslationVersionSummary } from "../api/types";

export function HistoryPage() {
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [versions, setVersions] = useState<Record<string, TranslationVersionSummary[]>>({});

  useEffect(() => {
    getScripts().then(async (items) => {
      setScripts(items);
      const pairs = await Promise.all(items.map(async (script) => [script.id, await getVersions(script.id)] as const));
      setVersions(Object.fromEntries(pairs));
    });
  }, []);

  return (
    <section className="stack">
      <div className="workspace-hero compact chrome-card">
        <div className="hero-copy">
          <p className="eyebrow">History</p>
          <h2>查看同一剧本的多模型版本</h2>
          <p className="hero-text">适合横向比较不同模型的口语风格、语气稳定性和成稿质量。</p>
        </div>
      </div>
      {scripts.map((script) => (
        <article key={script.id} className="panel">
          <div className="history-header">
            <div>
              <h3>{script.title}</h3>
              <p className="muted-text">
                {script.source_lang ?? "未知源语言"} · {script.version_count} 个版本
              </p>
            </div>
            <Link className="text-link" to={`/scripts/${script.id}`}>
              打开剧本
            </Link>
          </div>
          <div className="history-grid">
            {(versions[script.id] ?? []).map((version) => (
              <Link key={version.id} className="history-card" to={`/scripts/${script.id}?versionId=${version.id}`}>
                <strong>{version.model_provider}</strong>
                <span>{version.model_name}</span>
                <span>{version.target_lang}</span>
                <span>{version.status}</span>
              </Link>
            ))}
          </div>
        </article>
      ))}
    </section>
  );
}
