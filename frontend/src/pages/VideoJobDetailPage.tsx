import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Download, Loader2, RefreshCw, XCircle } from "lucide-react";
import { getModels, getScriptDownloadUrl, getVideoJob, startTranslation } from "@/api/client";
import type { ModelOption, VideoJobOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ModelSelector } from "@/components/ModelSelector";
import { toast } from "@/components/ui/sonner";
import { resolveInitialModelSelection, saveDoubaoModel } from "@/modelPreferences";

const TARGET_LANG_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英语" },
  { value: "th", label: "泰语" },
  { value: "ar", label: "阿拉伯语" },
];

const STATUS_BADGE: Record<
  VideoJobOut["status"],
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "排队中", variant: "muted" },
  submitted: { label: "已提交 LAS", variant: "info" },
  running: { label: "生成中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

export function VideoJobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<VideoJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [targetLang, setTargetLang] = useState("zh");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [translating, setTranslating] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    getModels()
      .then((data) => {
        setModels(data);
        const initial = resolveInitialModelSelection(data);
        if (initial) {
          setProvider(initial.provider);
          setModel(initial.model);
        }
      })
      .catch(() => {
        /* ignore — translation panel will show no models */
      });
  }, []);

  useEffect(() => {
    saveDoubaoModel(provider, model);
  }, [provider, model]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    async function poll() {
      try {
        const data = await getVideoJob(jobId!);
        if (cancelled) return;
        setJob(data);
        setError(null);
        if (data.status !== "completed" && data.status !== "failed") {
          timer.current = window.setTimeout(poll, 5000);
        }
      } catch {
        if (cancelled) return;
        setError("加载任务失败");
        timer.current = window.setTimeout(poll, 5000);
      }
    }

    poll();
    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [jobId]);

  async function handleStartTranslation() {
    if (!job?.generated_script_id || !provider || !model) return;
    setTranslating(true);
    try {
      const translation = await startTranslation(job.generated_script_id, {
        target_lang: targetLang,
        provider,
        model,
      });
      navigate(`/scripts/${job.generated_script_id}?versionId=${translation.version_id}`);
    } catch {
      toast.error("启动翻译失败");
    } finally {
      setTranslating(false);
    }
  }

  if (!job) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-10 text-muted-foreground">
          {error ? (
            <span className="text-sm">{error}</span>
          ) : (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">加载中…</span>
            </>
          )}
        </CardContent>
      </Card>
    );
  }

  const badge = STATUS_BADGE[job.status];
  const isTerminal = job.status === "completed" || job.status === "failed";

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-lg">
              {job.title}
              <Badge variant={badge.variant}>
                {job.status === "running" ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : null}
                {job.status === "completed" ? (
                  <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
                ) : null}
                {job.status === "failed" ? <XCircle className="mr-1 h-3.5 w-3.5" /> : null}
                {badge.label}
              </Badge>
            </CardTitle>
            <CardDescription>
              {job.video_count} 个视频 · 提示词「{job.prompt_template_name ?? "—"}」
            </CardDescription>
          </div>
          {!isTerminal ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <RefreshCw className="h-3 w-3" /> 自动刷新
            </span>
          ) : null}
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
          {job.progress_message ? <p>状态：{job.progress_message}</p> : null}
          {job.error_message ? (
            <p className="text-destructive">错误：{job.error_message}</p>
          ) : null}
          {job.las_task_id ? <p>LAS Task：{job.las_task_id}</p> : null}
          <p>创建于 {new Date(job.created_at).toLocaleString()}</p>
          {job.completed_at ? (
            <p>结束于 {new Date(job.completed_at).toLocaleString()}</p>
          ) : null}
        </CardContent>
      </Card>

      {job.status === "completed" && job.generated_script_id ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">剧本预览</CardTitle>
              <CardDescription>
                <div className="flex items-center gap-3">
                  <Link
                    className="underline hover:text-foreground"
                    to={`/scripts/${job.generated_script_id}`}
                  >
                    打开完整剧本
                  </Link>
                  <a
                    href={getScriptDownloadUrl(job.generated_script_id)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <Button size="sm" variant="secondary">
                      <Download className="mr-1 h-4 w-4" />
                      下载 Word
                    </Button>
                  </a>
                </div>
              </CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">
                {(job.generated_script_preview ?? []).join("\n")}
              </pre>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">开始翻译</CardTitle>
              <CardDescription>选择目标语言与模型，进入翻译流程。</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label>目标语言</Label>
                  <Select value={targetLang} onValueChange={setTargetLang}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TARGET_LANG_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <ModelSelector
                models={models}
                provider={provider}
                model={model}
                onChange={(p, m) => {
                  setProvider(p);
                  setModel(m);
                }}
              />
              <div className="flex justify-end">
                <Button
                  onClick={handleStartTranslation}
                  disabled={translating || !provider || !model}
                >
                  {translating ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  开始翻译
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      ) : null}

      {job.status === "failed" ? (
        <Card>
          <CardContent className="flex flex-col gap-3 py-6">
            <p className="text-sm text-destructive">
              生成失败：{job.error_message ?? "未知错误"}
            </p>
            <p className="text-xs text-muted-foreground">
              如需重新尝试，请回到「视频还原剧本」重新提交。
            </p>
            <div>
              <Button variant="secondary" onClick={() => navigate("/video-restore")}>
                返回上传页
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
