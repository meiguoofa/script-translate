import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Download, DownloadCloud, Loader2, RefreshCw, XCircle } from "lucide-react";
import { getSuperResJob } from "@/api/client";
import type { SuperResItemStatus, SuperResJobOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const JOB_BADGE: Record<
  SuperResJobOut["status"],
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

const ITEM_BADGE: Record<
  SuperResItemStatus,
  { label: string; variant: "info" | "success" | "destructive" | "muted" }
> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "超分中", variant: "info" },
  succeeded: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

export function SuperResolutionDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<SuperResJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    async function poll() {
      try {
        const data = await getSuperResJob(jobId!);
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
  const succeededItems = job.items.filter((it) => it.status === "succeeded" && it.output_public_url);

  async function downloadAll() {
    for (const item of succeededItems) {
      if (!item.output_public_url) continue;
      const a = document.createElement("a");
      a.href = item.output_public_url;
      // 用原文件名 + 索引前缀，避免重名
      a.download = `${String(item.index + 1).padStart(2, "0")}-${item.filename}`;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // 浏览器对快速连续触发的下载可能合并/吞掉，间隔 350ms 保险
      await new Promise((resolve) => setTimeout(resolve, 350));
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
              {job.video_count} 个视频 · 码率 {job.bit_rate} Mbps · 成功 {job.succeeded_count} ·
              失败 {job.failed_count}
            </CardDescription>
          </div>
          {!isTerminal ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <RefreshCw className="h-3 w-3" /> 自动刷新
            </span>
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

      <Card>
        <CardHeader>
          <CardTitle className="text-base">视频明细</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {job.items.map((item) => {
            const ib = ITEM_BADGE[item.status];
            return (
              <div
                key={item.index}
                className="flex flex-col gap-2 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">#{item.index + 1}</span>
                    <span className="truncate font-medium">{item.filename}</span>
                    <Badge variant={ib.variant}>
                      {item.status === "running" ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : null}
                      {ib.label}
                    </Badge>
                  </div>
                  {item.error ? (
                    <p className="text-xs text-destructive">错误：{item.error}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {item.output_public_url ? (
                    <a
                      href={item.output_public_url}
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

      {job.status === "failed" ? (
        <Card>
          <CardContent className="flex flex-col gap-3 py-6">
            <p className="text-sm text-destructive">
              整体失败：{job.error_message ?? "全部视频处理失败"}
            </p>
            <div>
              <Button variant="secondary" onClick={() => navigate("/super-resolution")}>
                返回上传页
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
