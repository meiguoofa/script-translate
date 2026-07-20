import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Loader2,
  RotateCcw,
  Square,
  XCircle,
} from "lucide-react";
import {
  getStarlingDramaJob,
  retryStarlingDramaJob,
  stopStarlingDramaJob,
} from "@/api/client";
import type {
  StarlingDramaJobItemOut,
  StarlingDramaJobOut,
  StarlingDramaTranslationOut,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/sonner";

const JOB_BADGE: Record<
  StarlingDramaJobOut["status"],
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

const ITEM_BADGE: Record<
  string,
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "待处理", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  succeeded: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

function itemStatusBadge(status: string) {
  return ITEM_BADGE[status] ?? { label: status, variant: "muted" as const };
}

function artifactLabel(type: string): string {
  const map: Record<string, string> = {
    final_video: "成品视频",
    clean_video: "净版视频(擦除后)",
    origin_video: "原视频",
    dubbed_audio: "配音音频",
    source_subtitle: "源字幕",
    target_subtitle: "目标字幕",
  };
  return map[type] ?? type;
}

function triggerBrowserDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export function StarlingDramaDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<StarlingDramaJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    async function poll() {
      try {
        const data = await getStarlingDramaJob(jobId!);
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

  async function handleStop() {
    if (!jobId || !job) return;
    setStopping(true);
    try {
      const updated = await stopStarlingDramaJob(jobId);
      setJob(updated);
      toast.success("已请求停止任务");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "停止失败");
    } finally {
      setStopping(false);
    }
  }

  async function handleRetry() {
    if (!jobId || !job) return;
    setRetrying(true);
    try {
      const updated = await retryStarlingDramaJob(jobId, {});
      setJob(updated);
      toast.success("已请求重试失败子任务");
      // 重启轮询
      if (timer.current) window.clearTimeout(timer.current);
      setTimeout(() => window.location.reload(), 500);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "重试失败");
    } finally {
      setRetrying(false);
    }
  }

  if (error && !job) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-destructive">{error}</CardContent>
      </Card>
    );
  }

  if (!job) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  const isRunning = job.status === "pending" || job.status === "running";
  const hasFailedItems = job.items.some((it) => it.status === "failed");

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <CardTitle className="text-xl">{job.title}</CardTitle>
                <Badge variant={JOB_BADGE[job.status].variant}>
                  {JOB_BADGE[job.status].label}
                </Badge>
              </div>
              <CardDescription>
                {job.drama_name} · 源 {job.source_lang} -&gt; {job.target_langs.join(",")}
              </CardDescription>
            </div>
            <div className="flex shrink-0 gap-2">
              {isRunning ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleStop}
                  disabled={stopping}
                >
                  <Square className="mr-1 h-4 w-4" />
                  {stopping ? "停止中…" : "停止"}
                </Button>
              ) : null}
              {!isRunning && hasFailedItems ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRetry}
                  disabled={retrying}
                >
                  <RotateCcw className="mr-1 h-4 w-4" />
                  {retrying ? "重试中…" : "重试失败项"}
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate("/starling-drama/history")}
              >
                返回列表
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          {job.progress_message ? (
            <p className="text-muted-foreground">进度：{job.progress_message}</p>
          ) : null}
          <p className="text-muted-foreground">
            Starling Project: <code>{job.starling_project_id ?? "-"}</code> · Task:{" "}
            <code>{job.starling_task_id ?? "-"}</code>
          </p>
          <p className="text-muted-foreground">
            成功 {job.succeeded_count} · 失败 {job.failed_count} · 总 {job.items.length}
          </p>
          {job.error_message ? (
            <p className="text-destructive">{job.error_message}</p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>分集处理状态</CardTitle>
          <CardDescription>
            每集 × 每目标语言的子任务进度。点击「下载」获取对应产物。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {job.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无分集数据</p>
          ) : (
            job.items.map((it, idx) => (
              <ItemRow key={idx} item={it} targetLangs={job.target_langs} />
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ItemRow({
  item,
  targetLangs,
}: {
  item: StarlingDramaJobItemOut;
  targetLangs: string[];
}) {
  const badge = itemStatusBadge(item.status);
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium truncate">
            第 {item.episode_number} 集 · {item.source_filename}
          </span>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
        <div className="text-xs text-muted-foreground shrink-0">
          {item.width && item.height ? `${item.width}×${item.height}` : ""}
          {item.duration_ms ? ` · ${Math.round(item.duration_ms / 1000)}s` : ""}
          {item.upload_status ? ` · ${item.upload_status}` : ""}
        </div>
      </div>
      {item.error ? (
        <p className="mt-1 text-xs text-destructive">{item.error}</p>
      ) : null}
      <div className="mt-2 flex flex-col gap-2">
        {targetLangs.map((lang) => (
          <TranslationRow
            key={lang}
            lang={lang}
            translation={item.translations?.[lang]}
          />
        ))}
      </div>
    </div>
  );
}

function TranslationRow({
  lang,
  translation,
}: {
  lang: string;
  translation?: StarlingDramaTranslationOut;
}) {
  if (!translation) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{lang}：</span>
        <span>未启动</span>
      </div>
    );
  }
  const products = translation.products || {};
  const hasProducts = Object.values(products).some((v) => v);
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="font-medium">{lang}：</span>
      <Badge variant="outline">{translation.ai_flow_status || "未启动"}</Badge>
      {translation.submit_status ? (
        <Badge variant="outline">校对：{translation.submit_status}</Badge>
      ) : null}
      {translation.suppression_status ? (
        <Badge variant="outline">压制：{translation.suppression_status}</Badge>
      ) : null}
      {translation.error_message ? (
        <span className="text-destructive">{translation.error_message}</span>
      ) : null}
      {hasProducts ? (
        <div className="flex flex-wrap items-center gap-1">
          {Object.entries(products).map(([key, url]) => {
            if (!url || typeof url !== "string") return null;
            if (!key.endsWith("_public_url")) return null;
            const type = key.replace("_public_url", "");
            return (
              <Button
                key={key}
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                onClick={() => {
                  const filename = url.split("/").pop() || `${type}.bin`;
                  triggerBrowserDownload(url, filename);
                }}
              >
                <Download className="mr-1 h-3 w-3" />
                {artifactLabel(type)}
              </Button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
