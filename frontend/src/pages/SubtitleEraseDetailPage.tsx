import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CheckCircle2,
  Download,
  DownloadCloud,
  Loader2,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { getSubtitleEraseJob, retrySubtitleEraseJob } from "@/api/client";
import type {
  SubtitleEraseItemStage,
  SubtitleEraseItemStatus,
  SubtitleEraseJobOut,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/sonner";

const JOB_BADGE: Record<
  SubtitleEraseJobOut["status"],
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

const ITEM_BADGE: Record<
  SubtitleEraseItemStatus,
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  succeeded: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

const STAGE_LABEL: Record<SubtitleEraseItemStage, string> = {
  pending: "等待开始",
  extracting: "字幕提取 + 擦除中",
  cleaning: "SRT 清洗",
  translating: "翻译 SRT",
  burning: "烧录译文字幕",
  done: "已完成",
};

export function SubtitleEraseDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<SubtitleEraseJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const timer = useRef<number | null>(null);
  const pollRef = useRef<(() => Promise<void>) | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    async function poll() {
      try {
        const data = await getSubtitleEraseJob(jobId!);
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

    pollRef.current = poll;
    poll();
    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [jobId]);

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

  const badge = JOB_BADGE[job.status];
  const isTerminal = job.status === "completed" || job.status === "failed";
  // 优先 TOS（本机烧录输出），fallback 到 OSS（阿里云烧录输出）
  const downloadUrl = (it: typeof job.items[number]) =>
    it.output_video_tos_public_url || it.output_public_url;
  const succeededItems = job.items.filter(
    (it) => it.status === "succeeded" && downloadUrl(it)
  );

  // 按剧分组
  const byDrama = new Map<number, typeof job.items>();
  for (const item of job.items) {
    const di = item.drama_index;
    if (!byDrama.has(di)) byDrama.set(di, []);
    byDrama.get(di)!.push(item);
  }

  async function downloadAll() {
    for (const item of succeededItems) {
      const url = downloadUrl(item);
      if (!url) continue;
      const a = document.createElement("a");
      a.href = url;
      a.download = `d${item.drama_index + 1}-e${item.episode_index + 1}-${item.filename}`;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
  }

  async function retryFailed() {
    if (!job) return;
    setRetrying(true);
    try {
      await retrySubtitleEraseJob(job.id);
      toast.success("已重新提交失败项");
      const data = await getSubtitleEraseJob(job.id);
      setJob(data);
      if (data.status !== "completed" && data.status !== "failed") {
        if (timer.current) window.clearTimeout(timer.current);
        pollRef.current?.();
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || "重试失败";
      toast.error(detail);
    } finally {
      setRetrying(false);
    }
  }

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
              {job.drama_count} 部剧 · {job.video_count} 集 · {job.detext_mode === "advanced" ? "高级版擦除" : "基础版擦除"} ·{" "}
              {job.translate_mode === "aliyun" ? "阿里云翻译" : "LLM 翻译"} → {job.target_lang} ·{" "}
              {job.burn_mode === "local" ? "本机 ffmpeg 烧录" : "阿里云 IMS 烧录"} ·
              成功 {job.succeeded_count} · 失败 {job.failed_count}
            </CardDescription>
          </div>
          {!isTerminal ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <RefreshCw className="h-3 w-3" /> 自动刷新
            </span>
          ) : null}
          {job.failed_count > 0 ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={retryFailed}
              disabled={retrying || !isTerminal}
            >
              {retrying ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <RotateCcw className="mr-1 h-4 w-4" />
              )}
              重试失败项（{job.failed_count}）
            </Button>
          ) : null}
          {succeededItems.length > 1 ? (
            <Button size="sm" variant="secondary" onClick={downloadAll}>
              <DownloadCloud className="mr-1 h-4 w-4" />
              下载全部（{succeededItems.length}）
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
          {job.progress_message ? <p>状态：{job.progress_message}</p> : null}
          {job.error_message ? (
            <p className="text-destructive">错误：{job.error_message}</p>
          ) : null}
          <p>输出前缀：<span className="font-mono text-xs">{job.output_oss_prefix}</span></p>
          <p>创建于 {new Date(job.created_at).toLocaleString()}</p>
          {job.completed_at ? (
            <p>结束于 {new Date(job.completed_at).toLocaleString()}</p>
          ) : null}
        </CardContent>
      </Card>

      {[...byDrama.keys()].sort((a, b) => a - b).map((di) => {
        const items = byDrama.get(di) || [];
        return (
          <Card key={`drama-${di}`}>
            <CardHeader>
              <CardTitle className="text-base">第 {di + 1} 部剧 · {items.length} 集</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {items.map((item) => {
                const ib = ITEM_BADGE[item.status];
                return (
                  <div
                    key={item.index}
                    className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-muted-foreground">
                          第 {item.episode_index + 1} 集
                        </span>
                        <span className="truncate font-medium">{item.filename}</span>
                        <Badge variant={ib.variant}>
                          {item.status === "running" ? (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          ) : null}
                          {ib.label}
                        </Badge>
                        {item.status === "running" ? (
                          <Badge variant="muted">{STAGE_LABEL[item.stage]}</Badge>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        {item.caption_status ? (
                          <span>提取: {item.caption_status}</span>
                        ) : null}
                        {item.detext_status ? (
                          <span>擦除: {item.detext_status}</span>
                        ) : null}
                        {item.translation_status ? (
                          <span>烧录: {item.translation_status}</span>
                        ) : null}
                      </div>
                      {item.error ? (
                        <p className="text-xs text-destructive">错误：{item.error}</p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {downloadUrl(item) ? (
                        <a
                          href={downloadUrl(item)!}
                          target="_blank"
                          rel="noopener noreferrer"
                          download
                        >
                          <Button size="sm" variant="ghost">
                            <Download className="mr-1 h-4 w-4" />
                            下载
                          </Button>
                        </a>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        );
      })}

      {job.status === "failed" ? (
        <Card>
          <CardContent className="flex flex-col gap-3 py-6">
            <p className="text-sm text-destructive">
              整体失败：{job.error_message ?? "全部视频处理失败"}
            </p>
            <div>
              <Button variant="secondary" onClick={() => navigate("/subtitle-erase")}>
                返回上传页
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
