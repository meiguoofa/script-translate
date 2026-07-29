import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronDown,
  Download,
  DownloadCloud,
  Loader2,
  RefreshCw,
  Square,
} from "lucide-react";
import {
  getImsSpeechJob,
  retryImsSpeechJob,
  stopImsSpeechJob,
} from "@/api/client";
import type {
  ImsSpeechJobItemOut,
  ImsSpeechJobOut,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { toast } from "@/components/ui/sonner";
import {
  buildImsDownloadFilename,
  countImsResources,
  getImsResourceUrl,
  triggerImsBrowserDownload,
  type ImsDownloadResourceType,
} from "@/pages/imsSpeechDownloadUtils";

const JOB_STATUS = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
} as const;

const ITEM_STATUS = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  succeeded: { label: "成功", variant: "success" },
  partial_failed: { label: "部分失败", variant: "destructive" },
  failed: { label: "失败", variant: "destructive" },
} as const;

const TRANSLATION_STATUS = {
  pending: { label: "等待", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  succeeded: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
} as const;

type Artifact = {
  label: string;
  url: string | null;
};

type DownloadOption = {
  key: ImsDownloadResourceType;
  label: string;
};

function DownloadAllMenu({
  count,
  disabled,
  options,
  onDownload,
}: {
  count: number;
  disabled: boolean;
  options: DownloadOption[];
  onDownload: (type: ImsDownloadResourceType) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        {disabled ? (
          <Loader2 className="mr-1 h-4 w-4 animate-spin" />
        ) : (
          <DownloadCloud className="mr-1 h-4 w-4" />
        )}
        {disabled ? "下载中…" : `下载全部（${count}）`}
        <ChevronDown className="ml-1 h-3 w-3" />
      </Button>
      {open ? (
        <div className="absolute right-0 top-full z-20 mt-1 min-w-[220px] rounded-md border bg-background py-1 shadow-md">
          {options.map((option) => (
            <button
              key={option.key}
              type="button"
              className="block w-full px-3 py-1.5 text-left text-sm hover:bg-muted"
              onClick={() => {
                setOpen(false);
                onDownload(option.key);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ArtifactLink({ artifact }: { artifact: Artifact }) {
  if (!artifact.url) return null;
  return (
    <a
      href={artifact.url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs hover:bg-accent"
    >
      <Download className="h-3 w-3" />
      {artifact.label}
    </a>
  );
}

function TranslationArtifacts({
  item,
  language,
}: {
  item: ImsSpeechJobItemOut;
  language: string;
}) {
  const artifacts: Artifact[] = [
    {
      label: "译制成片",
      url: getImsResourceUrl(item, "dubbed-video", language),
    },
    {
      label: "翻译音轨",
      url: getImsResourceUrl(item, "translated-audio", language),
    },
    {
      label: "译文字幕",
      url: getImsResourceUrl(item, "translated-subtitle", language),
    },
    {
      label: "修订字幕",
      url: getImsResourceUrl(item, "fix-subtitle", language),
    },
    {
      label: "双语字幕",
      url: getImsResourceUrl(item, "bilingual-subtitle", language),
    },
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {artifacts.map((artifact) => (
        <ArtifactLink key={artifact.label} artifact={artifact} />
      ))}
    </div>
  );
}

function EpisodeCard({
  item,
  activeLanguage,
}: {
  item: ImsSpeechJobItemOut;
  activeLanguage: string;
}) {
  const itemStatus = ITEM_STATUS[item.status];
  const translation = item.translations[activeLanguage];
  const translationStatus = translation
    ? TRANSLATION_STATUS[translation.status]
    : TRANSLATION_STATUS.pending;
  return (
    <Card>
      <CardContent className="space-y-4 py-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p className="truncate font-medium">
              第 {item.episode_index + 1} 集 · {item.filename}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              阶段：{item.stage} · IMS：{item.ims_status || "尚未提交"}
              {item.ims_job_id ? ` · ${item.ims_job_id}` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <Badge variant={itemStatus.variant}>{itemStatus.label}</Badge>
            <Badge variant={translationStatus.variant}>
              {activeLanguage}: {translationStatus.label}
            </Badge>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <ArtifactLink artifact={{ label: "原视频", url: item.input_public_url }} />
          <ArtifactLink artifact={{ label: "擦除字幕视频", url: item.detext_video_url }} />
          {translation ? (
            <TranslationArtifacts item={item} language={activeLanguage} />
          ) : null}
        </div>

        {translation?.speech_translation_job_id ? (
          <p className="text-xs text-muted-foreground">
            语音翻译子任务：{translation.speech_translation_job_id}
          </p>
        ) : null}
        {translation?.error || item.error ? (
          <p className="text-xs text-destructive">
            {translation?.error || item.error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function ImsSpeechDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<ImsSpeechJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeLanguage, setActiveLanguage] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [downloadingType, setDownloadingType] =
    useState<ImsDownloadResourceType | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    async function poll() {
      try {
        const data = await getImsSpeechJob(jobId!);
        if (cancelled) return;
        setJob(data);
        setError(null);
        if (!["completed", "failed"].includes(data.status)) {
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
  }, [jobId, refreshKey]);

  const effectiveLanguage = activeLanguage || job?.target_languages[0] || "";
  const byDrama = useMemo(() => {
    const groups = new Map<number, ImsSpeechJobItemOut[]>();
    for (const item of job?.items || []) {
      const entries = groups.get(item.drama_index) || [];
      entries.push(item);
      groups.set(item.drama_index, entries);
    }
    return groups;
  }, [job]);

  async function retryFailed() {
    if (!job) return;
    setRetrying(true);
    try {
      const data = await retryImsSpeechJob(job.id);
      setJob(data);
      setRefreshKey((value) => value + 1);
      toast.success("仅失败/缺失语言已重新提交，成功产物保持不变");
    } catch (requestError: any) {
      toast.error(requestError?.response?.data?.detail || "重试失败");
    } finally {
      setRetrying(false);
    }
  }

  async function stopRunning() {
    if (!job) return;
    const confirmed = window.confirm(
      "停止只会终止本地轮询，阿里云端任务可能继续执行并产生费用。确认停止？"
    );
    if (!confirmed) return;
    setStopping(true);
    try {
      const data = await stopImsSpeechJob(job.id);
      setJob(data);
      toast.success("已停止本地跟踪");
    } catch (requestError: any) {
      toast.error(requestError?.response?.data?.detail || "停止失败");
    } finally {
      setStopping(false);
    }
  }

  async function downloadAll(type: ImsDownloadResourceType) {
    if (!job || downloadingType) return;
    setDownloadingType(type);
    let triggered = 0;
    let skipped = 0;
    try {
      for (const item of job.items) {
        const url = getImsResourceUrl(item, type, effectiveLanguage);
        if (!url) {
          skipped += 1;
          continue;
        }
        triggerImsBrowserDownload(
          url,
          buildImsDownloadFilename(item, type, effectiveLanguage),
        );
        triggered += 1;
        await new Promise((resolve) => window.setTimeout(resolve, 350));
      }

      if (triggered === 0) {
        toast.error("没有可下载的资源");
      } else if (skipped > 0) {
        toast.success(`已触发 ${triggered} 个下载，${skipped} 个资源缺失已跳过`);
      } else {
        toast.success(`已触发 ${triggered} 个下载`);
      }
    } finally {
      setDownloadingType(null);
    }
  }

  if (!job) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          {error ? error : <><Loader2 className="h-4 w-4 animate-spin" />加载中…</>}
        </CardContent>
      </Card>
    );
  }

  const status = JOB_STATUS[job.status];
  const canRetry =
    ["completed", "failed"].includes(job.status) &&
    job.partial_failed_count + job.failed_count > 0;
  const downloadOptions = ([
    { key: "original", label: "全部原视频" },
    { key: "erased", label: "全部擦除字幕视频" },
    { key: "dubbed-video", label: `全部译制成片（${effectiveLanguage}）` },
    { key: "translated-audio", label: `全部翻译音轨（${effectiveLanguage}）` },
    { key: "translated-subtitle", label: `全部译文字幕（${effectiveLanguage}）` },
    { key: "fix-subtitle", label: `全部修订字幕（${effectiveLanguage}）` },
    { key: "bilingual-subtitle", label: `全部双语字幕（${effectiveLanguage}）` },
  ] satisfies DownloadOption[]).filter(
    (option) =>
      countImsResources(job.items, option.key, effectiveLanguage) > 0,
  );
  const downloadableItemCount = job.items.filter((item) =>
    downloadOptions.some((option) =>
      getImsResourceUrl(item, option.key, effectiveLanguage),
    ),
  ).length;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <CardTitle>{job.title}</CardTitle>
                <Badge variant={status.variant}>{status.label}</Badge>
              </div>
              <CardDescription className="mt-2">
                {job.drama_count} 部剧 · {job.video_count} 集 · {job.text_source} ·{" "}
                {job.source_language} → {job.target_languages.join(", ")}
              </CardDescription>
            </div>
            <div className="flex gap-2">
              {downloadableItemCount > 1 ? (
                <DownloadAllMenu
                  count={downloadableItemCount}
                  disabled={downloadingType !== null}
                  options={downloadOptions}
                  onDownload={downloadAll}
                />
              ) : null}
              {job.status === "pending" || job.status === "running" ? (
                <Button variant="outline" onClick={stopRunning} disabled={stopping}>
                  {stopping ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Square className="mr-2 h-4 w-4" />
                  )}
                  停止本地跟踪
                </Button>
              ) : null}
              {canRetry ? (
                <Button onClick={retryFailed} disabled={retrying}>
                  {retrying ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 h-4 w-4" />
                  )}
                  重试失败语言
                </Button>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">成功集数</p>
              <p className="text-xl font-semibold">{job.succeeded_count}</p>
            </div>
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">部分失败</p>
              <p className="text-xl font-semibold">{job.partial_failed_count}</p>
            </div>
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">失败集数</p>
              <p className="text-xl font-semibold">{job.failed_count}</p>
            </div>
          </div>
          {job.progress_message ? (
            <p className="text-sm text-muted-foreground">{job.progress_message}</p>
          ) : null}
          {job.error_message ? (
            <div className="flex gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {job.error_message}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">目标语言</CardTitle>
          <CardDescription>
            切换语言查看对应成片、音轨和字幕；修订字幕已持久化，但当前版本不提供修订后重提交流程。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {job.target_languages.map((language) => (
            <Button
              key={language}
              size="sm"
              variant={effectiveLanguage === language ? "default" : "outline"}
              onClick={() => setActiveLanguage(language)}
            >
              {language}
            </Button>
          ))}
        </CardContent>
      </Card>

      {[...byDrama.entries()].map(([dramaIndex, items]) => (
        <section key={dramaIndex} className="space-y-3">
          <div>
            <h2 className="font-semibold">第 {dramaIndex + 1} 部剧</h2>
            <p className="text-xs text-muted-foreground">{items.length} 集</p>
          </div>
          <Separator />
          {items
            .sort((left, right) => left.episode_index - right.episode_index)
            .map((item) => (
              <EpisodeCard
                key={item.index}
                item={item}
                activeLanguage={effectiveLanguage}
              />
            ))}
        </section>
      ))}
    </div>
  );
}
