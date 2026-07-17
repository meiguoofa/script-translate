import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Download,
  DownloadCloud,
  Loader2,
  RefreshCw,
  RotateCcw,
  Square,
  XCircle,
} from "lucide-react";
import {
  getBaiduVodJob,
  retryBaiduVodJob,
  stopBaiduVodJob,
} from "@/api/client";
import type { BaiduVodJobOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/sonner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const JOB_BADGE: Record<string, { label: string; variant: "info" | "success" | "destructive" | "muted" }> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

const LANG_LABELS: Record<string, string> = {
  "zh-CN": "中文", "en-US": "英文", "ja-JP": "日文", "ko-KR": "韩文",
  "de-DE": "德文", "fr-FR": "法文", "ru-RU": "俄文", "es-ES": "西班牙文",
  "pt-PT": "葡萄牙文", "id-ID": "印尼文", "vi-VN": "越南文", "th-TH": "泰文",
};

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "--";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

type DownloadType = "final" | "desubtitle" | "source-srt" | "target-srt" | "cover";

function getItemResourceUrl(
  item: BaiduVodJobOut["items"][number],
  type: DownloadType,
  lang: string
): string | null {
  const t = item.translations?.[lang];
  if (!t) return null;
  switch (type) {
    case "final": return t.final_video_url || null;
    case "desubtitle": return t.desubtitle_video_url || null;
    case "source-srt": return t.source_srt_url || null;
    case "target-srt": return t.target_srt_url || null;
    case "cover": return t.cover_url || null;
  }
}

function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function DownloadMenu({ item, lang }: { item: BaiduVodJobOut["items"][number]; lang: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const types: { key: DownloadType; label: string }[] = [
    { key: "final", label: "最终视频" },
    { key: "desubtitle", label: "擦除视频" },
    { key: "source-srt", label: "源字幕 SRT" },
    { key: "target-srt", label: "译文字幕 SRT" },
    { key: "cover", label: "封面" },
  ];
  const visible = types.filter((t) => getItemResourceUrl(item, t.key, lang));
  if (visible.length === 0) return null;

  return (
    <div className="relative" ref={ref}>
      <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
        <Download className="mr-1 h-4 w-4" />
        下载
        <ChevronDown className="ml-1 h-3 w-3" />
      </Button>
      {open ? (
        <div className="absolute right-0 top-full z-20 mt-1 min-w-[160px] rounded-md border bg-background shadow-md">
          {visible.map((o) => {
            const url = getItemResourceUrl(item, o.key, lang)!;
            return (
              <a key={o.key}
                href={url} target="_blank" rel="noopener noreferrer"
                onClick={() => setOpen(false)}
                className="block cursor-pointer px-3 py-1.5 text-sm hover:bg-muted">
                {o.label}
              </a>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function BaiduVodDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<BaiduVodJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [activeLang, setActiveLang] = useState<string>("");
  const timer = useRef<number | null>(null);
  const pollRef = useRef<(() => Promise<void>) | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    async function poll() {
      try {
        const data = await getBaiduVodJob(jobId!);
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

  if (error) {
    return <div className="p-4 text-destructive">{error}</div>;
  }
  if (!job) {
    return <div className="p-4 text-muted-foreground">加载中...</div>;
  }

  const badge = JOB_BADGE[job.status] || { label: job.status, variant: "muted" as const };
  const isTerminal = job.status === "completed" || job.status === "failed";
  const effectiveLang = activeLang || job.target_langs[0] || "";

  // 按剧分组
  const byDrama = new Map<number, typeof job.items>();
  for (const item of job.items) {
    const di = item.drama_index;
    if (!byDrama.has(di)) byDrama.set(di, []);
    byDrama.get(di)!.push(item);
  }

  async function stopRunning() {
    if (!job) return;
    setStopping(true);
    try {
      const data = await stopBaiduVodJob(job.id);
      setJob(data);
      toast.success("已停止任务");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "停止失败");
    } finally {
      setStopping(false);
    }
  }

  async function retryFailed() {
    if (!job) return;
    setRetrying(true);
    try {
      const data = await retryBaiduVodJob(job.id);
      setJob(data);
      toast.success("已重新提交失败项");
      pollRef.current?.();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || "重试失败");
    } finally {
      setRetrying(false);
    }
  }

  const failedCount = job.items.filter((it) => it.status === "failed").length;

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-lg">
              {job.title}
              <Badge variant={badge.variant}>
                {job.status === "running" ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
                {badge.label}
              </Badge>
            </CardTitle>
            <CardDescription>
              {job.drama_count} 部剧 · {job.video_count} 集 · 总时长 {formatDuration(job.total_duration_seconds)} ·{" "}
              已注册媒资 {job.registered_count}/{job.video_count} 集 ·{" "}
              源语言 {LANG_LABELS[job.source_language] || job.source_language}{" -> "}
              {job.target_langs.map((l) => LANG_LABELS[l] || l).join("、")} ·{" "}
              成功 {job.succeeded_count} · 失败 {job.failed_count}
            </CardDescription>
          </div>
          {!isTerminal ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <RefreshCw className="h-3 w-3" /> 自动刷新
            </span>
          ) : null}
          {failedCount > 0 && isTerminal ? (
            <Button size="sm" variant="secondary" onClick={retryFailed} disabled={retrying}>
              {retrying ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-1 h-4 w-4" />}
              重试失败项({failedCount})
            </Button>
          ) : null}
          {job.status === "running" ? (
            <Button size="sm" variant="destructive" onClick={stopRunning} disabled={stopping}>
              {stopping ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Square className="mr-1 h-4 w-4" />}
              停止任务
            </Button>
          ) : null}
        </CardHeader>
      </Card>

      {job.error_message ? (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-destructive">{job.error_message}</p>
          </CardContent>
        </Card>
      ) : null}

      {job.target_langs.length > 1 ? (
        <div className="flex flex-wrap gap-2">
          {job.target_langs.map((lang) => {
            const label = LANG_LABELS[lang] || lang;
            const isActive = lang === effectiveLang;
            return (
              <button key={lang} type="button" onClick={() => setActiveLang(lang)}
                className={
                  "rounded-md border px-3 py-1.5 text-sm transition-colors " +
                  (isActive ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted")
                }>
                {label}
              </button>
            );
          })}
        </div>
      ) : null}

      {[...byDrama.keys()].sort((a, b) => a - b).map((di) => {
        const items = byDrama.get(di) || [];
        return (
          <Card key={`drama-${di}`}>
            <CardHeader>
              <CardTitle className="text-base">第 {di + 1} 部剧 · {items.length} 集</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {items.map((item) => {
                const t = item.translations?.[effectiveLang] || null;
                const itemStatus = t?.status || item.status;
                const itemError = t?.error || item.error;
                const statusLabel = itemStatus === "SUCCESS" ? "成功" :
                  itemStatus === "FAILED" ? "失败" :
                  itemStatus === "RUNNING" ? "处理中" :
                  itemStatus === "READY" ? "等待" : "排队中";
                const statusVariant = itemStatus === "SUCCESS" ? "success" :
                  itemStatus === "FAILED" ? "destructive" :
                  itemStatus === "RUNNING" || itemStatus === "READY" ? "info" : "muted";
                return (
                  <div key={item.index}
                    className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex min-w-0 flex-col gap-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-muted-foreground">第 {item.episode_index + 1} 集</span>
                        <span className="truncate font-medium">{item.filename}</span>
                        <span className="text-xs text-muted-foreground">⏱ {formatDuration(item.duration_seconds)}</span>
                        <Badge variant={statusVariant as any}>
                          {itemStatus === "RUNNING" ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                          {statusLabel}
                        </Badge>
                        {item.baidu_media_id ? (
                          <Badge variant="success" className="gap-1"><CheckCircle2 className="h-3 w-3" />已注册媒资</Badge>
                        ) : null}
                        {item.warning ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Badge variant="warning" className="cursor-default gap-1">
                                <AlertTriangle className="h-3 w-3" />警告
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-xs">{item.warning}</TooltipContent>
                          </Tooltip>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        {t?.baidu_task_id ? <span>taskId: {t.baidu_task_id.slice(0, 20)}...</span> : null}
                        {item.baidu_media_id ? <span>mediaId: {item.baidu_media_id.slice(0, 20)}...</span> : null}
                      </div>
                      {itemError ? (
                        <p className="text-xs text-destructive">错误：{itemError}</p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <DownloadMenu item={item} lang={effectiveLang} />
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        );
      })}

      <div className="flex justify-center">
        <DownloadCloud className="h-8 w-8 text-muted-foreground" />
      </div>
      <div className="text-center text-xs text-muted-foreground">
        job_id: {job.id}
        {job.baidu_project_id ? ` · project: ${job.baidu_project_id}` : null}
      </div>
    </div>
  );
}
