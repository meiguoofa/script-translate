import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  createSubtitleEraseJob,
  getModels,
  requestSubtitleEraseUploadUrls,
} from "@/api/client";
import type { ModelOption, SubtitleEraseUploadEntry } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { toast } from "@/components/ui/sonner";
import { MultiFolderDropzone, type Drama } from "@/components/MultiFolderDropzone";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";

const TARGET_LANGS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
  { value: "vi", label: "越南语" },
  { value: "th", label: "泰语" },
  { value: "id", label: "印尼语" },
  { value: "ms", label: "马来语" },
];

const SOURCE_LANGS = [
  { value: "auto", label: "自动识别" },
  { value: "ch_ml", label: "中英混合" },
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

const CAPTION_LANGS = [
  { value: "ch_ml", label: "中英混合" },
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

const FORM_PARAMS_STORAGE_KEY = "subtitle-erase-form-params";

type FormParams = {
  detextMode: "basic" | "advanced";
  translateMode: "aliyun" | "llm";
  burnMode: "local" | "aliyun";
  placementMode: "safe_bottom" | "simple_bottom";
  sourceLang: string;
  targetLang: string;
  modelProvider: string;
  modelName: string;
  qps: number;
  captionFps: number;
  captionLang: string;
  captionTrack: string;
  captionRoi: string;
  captionSep: boolean;
  detextLimitRegion: string;
  burnFontSize: number;
  burnFontColor: string;
  burnX: number;
  burnY: number;
  burnTextWidth: number;
};

const DEFAULT_FORM_PARAMS: FormParams = {
  detextMode: "advanced",
  translateMode: "llm",
  burnMode: "local",
  placementMode: "safe_bottom",
  sourceLang: "auto",
  targetLang: "zh",
  modelProvider: "",
  modelName: "",
  qps: 10,
  captionFps: 5,
  captionLang: "ch_ml",
  captionTrack: "main",
  captionRoi: "",
  captionSep: false,
  detextLimitRegion: "",
  burnFontSize: 72,
  burnFontColor: "#FFFFFF",
  burnX: 0.5,
  burnY: 0.82,
  burnTextWidth: 0.9,
};

function loadStoredFormParams(): FormParams {
  try {
    const raw = localStorage.getItem(FORM_PARAMS_STORAGE_KEY);
    if (!raw) return DEFAULT_FORM_PARAMS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_FORM_PARAMS, ...parsed };
  } catch {
    return DEFAULT_FORM_PARAMS;
  }
}

export function SubtitleErasePage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [dramas, setDramas] = useState<Drama[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);

  const [stored] = useState(loadStoredFormParams);
  const [detextMode, setDetextMode] = useState<"basic" | "advanced">(stored.detextMode);
  const [translateMode, setTranslateMode] = useState<"aliyun" | "llm">(stored.translateMode);
  const [burnMode, setBurnMode] = useState<"local" | "aliyun">(stored.burnMode);
  const [placementMode, setPlacementMode] = useState<"safe_bottom" | "simple_bottom">(stored.placementMode);
  const [sourceLang, setSourceLang] = useState<string>(stored.sourceLang);
  const [targetLang, setTargetLang] = useState<string>(stored.targetLang);
  const [modelProvider, setModelProvider] = useState<string>(stored.modelProvider);
  const [modelName, setModelName] = useState<string>(stored.modelName);
  const [qps, setQps] = useState<number>(stored.qps);

  const [captionFps, setCaptionFps] = useState<number>(stored.captionFps);
  const [captionLang, setCaptionLang] = useState<string>(stored.captionLang);
  const [captionTrack, setCaptionTrack] = useState<string>(stored.captionTrack);
  const [captionRoi, setCaptionRoi] = useState<string>(stored.captionRoi);
  const [captionSep, setCaptionSep] = useState<boolean>(stored.captionSep);

  const [detextLimitRegion, setDetextLimitRegion] = useState<string>(stored.detextLimitRegion);
  const [burnFontSize, setBurnFontSize] = useState<number>(stored.burnFontSize);
  const [burnFontColor, setBurnFontColor] = useState<string>(stored.burnFontColor);
  const [burnX, setBurnX] = useState<number>(stored.burnX);
  const [burnY, setBurnY] = useState<number>(stored.burnY);
  const [burnTextWidth, setBurnTextWidth] = useState<number>(stored.burnTextWidth);

  const [progress, setProgress] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!verified) return;
    getModels()
      .then((list) => {
        setModels(list);
        // 仅当上次没有保存过 provider/model 时，才用默认值
        if (!modelProvider && !modelName) {
          const def = list.find((m) => m.default) ?? list[0];
          if (def) {
            setModelProvider(def.provider);
            setModelName(def.name);
          }
        }
      })
      .catch(() => toast.error("模型列表加载失败"));
  }, [verified]); // eslint-disable-line react-hooks/exhaustive-deps

  // 表单参数变化时持久化到 localStorage（标题和上传文件不保存）
  useEffect(() => {
    const params: FormParams = {
      detextMode, translateMode, burnMode, placementMode,
      sourceLang, targetLang, modelProvider, modelName, qps,
      captionFps, captionLang, captionTrack, captionRoi, captionSep,
      detextLimitRegion, burnFontSize, burnFontColor,
      burnX, burnY, burnTextWidth,
    };
    try {
      localStorage.setItem(FORM_PARAMS_STORAGE_KEY, JSON.stringify(params));
    } catch {
      // 忽略 localStorage 写入失败（如隐私模式）
    }
  }, [
    detextMode, translateMode, burnMode, placementMode,
    sourceLang, targetLang, modelProvider, modelName, qps,
    captionFps, captionLang, captionTrack, captionRoi, captionSep,
    detextLimitRegion, burnFontSize, burnFontColor,
    burnX, burnY, burnTextWidth,
  ]);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  const totalFiles = dramas.reduce((s, d) => s + d.files.length, 0);
  const canSubmit =
    Boolean(title.trim()) &&
    totalFiles > 0 &&
    !submitting &&
    (translateMode === "aliyun" ? Boolean(sourceLang) : Boolean(modelProvider && modelName)) &&
    (burnMode === "aliyun" ? Boolean(sourceLang) && sourceLang !== "auto" : true);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setProgress({});
    try {
      const allFiles = dramas.flatMap((d, di) =>
        d.files.map((f, fi) => ({ ...f, drama_index: di, episode_index: fi }))
      );

      const upload = await requestSubtitleEraseUploadUrls({
        files: allFiles.map((f) => ({
          filename: f.filename,
          content_type: f.file.type || "video/mp4",
        })),
      });

      await Promise.all(
        upload.entries.map((entry: SubtitleEraseUploadEntry, index: number) =>
          axios.put(entry.presigned_url, allFiles[index].file, {
            headers: { "Content-Type": allFiles[index].file.type || "video/mp4" },
            onUploadProgress: (event) => {
              if (event.total) {
                setProgress((prev) => ({
                  ...prev,
                  [`${allFiles[index].drama_index}-${allFiles[index].episode_index}`]: Math.round(
                    (event.loaded / event.total!) * 100
                  ),
                }));
              }
            },
          })
        )
      );

      const items = upload.entries.map((entry, index) => {
        const f = allFiles[index];
        return {
          filename: f.filename,
          oss_uri: entry.oss_uri,
          public_url: entry.public_url,
          key: entry.key,
          drama_index: f.drama_index,
          episode_index: f.episode_index,
        };
      });

      const job = await createSubtitleEraseJob({
        job_id: upload.job_id,
        title: title.trim(),
        detext_mode: detextMode,
        translate_mode: translateMode,
        burn_mode: burnMode,
        placement_mode: placementMode,
        source_lang: translateMode === "aliyun" || burnMode === "aliyun" ? sourceLang : null,
        target_lang: targetLang,
        model_provider: translateMode === "llm" ? modelProvider : null,
        model_name: translateMode === "llm" ? modelName : null,
        qps,
        caption_fps: captionFps,
        caption_lang: captionLang,
        caption_track: captionTrack,
        caption_roi: captionRoi.trim() || null,
        caption_sep: captionSep,
        detext_limit_region: detextLimitRegion.trim() || null,
        burn_font_size: burnFontSize,
        burn_font_color: burnFontColor,
        burn_font_color_opacity: 1.0,
        burn_x: burnX,
        burn_y: burnY,
        burn_text_width: burnTextWidth,
        items,
        original_filenames: allFiles.map((f) => f.filename),
      });

      toast.success("任务已提交，正在擦除字幕并翻译");
      navigate(`/subtitle-erase/${job.id}`);
    } catch (error: any) {
      console.error(error);
      const detail = error?.response?.data?.detail || "上传或提交失败";
      toast.error(detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>视频字幕擦除 + 翻译</CardTitle>
          <CardDescription>
            上传一个或多个文件夹（每个文件夹 = 一部短剧），按集顺序调用阿里云 IMS 字幕提取/擦除 + 翻译，输出含译制字幕的视频到 OSS。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="title">批次标题</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如：火花瞬间燃点 全剧字幕擦除翻译"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>视频文件夹（每部剧一个文件夹）</Label>
              <MultiFolderDropzone dramas={dramas} onChange={setDramas} disabled={submitting} />
            </div>

            {submitting && totalFiles > 0 ? (
              <div className="flex flex-col gap-2">
                <Label>上传进度</Label>
                {dramas.flatMap((d, di) =>
                  d.files.map((f, fi) => {
                    const key = `${di}-${fi}`;
                    return (
                      <div key={key} className="flex flex-col gap-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="truncate">{d.name} / 第 {fi + 1} 集 · {f.filename}</span>
                          <span>{progress[key] ?? 0}%</span>
                        </div>
                        <Progress value={progress[key] ?? 0} className="h-1.5" />
                      </div>
                    );
                  })
                )}
              </div>
            ) : null}

            <Separator />

            <div className="grid gap-4 md:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label>字幕擦除模式</Label>
                <Select value={detextMode} onValueChange={(v) => setDetextMode(v as "basic" | "advanced")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="advanced">高级版（algo-video-detext-new，效果更好）</SelectItem>
                    <SelectItem value="basic">基础版（默认模型）</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>翻译模式</Label>
                <Select
                  value={translateMode}
                  onValueChange={(v) => {
                    const mode = v as "aliyun" | "llm";
                    setTranslateMode(mode);
                    // 切到阿里云翻译时必须搭配阿里云烧录（IMS 一体）
                    if (mode === "aliyun") {
                      setBurnMode("aliyun");
                      if (sourceLang === "auto") setSourceLang("zh");
                    }
                    // LLM 翻译时若烧录是 aliyun，保持（合法：LLM 译 + IMS 烧）
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="llm">工程内 LLM 翻译（豆包/Deepseek 等，默认）</SelectItem>
                    <SelectItem value="aliyun">阿里云翻译 API（需 IMS 订阅）</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>烧录模式</Label>
                <Select
                  value={burnMode}
                  onValueChange={(v) => {
                    const mode = v as "local" | "aliyun";
                    setBurnMode(mode);
                    // 本机烧录必须搭配 LLM 翻译（IMS 翻译不单独提供 SRT 译文）
                    if (mode === "local") {
                      setTranslateMode("llm");
                    } else {
                      // 阿里云烧录：源语言不能是 auto
                      if (sourceLang === "auto") setSourceLang("zh");
                    }
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="local">本机 ffmpeg 烧录（默认，输出 TOS 新加坡）</SelectItem>
                    <SelectItem value="aliyun">阿里云 IMS 烧录（需 IMS 视频翻译套餐）</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  本机烧录不依赖 IMS 订阅；输出上传到火山引擎 TOS 新加坡桶，服务器零带宽
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>字幕放置模式</Label>
                <Select value={placementMode} onValueChange={(v) => setPlacementMode(v as "safe_bottom" | "simple_bottom")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="safe_bottom">safe_bottom（底部加黑边，字幕在黑边内）</SelectItem>
                    <SelectItem value="simple_bottom">simple_bottom（直接烧到原画面底部）</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>源语言</Label>
                <Select
                  value={sourceLang}
                  onValueChange={setSourceLang}
                  disabled={translateMode === "llm" && burnMode === "local"}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SOURCE_LANGS.filter(
                      (l) =>
                        (translateMode === "llm" && burnMode === "local") ||
                        l.value !== "auto"
                    ).map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {(translateMode === "llm" && burnMode === "local")
                    ? "LLM 翻译 + 本机烧录：源语言由模型自动识别"
                    : translateMode === "aliyun" || burnMode === "aliyun"
                      ? "阿里云翻译/烧录必须明确源语言；如需自动识别，请切换为 LLM + 本机烧录"
                      : ""}
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>翻译目标语言</Label>
                <Select value={targetLang} onValueChange={setTargetLang}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TARGET_LANGS.map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {translateMode === "llm" ? (
                <>
                  <div className="flex flex-col gap-1.5">
                    <Label>LLM Provider</Label>
                    <Select
                      value={modelProvider}
                      onValueChange={(v) => {
                        setModelProvider(v);
                        const first = models.find((m) => m.provider === v);
                        if (first) setModelName(first.name);
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="选择 Provider" />
                      </SelectTrigger>
                      <SelectContent>
                        {[...new Set(models.map((m) => m.provider))].map((p) => (
                          <SelectItem key={p} value={p}>
                            {p}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>LLM 模型</Label>
                    <Select value={modelName} onValueChange={setModelName}>
                      <SelectTrigger>
                        <SelectValue placeholder="选择模型" />
                      </SelectTrigger>
                      <SelectContent>
                        {models
                          .filter((m) => m.provider === modelProvider)
                          .map((m) => (
                            <SelectItem key={m.name} value={m.name}>
                              {m.label || m.name}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  </div>
                </>
              ) : null}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="qps">QPS（1-50，默认 10）</Label>
                <Input
                  id="qps"
                  type="number"
                  min={1}
                  max={50}
                  step={1}
                  value={qps}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (Number.isNaN(v)) return;
                    setQps(Math.min(50, Math.max(1, Math.round(v))));
                  }}
                />
                <p className="text-xs text-muted-foreground">全工程共享，控制对阿里云 IMS 的调用速率</p>
              </div>
            </div>

            <Separator />

            <div className="flex flex-col gap-3">
              <Label className="text-sm font-semibold">高级参数（可选）</Label>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="caption-fps">字幕提取 FPS（2-10）</Label>
                  <Input
                    id="caption-fps"
                    type="number"
                    min={2}
                    max={10}
                    value={captionFps}
                    onChange={(e) => setCaptionFps(Math.min(10, Math.max(2, Number(e.target.value) || 5)))}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>字幕提取语言</Label>
                  <Select value={captionLang} onValueChange={setCaptionLang}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CAPTION_LANGS.map((l) => (
                        <SelectItem key={l.value} value={l.value}>
                          {l.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>字幕提取 track</Label>
                  <Select value={captionTrack} onValueChange={setCaptionTrack}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="main">main（仅主字幕）</SelectItem>
                      <SelectItem value="all">all（全部字幕）</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="caption-roi">字幕提取 ROI（JSON）</Label>
                  <Input
                    id="caption-roi"
                    value={captionRoi}
                    onChange={(e) => setCaptionRoi(e.target.value)}
                    placeholder='默认 [[0.65,1],[0,1]]（底部 35%）'
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="limit-region">字幕擦除 LimitRegion（JSON）</Label>
                  <Input
                    id="limit-region"
                    value={detextLimitRegion}
                    onChange={(e) => setDetextLimitRegion(e.target.value)}
                    placeholder='默认 [[0,0.65,1,0.35]]（底部 35%）'
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="burn-font-size">烧录字号</Label>
                  <Input
                    id="burn-font-size"
                    type="number"
                    min={8}
                    max={200}
                    value={burnFontSize}
                    onChange={(e) => setBurnFontSize(Number(e.target.value) || 72)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="burn-color">烧录颜色</Label>
                  <Input
                    id="burn-color"
                    value={burnFontColor}
                    onChange={(e) => setBurnFontColor(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="burn-x">烧录位置 X（0-1）</Label>
                  <Input
                    id="burn-x"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={burnX}
                    onChange={(e) => setBurnX(Number(e.target.value) || 0.5)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="burn-y">烧录位置 Y（0-1）</Label>
                  <Input
                    id="burn-y"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={burnY}
                    onChange={(e) => setBurnY(Number(e.target.value) || 0.82)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="burn-width">烧录文本宽度（0.1-1）</Label>
                  <Input
                    id="burn-width"
                    type="number"
                    min={0.1}
                    max={1}
                    step={0.01}
                    value={burnTextWidth}
                    onChange={(e) => setBurnTextWidth(Number(e.target.value) || 0.9)}
                  />
                </div>
              </div>
            </div>

            <div className="flex justify-end">
              <Button type="submit" size="lg" disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {submitting ? "处理中…" : "开始上传并擦除翻译"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">任务摘要</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <SummaryRow label="标题" value={title || "未填写"} />
            <SummaryRow label="剧数" value={String(dramas.length)} />
            <SummaryRow label="总集数" value={String(totalFiles)} />
            <SummaryRow label="擦除模式" value={detextMode === "advanced" ? "高级版" : "基础版"} />
            <SummaryRow label="翻译模式" value={translateMode === "aliyun" ? "阿里云翻译" : "LLM 翻译"} />
            <SummaryRow label="烧录模式" value={burnMode === "local" ? "本机 ffmpeg" : "阿里云 IMS"} />
            <SummaryRow label="字幕放置" value={placementMode === "safe_bottom" ? "safe_bottom" : "simple_bottom"} />
            <SummaryRow label="目标语言" value={TARGET_LANGS.find((l) => l.value === targetLang)?.label || targetLang} />
            <SummaryRow label="QPS" value={String(qps)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">流程说明</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
            <p>1. 浏览器直传阿里云 OSS（不经过本服务）。</p>
            <p>2. 每集并行：CaptionExtraction 提取 SRT + VideoDetext 擦除字幕。</p>
            <p>3. SRT 清洗后翻译（阿里云或 LLM）。</p>
            <p>4. SubmitVideoTranslationJob 把译文字幕烧录到无字幕视频。</p>
            <p>5. 输出含译制字幕的 mp4 到 OSS。</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-medium">{value}</span>
    </div>
  );
}
