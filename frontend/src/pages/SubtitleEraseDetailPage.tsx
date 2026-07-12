import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  DownloadCloud,
  Loader2,
  RefreshCw,
  RotateCcw,
  Square,
  XCircle,
} from "lucide-react";
import {
  getModels,
  getSubtitleEraseJob,
  rerunAllSubtitleEraseJob,
  retrySubtitleEraseJob,
  stopSubtitleEraseJob,
} from "@/api/client";
import type {
  ModelOption,
  SubtitleEraseItemStage,
  SubtitleEraseItemStatus,
  SubtitleEraseJobOut,
  SubtitleEraseRerunRequest,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { toast } from "@/components/ui/sonner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

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

const TARGET_LANG_LABELS: Record<string, string> = {
  zh: "中文",
  en: "英文",
  ja: "日文",
  ko: "韩文",
  vi: "越南语",
  th: "泰语",
  id: "印尼语",
  ms: "马来语",
  pt: "葡萄牙语",
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

export function SubtitleEraseDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<SubtitleEraseJobOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [showRerun, setShowRerun] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  // 当前选中展示的语言 Tab(默认空字符串,渲染时回退到 target_langs[0])
  const [activeLang, setActiveLang] = useState<string>("");

  // rerun form state (初始值在 job 加载后更新)
  const [rDetextMode, setRDetextMode] = useState<"basic" | "advanced">("advanced");
  const [rTranslateMode, setRTranslateMode] = useState<"aliyun" | "llm">("llm");
  const [rBurnMode, setRBurnMode] = useState<"local" | "aliyun" | "mps">("mps");
  const [rPlacementMode, setRPlacementMode] = useState<"safe_bottom" | "simple_bottom">("safe_bottom");
  const [rSourceLang, setRSourceLang] = useState("auto");
  const [rTargetLangs, setRTargetLangs] = useState<string[]>(["zh"]);
  const [rForceRedetext, setRForceRedetext] = useState(false);
  const [rForceRecaption, setRForceRecaption] = useState(false);
  const [rModelProvider, setRModelProvider] = useState("");
  const [rModelName, setRModelName] = useState("");
  const [rQps, setRQps] = useState(30);
  const [rCaptionFps, setRCaptionFps] = useState(5);
  const [rCaptionLang, setRCaptionLang] = useState("ch_ml");
  const [rCaptionTrack, setRCaptionTrack] = useState("main");
  const [rCaptionRoiPct, setRCaptionRoiPct] = useState(35);
  const [rCaptionSep, setRCaptionSep] = useState(false);
  const [rDetextRegionPct, setRDetextRegionPct] = useState(35);
  const [rBurnFontSize, setRBurnFontSize] = useState(5);
  const [rBurnFontColor, setRBurnFontColor] = useState("#FFFFFF");
  const [rBurnX, setRBurnX] = useState(0.5);
  const [rBurnY, setRBurnY] = useState(0.82);
  const [rBurnTextWidth, setRBurnTextWidth] = useState(0.9);

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

  // 当 job 加载完成后，将参数同步到 rerun 表单
  useEffect(() => {
    if (!job) return;
    setRDetextMode(job.detext_mode as "basic" | "advanced");
    setRTranslateMode(job.translate_mode as "aliyun" | "llm");
    setRBurnMode(job.burn_mode as "local" | "aliyun" | "mps");
    setRPlacementMode(job.placement_mode as "safe_bottom" | "simple_bottom");
    setRSourceLang(job.source_lang || "auto");
    setRTargetLangs(job.target_langs && job.target_langs.length > 0 ? job.target_langs : ["zh"]);
    setRModelProvider(job.model_provider || "");
    setRModelName(job.model_name || "");
    setRQps(job.qps);
    setRCaptionFps(job.caption_fps);
    setRCaptionLang(job.caption_lang);
    setRCaptionTrack(job.caption_track);
    try { const r = JSON.parse(job.caption_roi || ""); setRCaptionRoiPct(Math.round((1 - r[0][0]) * 100)); } catch { setRCaptionRoiPct(35); }
    setRCaptionSep(job.caption_sep);
    try { const r = JSON.parse(job.detext_limit_region || ""); setRDetextRegionPct(Math.round(r[0][3] * 100)); } catch { setRDetextRegionPct(35); }
    setRBurnFontSize(job.burn_font_size);
    setRBurnFontColor(job.burn_font_color);
    setRBurnX(job.burn_x);
    setRBurnY(job.burn_y);
    setRBurnTextWidth(job.burn_text_width);
  }, [job?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 打开重新运行面板时加载模型列表
  useEffect(() => {
    if (!showRerun || models.length > 0) return;
    getModels()
      .then((list) => {
        setModels(list);
        if (!rModelProvider) {
          const def = list.find((m) => m.default) ?? list[0];
          if (def) {
            setRModelProvider((curr) => curr || def.provider);
            setRModelName((curr) => curr || def.name);
          }
        }
      })
      .catch(() => toast.error("模型列表加载失败"));
  }, [showRerun]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const effectiveLang = activeLang || job.target_langs[0] || "";
  // 优先北京 TOS（国内用户快）→ 新加坡 TOS（服务器内网上传的）→ 阿里云 OSS（IMS 烧录）
  const downloadUrl = (it: typeof job.items[number]) => {
    const t = it.translations?.[effectiveLang];
    if (!t) return null;
    return t.output_video_bj_tos_public_url || t.output_video_tos_public_url || t.output_public_url;
  };
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

  async function stopRunning() {
    if (!job) return;
    setStopping(true);
    try {
      const data = await stopSubtitleEraseJob(job.id);
      setJob(data);
      toast.success("已停止任务，可重试失败项");
    } catch (err: any) {
      const detail = err?.response?.data?.detail || "停止任务失败";
      toast.error(detail);
    } finally {
      setStopping(false);
    }
  }

  async function rerunAll() {
    if (!job) return;
    setRerunning(true);
    try {
      const payload: SubtitleEraseRerunRequest = {
        detext_mode: rDetextMode,
        translate_mode: rTranslateMode,
        burn_mode: rBurnMode,
        placement_mode: rPlacementMode,
        source_lang: rTranslateMode === "llm" && rBurnMode !== "aliyun" ? null : rSourceLang,
        target_langs: rTargetLangs,
        force_redetext: rForceRedetext,
        force_recaption: rForceRecaption,
        model_provider: rTranslateMode === "llm" ? rModelProvider : null,
        model_name: rTranslateMode === "llm" ? rModelName : null,
        qps: rQps,
        caption_fps: rCaptionFps,
        caption_lang: rCaptionLang,
        caption_track: rCaptionTrack,
        caption_roi: `[[${(1 - rCaptionRoiPct / 100).toFixed(2)},1],[0,1]]`,
        caption_sep: rCaptionSep,
        detext_limit_region: `[[0,${(1 - rDetextRegionPct / 100).toFixed(2)},1,${(rDetextRegionPct / 100).toFixed(2)}]]`,
        burn_font_size: rBurnFontSize,
        burn_font_color: rBurnFontColor,
        burn_font_color_opacity: 1.0,
        burn_x: rBurnX,
        burn_y: rBurnY,
        burn_text_width: rBurnTextWidth,
      };
      const data = await rerunAllSubtitleEraseJob(job.id, payload);
      setJob(data);
      setShowRerun(false);
      toast.success("已重新提交全部集数");
      if (data.status !== "completed" && data.status !== "failed") {
        if (timer.current) window.clearTimeout(timer.current);
        pollRef.current?.();
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || "重新运行失败";
      toast.error(detail);
    } finally {
      setRerunning(false);
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
              {job.drama_count} 部剧 · {job.video_count} 集 · 总时长 {formatDuration(job.total_duration_seconds)} · {job.detext_mode === "advanced" ? "高级版擦除" : "基础版擦除"} · 已擦除 {job.detexted_count}/{job.video_count} 集 · 已提取字幕 {job.captioned_count}/{job.video_count} 集 ·{" "}
              {job.translate_mode === "aliyun" ? "阿里云翻译" : "LLM 翻译"} → {job.target_langs.map((l) => TARGET_LANG_LABELS[l] || l).join("、")} ·{" "}
              {job.burn_mode === "local" ? "本机 ffmpeg 烧录" : job.burn_mode === "mps" ? "MPS 烧录" : "阿里云 IMS 烧录"} ·
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
          {job.status === "running" ? (
            <Button
              size="sm"
              variant="destructive"
              onClick={stopRunning}
              disabled={stopping}
            >
              {stopping ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Square className="mr-1 h-4 w-4" />
              )}
              停止任务
            </Button>
          ) : null}
          {isTerminal ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowRerun((v) => !v)}
            >
              {showRerun ? (
                <ChevronUp className="mr-1 h-4 w-4" />
              ) : (
                <ChevronDown className="mr-1 h-4 w-4" />
              )}
              编辑并重新运行
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

      {showRerun ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">编辑参数并重新运行全部</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label>字幕擦除模式</Label>
                <Select value={rDetextMode} onValueChange={(v) => setRDetextMode(v as "basic" | "advanced")}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="advanced">高级版（algo-video-detext-new）</SelectItem>
                    <SelectItem value="basic">基础版</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>翻译模式</Label>
                <Select value={rTranslateMode} onValueChange={(v) => {
                  const mode = v as "aliyun" | "llm";
                  setRTranslateMode(mode);
                  if (mode === "aliyun") { setRBurnMode("aliyun"); if (rSourceLang === "auto") setRSourceLang("zh"); }
                }}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="llm">LLM 翻译</SelectItem>
                    <SelectItem value="aliyun">阿里云翻译 API</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>烧录模式</Label>
                <Select value={rBurnMode} onValueChange={(v) => {
                  const mode = v as "local" | "aliyun" | "mps";
                  setRBurnMode(mode);
                  if (mode === "local" || mode === "mps") setRTranslateMode("llm");
                  else if (rSourceLang === "auto") setRSourceLang("zh");
                }}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mps">阿里云 MPS 烧录（推荐）</SelectItem>
                    <SelectItem value="local">本机 ffmpeg 烧录</SelectItem>
                    <SelectItem value="aliyun">阿里云 IMS 烧录</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>翻译目标语言（可多选）</Label>
                <div className="flex flex-wrap gap-3 rounded-md border p-3">
                  {[
                    { value: "zh", label: "中文" }, { value: "en", label: "英文" },
                    { value: "ja", label: "日文" }, { value: "ko", label: "韩文" },
                    { value: "vi", label: "越南语" }, { value: "th", label: "泰语" },
                    { value: "id", label: "印尼语" }, { value: "ms", label: "马来语" },
                    { value: "pt", label: "葡萄牙语" },
                  ].map((l) => {
                    const checked = rTargetLangs.includes(l.value);
                    return (
                      <label key={l.value} className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setRTargetLangs((prev) => prev.includes(l.value) ? prev : [...prev, l.value]);
                            } else {
                              setRTargetLangs((prev) => prev.length > 1 ? prev.filter((v) => v !== l.value) : prev);
                            }
                          }}
                          className="h-4 w-4"
                        />
                        <span className="text-sm">{l.label}</span>
                      </label>
                    );
                  })}
                </div>
                {rTargetLangs.length === 0 ? (
                  <p className="text-xs text-destructive">至少选择一个目标语言</p>
                ) : null}
              </div>
              <div className="flex flex-col gap-2 rounded-md border p-3 bg-muted/30">
                <Label className="text-sm font-medium">产物复用选项（默认自动复用已成功步骤）</Label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rForceRedetext}
                    onChange={(e) => setRForceRedetext(e.target.checked)}
                    className="h-4 w-4"
                  />
                  <span className="text-sm">强制重新擦除字幕（不复用 clean_video，重新付费跑 VideoDetext）</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rForceRecaption}
                    onChange={(e) => setRForceRecaption(e.target.checked)}
                    className="h-4 w-4"
                  />
                  <span className="text-sm">强制重新提取字幕（不复用 source/cleaned SRT，重新付费跑 CaptionExtraction）</span>
                </label>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>源语言</Label>
                <Select
                  value={rSourceLang}
                  disabled={rTranslateMode === "llm" && (rBurnMode === "local" || rBurnMode === "mps")}
                  onValueChange={setRSourceLang}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {[
                      { value: "auto", label: "自动识别" }, { value: "ch_ml", label: "中英混合" },
                      { value: "zh", label: "中文" }, { value: "en", label: "英文" },
                    ].filter((l) => (rTranslateMode === "llm" && (rBurnMode === "local" || rBurnMode === "mps")) || l.value !== "auto")
                      .map((l) => <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              {rTranslateMode === "llm" ? (
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label>LLM Provider</Label>
                    <Select value={rModelProvider} onValueChange={(v) => {
                      setRModelProvider(v);
                      const first = models.find((m) => m.provider === v);
                      if (first) setRModelName(first.name);
                    }}>
                      <SelectTrigger><SelectValue placeholder="选择 Provider" /></SelectTrigger>
                      <SelectContent>
                        {[...new Set(models.map((m) => m.provider))].map((p) => (
                          <SelectItem key={p} value={p}>{p}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>LLM 模型</Label>
                    <Select value={rModelName} onValueChange={setRModelName}>
                      <SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger>
                      <SelectContent>
                        {models.filter((m) => m.provider === rModelProvider).map((m) => (
                          <SelectItem key={m.name} value={m.name}>{m.label || m.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </>
              ) : null}
              <div className="flex flex-col gap-1.5">
                <Label>QPS（1-100）</Label>
                <Input type="number" min={1} max={100} value={rQps}
                  onChange={(e) => setRQps(Math.min(100, Math.max(1, Number(e.target.value) || 30)))} />
              </div>
            </div>
            <Separator />
            <p className="text-xs font-semibold text-muted-foreground">字幕提取参数</p>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label>FPS（2-10）</Label>
                <Input type="number" min={2} max={10} value={rCaptionFps}
                  onChange={(e) => setRCaptionFps(Math.min(10, Math.max(2, Number(e.target.value) || 5)))} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>字幕语言</Label>
                <Select value={rCaptionLang} onValueChange={setRCaptionLang}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {[{ value: "ch_ml", label: "中英混合" }, { value: "zh", label: "中文" },
                      { value: "en", label: "英文" }, { value: "ja", label: "日文" }, { value: "ko", label: "韩文" }]
                      .map((l) => <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>字幕区域（底部高度 %）</Label>
                <Input type="number" min={5} max={80} step={5} value={rCaptionRoiPct}
                  onChange={(e) => setRCaptionRoiPct(Math.min(80, Math.max(5, Number(e.target.value) || 35)))} />
                <p className="text-xs text-muted-foreground">→ [[{(1 - rCaptionRoiPct / 100).toFixed(2)},1],[0,1]]</p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>擦除区域（底部高度 %）</Label>
                <Input type="number" min={5} max={80} step={5} value={rDetextRegionPct}
                  onChange={(e) => setRDetextRegionPct(Math.min(80, Math.max(5, Number(e.target.value) || 35)))} />
                <p className="text-xs text-muted-foreground">→ [[0,{(1 - rDetextRegionPct / 100).toFixed(2)},1,{(rDetextRegionPct / 100).toFixed(2)}]]</p>
              </div>
            </div>
            <Separator />
            <p className="text-xs font-semibold text-muted-foreground">烧录字幕参数</p>
            <div className="grid gap-3 md:grid-cols-3">
              <div className="flex flex-col gap-1.5">
                <Label>字号（占视频高度 %）</Label>
                <Input type="number" min={1} max={30} step={1} value={rBurnFontSize}
                  onChange={(e) => setRBurnFontSize(Math.min(30, Math.max(1, Number(e.target.value) || 5)))} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>颜色</Label>
                <Input value={rBurnFontColor} onChange={(e) => setRBurnFontColor(e.target.value)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>位置 X</Label>
                <Input type="number" min={0} max={1} step={0.01} value={rBurnX}
                  onChange={(e) => setRBurnX(Number(e.target.value) || 0.5)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>位置 Y</Label>
                <Input type="number" min={0} max={1} step={0.01} value={rBurnY}
                  onChange={(e) => setRBurnY(Number(e.target.value) || 0.82)} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>文本宽度</Label>
                <Input type="number" min={0.1} max={1} step={0.01} value={rBurnTextWidth}
                  onChange={(e) => setRBurnTextWidth(Number(e.target.value) || 0.9)} />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowRerun(false)} disabled={rerunning}>取消</Button>
              <Button onClick={rerunAll} disabled={rerunning}>
                {rerunning ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
                {rerunning ? "提交中…" : "重新运行全部"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {job.target_langs.length > 1 ? (
        <div className="flex flex-wrap gap-2">
          {job.target_langs.map((lang) => {
            const label = TARGET_LANG_LABELS[lang] || lang;
            const isActive = lang === effectiveLang;
            return (
              <button
                key={lang}
                type="button"
                onClick={() => setActiveLang(lang)}
                className={
                  "rounded-md border px-3 py-1.5 text-sm transition-colors " +
                  (isActive
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background hover:bg-muted")
                }
              >
                {label} 视频列表
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
                const itemStage = t?.stage || item.stage;
                const itemError = t?.error || item.error;
                const ib = ITEM_BADGE[itemStatus] || ITEM_BADGE["pending"];
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
                        <span className="text-xs text-muted-foreground">⏱ {formatDuration(item.duration_seconds)}</span>
                        {item.clean_video_oss_uri ? (
                          <Badge variant="success" className="gap-1"><CheckCircle2 className="h-3 w-3" />已擦除</Badge>
                        ) : null}
                        {item.cleaned_srt_oss_uri ? (
                          <Badge variant="success" className="gap-1"><CheckCircle2 className="h-3 w-3" />已提取字幕</Badge>
                        ) : null}
                        <Badge variant={ib.variant}>
                          {itemStatus === "running" ? (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          ) : null}
                          {ib.label}
                        </Badge>
                        {itemStatus === "running" ? (
                          <Badge variant="muted">{STAGE_LABEL[itemStage] || itemStage}</Badge>
                        ) : null}
                        {item.warning ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Badge variant="warning" className="cursor-default gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                字幕为空
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-xs">
                              {item.warning}
                            </TooltipContent>
                          </Tooltip>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        {item.caption_status ? (
                          <span>提取: {item.caption_status}</span>
                        ) : null}
                        {item.detext_status ? (
                          <span>擦除: {item.detext_status}</span>
                        ) : null}
                        {t?.translation_status ? (
                          <span>烧录: {t.translation_status}</span>
                        ) : null}
                      </div>
                      {itemError ? (
                        <p className="text-xs text-destructive">错误：{itemError}</p>
                      ) : null}
                      {t?.bj_fetch_error && !t.output_video_bj_tos_public_url ? (
                        <p className="text-xs text-muted-foreground" title={t.bj_fetch_error}>
                          国内源同步失败，已用海外源兜底
                        </p>
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
