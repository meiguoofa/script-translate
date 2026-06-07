import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import {
  getDownloadUrl,
  getModels,
  getScript,
  getTranslation,
  getVersions,
  startTranslation,
} from "../api/client";
import type {
  ModelOption,
  ScriptDetail,
  TranslationDetail,
  TranslationVersionSummary,
} from "../api/types";
import { DownloadButton } from "../components/DownloadButton";
import { ModelSelector } from "../components/ModelSelector";
import { ScriptLineRow } from "../components/ScriptLineRow";
import { TranslationStatus } from "../components/TranslationStatus";
import { resolveInitialModelSelection, saveDoubaoModel } from "../modelPreferences";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";

const STATUS_DOT: Record<string, string> = {
  done: "bg-emerald-500",
  running: "bg-sky-500 animate-pulse",
  failed: "bg-destructive",
  pending: "bg-muted-foreground/40",
};

const STATUS_LABEL: Record<string, string> = {
  done: "已完成",
  running: "进行中",
  failed: "失败",
  pending: "等待中",
};

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

  useEffect(() => {
    getModels()
      .then((data) => {
        setModels(data);
        const initialSelection = resolveInitialModelSelection(data);
        if (initialSelection) {
          setProvider(initialSelection.provider);
          setModel(initialSelection.model);
          return;
        }
        toast.error("当前没有可用模型，请先在后端配置豆包或其他 Provider。");
      })
      .catch(() => {
        toast.error("模型列表加载失败，请检查后端 Provider 配置。");
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
    try {
      const next = await startTranslation(scriptId, { target_lang: targetLang, provider, model });
      setSearchParams({ versionId: next.version_id });
    } catch {
      toast.error("提交新版本失败，请重试。");
    } finally {
      setBusy(false);
    }
  }

  if (!script) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        加载剧本中…
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-2">
              <CardTitle className="break-words text-base">{script.title}</CardTitle>
              <Badge variant="outline" className="shrink-0">#{script.lines.length}</Badge>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            <DetailRow label="源语言" value={script.source_lang ?? "未知"} />
            <DetailRow label="输入方式" value={script.source_type} />
            <DetailRow label="总行数" value={String(script.lines.length)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">生成新版本</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>目标语言</Label>
              <Select value={targetLang} onValueChange={setTargetLang}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zh">中文</SelectItem>
                  <SelectItem value="en">英语</SelectItem>
                  <SelectItem value="th">泰语</SelectItem>
                  <SelectItem value="ar">阿拉伯语</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <ModelSelector
              models={models}
              provider={provider}
              model={model}
              onChange={(nextProvider, nextModel) => {
                setProvider(nextProvider);
                setModel(nextModel);
              }}
            />
            <Button onClick={handleRetranslate} disabled={busy || !provider || !model} className="w-full">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {busy ? "提交中…" : "生成新版本"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">历史版本</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无版本，提交一次翻译即可生成。</p>
            ) : (
              versions.map((item) => {
                const active = item.id === versionId;
                return (
                  <button
                    key={item.id}
                    onClick={() => setSearchParams({ versionId: item.id })}
                    className={cn(
                      "flex flex-col gap-1 rounded-md border px-3 py-2 text-left transition-colors",
                      active
                        ? "border-primary bg-accent/50"
                        : "border-border bg-card hover:border-primary/40 hover:bg-accent/30"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{item.model_provider}</span>
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[item.status] ?? "bg-muted-foreground/40")} />
                        {STATUS_LABEL[item.status] ?? item.status}
                      </span>
                    </div>
                    <span className="truncate text-xs text-muted-foreground">
                      {item.target_lang} · {item.model_name}
                    </span>
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>
      </aside>

      <Card className="min-w-0">
        <CardHeader className="flex-row items-start justify-between gap-4 space-y-0 border-b">
          <div className="min-w-0">
            <CardTitle className="truncate text-base">
              {translation ? `${translation.model_provider} · ${translation.model_name}` : "请选择一个版本"}
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              原文与译文以内联附注方式呈现，便于逐行审校。
            </p>
          </div>
          {translation ? (
            <div className="flex items-center gap-4">
              <TranslationStatus status={translation.status} errorMessage={translation.error_message} />
              <DownloadButton
                versionId={translation.id}
                href={getDownloadUrl(translation.id)}
                disabled={translation.status !== "done"}
              />
            </div>
          ) : null}
        </CardHeader>
        <CardContent className="pt-0">
          {!translation ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <p>请在左侧选择一个版本，或生成新版本以查看译文。</p>
            </div>
          ) : (
            <div className="flex flex-col gap-1 py-4">
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-medium">{value}</span>
    </div>
  );
}