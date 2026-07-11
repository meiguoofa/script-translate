import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  createSubtitleEraseJob,
  getModels,
  getSubtitleEraseSettings,
  requestSubtitleEraseUploadUrls,
  requestMultipartUploadUrls,
  completeMultipartUpload,
  abortMultipartUpload,
  saveSubtitleEraseSettings,
} from "@/api/client";
import type { ModelOption } from "@/api/types";
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
import { uuid } from "@/lib/uuid";

const MULTIPART_THRESHOLD = 10 * 1024 * 1024; // <10MB 走单 PUT，≥10MB 走分片
const PART_CONCURRENCY = 5; // 前端分片并发数
const PART_MAX_RETRY = 3; // 单 part 失败重试次数

type UploadedFileResult = {
  filename: string;
  oss_uri: string;
  public_url: string;
  key: string;
  drama_index: number;
  episode_index: number;
};

async function uploadOneFileMultipart(
  file: File,
  job_id: string,
  index: number,
  drama_index: number,
  episode_index: number,
  setProgress: React.Dispatch<React.SetStateAction<Record<string, number>>>
): Promise<UploadedFileResult> {
  const init = await requestMultipartUploadUrls({
    filename: file.name,
    content_type: file.type || "video/mp4",
    file_size: file.size,
    job_id,
    index,
  });
  const contentType = file.type || "video/mp4";
  const uploadedBytes = new Array(init.parts.length).fill(0);
  const results: { part_number: number; etag: string }[] = [];

  const updatePct = () => {
    const loaded = uploadedBytes.reduce((a, b) => a + b, 0);
    setProgress((prev) => ({
      ...prev,
      [`${drama_index}-${episode_index}`]: Math.round((loaded / file.size) * 100),
    }));
  };

  let cursor = 0;
  const worker = async () => {
    while (cursor < init.parts.length) {
      const idx = cursor++;
      const p = init.parts[idx];
      const blob = file.slice(p.offset, p.offset + p.size);
      let etag: string | null = null;
      for (let attempt = 0; attempt < PART_MAX_RETRY; attempt++) {
        try {
          const resp = await axios.put(p.presigned_url, blob, {
            headers: { "Content-Type": contentType },
            onUploadProgress: (e) => {
              uploadedBytes[idx] = Math.min(p.size, e.loaded || 0);
              updatePct();
            },
          });
          etag = resp.headers["etag"];
          uploadedBytes[idx] = p.size;
          updatePct();
          break;
        } catch (err) {
          if (attempt === PART_MAX_RETRY - 1) throw err;
          uploadedBytes[idx] = 0;
          await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
        }
      }
      results.push({ part_number: p.part_number, etag: etag! });
    }
  };

  await Promise.all(Array.from({ length: PART_CONCURRENCY }, worker));

  try {
    const done = await completeMultipartUpload({
      job_id: init.job_id,
      key: init.key,
      upload_id: init.upload_id,
      parts: results,
    });
    return {
      filename: file.name,
      oss_uri: done.oss_uri,
      public_url: done.public_url,
      key: init.key,
      drama_index,
      episode_index,
    };
  } catch (err) {
    await abortMultipartUpload(init.key, init.upload_id).catch(() => {});
    throw err;
  }
}

async function uploadOneFileSimple(
  file: File,
  presigned_url: string,
  drama_index: number,
  episode_index: number,
  setProgress: React.Dispatch<React.SetStateAction<Record<string, number>>>
) {
  await axios.put(presigned_url, file, {
    headers: { "Content-Type": file.type || "video/mp4" },
    onUploadProgress: (event) => {
      if (event.total) {
        setProgress((prev) => ({
          ...prev,
          [`${drama_index}-${episode_index}`]: Math.round(
            (event.loaded / event.total!) * 100
          ),
        }));
      }
    },
  });
}

const TARGET_LANGS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
  { value: "vi", label: "越南语" },
  { value: "th", label: "泰语" },
  { value: "id", label: "印尼语" },
  { value: "ms", label: "马来语" },
  { value: "pt", label: "葡萄牙语" },
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

type FormParams = {
  detextMode: "basic" | "advanced";
  translateMode: "aliyun" | "llm";
  burnMode: "local" | "aliyun" | "mps";
  placementMode: "safe_bottom" | "simple_bottom";
  sourceLang: string;
  targetLangs: string[];
  modelProvider: string;
  modelName: string;
  qps: number;
  captionFps: number;
  captionLang: string;
  captionTrack: string;
  captionRoiPct: number;
  captionSep: boolean;
  detextRegionPct: number;
  burnFontSize: number;
  burnFontColor: string;
  burnX: number;
  burnY: number;
  burnTextWidth: number;
};

const DEFAULT_FORM_PARAMS: FormParams = {
  detextMode: "advanced",
  translateMode: "llm",
  burnMode: "mps",
  placementMode: "safe_bottom",
  sourceLang: "auto",
  targetLangs: ["zh"],
  modelProvider: "",
  modelName: "",
  qps: 10,
  captionFps: 5,
  captionLang: "ch_ml",
  captionTrack: "main",
  captionRoiPct: 35,
  captionSep: false,
  detextRegionPct: 35,
  burnFontSize: 5,
  burnFontColor: "#FFFFFF",
  burnX: 0.5,
  burnY: 0.82,
  burnTextWidth: 0.9,
};

export function SubtitleErasePage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [dramas, setDramas] = useState<Drama[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);

  // 表单参数：先用默认值初始化，verify 后从服务器加载覆盖
  const [detextMode, setDetextMode] = useState<"basic" | "advanced">(DEFAULT_FORM_PARAMS.detextMode);
  const [translateMode, setTranslateMode] = useState<"aliyun" | "llm">(DEFAULT_FORM_PARAMS.translateMode);
  const [burnMode, setBurnMode] = useState<"local" | "aliyun" | "mps">(DEFAULT_FORM_PARAMS.burnMode);
  const [placementMode, setPlacementMode] = useState<"safe_bottom" | "simple_bottom">(DEFAULT_FORM_PARAMS.placementMode);
  const [sourceLang, setSourceLang] = useState<string>(DEFAULT_FORM_PARAMS.sourceLang);
  const [targetLangs, setTargetLangs] = useState<string[]>(DEFAULT_FORM_PARAMS.targetLangs);
  const [modelProvider, setModelProvider] = useState<string>(DEFAULT_FORM_PARAMS.modelProvider);
  const [modelName, setModelName] = useState<string>(DEFAULT_FORM_PARAMS.modelName);
  const [qps, setQps] = useState<number>(DEFAULT_FORM_PARAMS.qps);

  const [captionFps, setCaptionFps] = useState<number>(DEFAULT_FORM_PARAMS.captionFps);
  const [captionLang, setCaptionLang] = useState<string>(DEFAULT_FORM_PARAMS.captionLang);
  const [captionTrack, setCaptionTrack] = useState<string>(DEFAULT_FORM_PARAMS.captionTrack);
  const [captionRoiPct, setCaptionRoiPct] = useState<number>(DEFAULT_FORM_PARAMS.captionRoiPct);
  const [captionSep, setCaptionSep] = useState<boolean>(DEFAULT_FORM_PARAMS.captionSep);

  const [detextRegionPct, setDetextRegionPct] = useState<number>(DEFAULT_FORM_PARAMS.detextRegionPct);
  const [burnFontSize, setBurnFontSize] = useState<number>(DEFAULT_FORM_PARAMS.burnFontSize);
  const [burnFontColor, setBurnFontColor] = useState<string>(DEFAULT_FORM_PARAMS.burnFontColor);
  const [burnX, setBurnX] = useState<number>(DEFAULT_FORM_PARAMS.burnX);
  const [burnY, setBurnY] = useState<number>(DEFAULT_FORM_PARAMS.burnY);
  const [burnTextWidth, setBurnTextWidth] = useState<number>(DEFAULT_FORM_PARAMS.burnTextWidth);

  const [progress, setProgress] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);

  // 加载完成标志：避免首次加载触发的 setXxx 又触发保存
  const settingsLoadedRef = useRef(false);
  // 防抖保存的 timer
  const saveTimerRef = useRef<number | null>(null);

  // 验证后从服务器加载已保存的表单参数
  useEffect(() => {
    if (!verified) return;
    getSubtitleEraseSettings()
      .then((data) => {
        if (!data || Object.keys(data).length === 0) return;
        // 用 server 数据覆盖 state（只覆盖存在的字段）
        if (data.detextMode) setDetextMode(data.detextMode as "basic" | "advanced");
        if (data.translateMode) setTranslateMode(data.translateMode as "aliyun" | "llm");
        if (data.burnMode) setBurnMode(data.burnMode as "local" | "aliyun" | "mps");
        if (data.placementMode) setPlacementMode(data.placementMode as "safe_bottom" | "simple_bottom");
        if (typeof data.sourceLang === "string") setSourceLang(data.sourceLang);
        if (Array.isArray(data.targetLangs)) setTargetLangs(data.targetLangs);
        if (typeof data.modelProvider === "string" && data.modelProvider) setModelProvider(data.modelProvider);
        if (typeof data.modelName === "string" && data.modelName) setModelName(data.modelName);
        if (typeof data.qps === "number") setQps(data.qps);
        if (typeof data.captionFps === "number") setCaptionFps(data.captionFps);
        if (typeof data.captionLang === "string") setCaptionLang(data.captionLang);
        if (typeof data.captionTrack === "string") setCaptionTrack(data.captionTrack);
        if (typeof data.captionRoiPct === "number") setCaptionRoiPct(data.captionRoiPct);
        else if (typeof data.captionRoi === "string" && data.captionRoi) {
          try { const r = JSON.parse(data.captionRoi as string); setCaptionRoiPct(Math.round((1 - r[0][0]) * 100)); } catch { /* ignore */ }
        }
        if (typeof data.captionSep === "boolean") setCaptionSep(data.captionSep);
        if (typeof data.detextRegionPct === "number") setDetextRegionPct(data.detextRegionPct);
        else if (typeof data.detextLimitRegion === "string" && data.detextLimitRegion) {
          try { const r = JSON.parse(data.detextLimitRegion as string); setDetextRegionPct(Math.round(r[0][3] * 100)); } catch { /* ignore */ }
        }
        if (typeof data.burnFontSize === "number") setBurnFontSize(data.burnFontSize);
        if (typeof data.burnFontColor === "string") setBurnFontColor(data.burnFontColor);
        if (typeof data.burnX === "number") setBurnX(data.burnX);
        if (typeof data.burnY === "number") setBurnY(data.burnY);
        if (typeof data.burnTextWidth === "number") setBurnTextWidth(data.burnTextWidth);
      })
      .catch(() => {
        // 加载失败静默处理，用默认值即可
      })
      .finally(() => {
        settingsLoadedRef.current = true;
      });
  }, [verified]);

  useEffect(() => {
    if (!verified) return;
    getModels()
      .then((list) => {
        setModels(list);
        // 用函数式更新避免 stale closure：仅当当前值为空时才填默认
        const def = list.find((m) => m.default) ?? list[0];
        if (def) {
          setModelProvider((curr) => curr || def.provider);
          setModelName((curr) => curr || def.name);
        }
      })
      .catch(() => toast.error("模型列表加载失败"));
  }, [verified]); // eslint-disable-line react-hooks/exhaustive-deps

  // models 加载后，若 provider 有值但 model 为空，自动填该 provider 下第一个 model
  // 解决：用户在 getModels 完成前手选 provider，model 联动漏填的问题
  useEffect(() => {
    if (models.length === 0) return;
    if (!modelProvider) return;
    if (modelName) return;
    const first = models.find((m) => m.provider === modelProvider);
    if (first) setModelName(first.name);
  }, [models, modelProvider, modelName]);

  // 表单参数变化时防抖保存到服务器（标题和上传文件不保存）
  useEffect(() => {
    if (!settingsLoadedRef.current) return;
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => {
      // 关键：modelProvider/modelName 为空时用默认值兜底，避免保存空字符串
      // 否则下次加载会用空字符串覆盖 getModels 填的默认值，形成循环
      const defModel = models.find((m) => m.default) ?? models[0];
      const provider = modelProvider || defModel?.provider || "";
      const name = modelName || defModel?.name || "";
      const params: FormParams = {
        detextMode, translateMode, burnMode, placementMode,
        sourceLang, targetLangs, modelProvider: provider, modelName: name, qps,
        captionFps, captionLang, captionTrack, captionRoiPct, captionSep,
        detextRegionPct, burnFontSize, burnFontColor,
        burnX, burnY, burnTextWidth,
      };
      saveSubtitleEraseSettings(params).catch(() => {
        // 保存失败静默处理
      });
    }, 800);
    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, [
    detextMode, translateMode, burnMode, placementMode,
    sourceLang, targetLangs, modelProvider, modelName, qps,
    captionFps, captionLang, captionTrack, captionRoiPct, captionSep,
    detextRegionPct, burnFontSize, burnFontColor,
    burnX, burnY, burnTextWidth,
    models,
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

      const job_id = uuid();

      const smallIndices: number[] = [];
      const multipartIndices: number[] = [];
      allFiles.forEach((f, i) => {
        if (f.file.size >= MULTIPART_THRESHOLD) {
          multipartIndices.push(i);
        } else {
          smallIndices.push(i);
        }
      });

      const results: UploadedFileResult[] = new Array(allFiles.length);

      if (smallIndices.length > 0) {
        const smallResp = await requestSubtitleEraseUploadUrls({
          files: smallIndices.map((i) => ({
            filename: allFiles[i].filename,
            content_type: allFiles[i].file.type || "video/mp4",
          })),
          job_id,
        });
        await Promise.all(
          smallResp.entries.map((entry, idx) => {
            const i = smallIndices[idx];
            const f = allFiles[i];
            return uploadOneFileSimple(
              f.file,
              entry.presigned_url,
              f.drama_index,
              f.episode_index,
              setProgress
            ).then(() => {
              results[i] = {
                filename: f.filename,
                oss_uri: entry.oss_uri,
                public_url: entry.public_url,
                key: entry.key,
                drama_index: f.drama_index,
                episode_index: f.episode_index,
              };
            });
          })
        );
      }

      if (multipartIndices.length > 0) {
        const multipartResults = await Promise.all(
          multipartIndices.map((i) => {
            const f = allFiles[i];
            return uploadOneFileMultipart(
              f.file,
              job_id,
              i,
              f.drama_index,
              f.episode_index,
              setProgress
            );
          })
        );
        multipartIndices.forEach((i, idx) => {
          results[i] = multipartResults[idx];
        });
      }

      const items = results.map((r) => ({
        filename: r.filename,
        oss_uri: r.oss_uri,
        public_url: r.public_url,
        key: r.key,
        drama_index: r.drama_index,
        episode_index: r.episode_index,
      }));

      const job = await createSubtitleEraseJob({
        job_id,
        title: title.trim(),
        detext_mode: detextMode,
        translate_mode: translateMode,
        burn_mode: burnMode,
        placement_mode: placementMode,
        source_lang: translateMode === "aliyun" || burnMode === "aliyun" ? sourceLang : null,
        target_langs: targetLangs,
        model_provider: translateMode === "llm" ? modelProvider : null,
        model_name: translateMode === "llm" ? modelName : null,
        qps,
        caption_fps: captionFps,
        caption_lang: captionLang,
        caption_track: captionTrack,
        caption_roi: `[[${(1 - captionRoiPct / 100).toFixed(2)},1],[0,1]]`,
        caption_sep: captionSep,
        detext_limit_region: `[[0,${(1 - detextRegionPct / 100).toFixed(2)},1,${(detextRegionPct / 100).toFixed(2)}]]`,
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
                    const mode = v as "local" | "aliyun" | "mps";
                    setBurnMode(mode);
                    if (mode === "local" || mode === "mps") {
                      // 本机/MPS 烧录必须搭配 LLM 翻译
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
                    <SelectItem value="mps">阿里云 MPS 烧录（默认，推荐）</SelectItem>
                    <SelectItem value="local">本机 ffmpeg 烧录（输出 TOS 新加坡）</SelectItem>
                    <SelectItem value="aliyun">阿里云 IMS 烧录（需 IMS 视频翻译套餐）</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {burnMode === "mps"
                    ? "MPS 烧录不依赖 IMS 订阅，使用自定义模板保留原视频参数，输出落 OSS"
                    : burnMode === "local"
                      ? "本机 ffmpeg 烧录；输出上传到火山引擎 TOS 新加坡桶，服务器零带宽"
                      : "阿里云 IMS 一体翻译+烧录，需 IMS 视频翻译套餐"}
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
                  disabled={translateMode === "llm" && (burnMode === "local" || burnMode === "mps")}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SOURCE_LANGS.filter(
                      (l) =>
                        (translateMode === "llm" && (burnMode === "local" || burnMode === "mps")) ||
                        l.value !== "auto"
                    ).map((l) => (
                      <SelectItem key={l.value} value={l.value}>
                        {l.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {(translateMode === "llm" && (burnMode === "local" || burnMode === "mps"))
                    ? "LLM 翻译模式：源语言由模型自动识别"
                    : translateMode === "aliyun" || burnMode === "aliyun"
                      ? "阿里云翻译/烧录必须明确源语言；如需自动识别，请切换为 LLM + MPS 烧录"
                      : ""}
                </p>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>翻译目标语言（可多选）</Label>
                <div className="flex flex-wrap gap-3 rounded-md border p-3">
                  {TARGET_LANGS.map((l) => {
                    const checked = targetLangs.includes(l.value);
                    return (
                      <label key={l.value} className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setTargetLangs((prev) =>
                                prev.includes(l.value) ? prev : [...prev, l.value]
                              );
                            } else {
                              setTargetLangs((prev) =>
                                prev.length > 1 ? prev.filter((v) => v !== l.value) : prev
                              );
                            }
                          }}
                          className="h-4 w-4"
                        />
                        <span className="text-sm">{l.label}</span>
                      </label>
                    );
                  })}
                </div>
                {targetLangs.length === 0 ? (
                  <p className="text-xs text-destructive">至少选择一个目标语言</p>
                ) : null}
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
                  <Label htmlFor="caption-roi">字幕区域（底部高度 %，默认 35）</Label>
                  <Input
                    id="caption-roi"
                    type="number"
                    min={5}
                    max={80}
                    step={5}
                    value={captionRoiPct}
                    onChange={(e) => setCaptionRoiPct(Math.min(80, Math.max(5, Number(e.target.value) || 35)))}
                  />
                  <p className="text-xs text-muted-foreground">生成 ROI [[{(1 - captionRoiPct / 100).toFixed(2)},1],[0,1]]</p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="limit-region">字幕擦除区域（底部高度 %，默认 35）</Label>
                  <Input
                    id="limit-region"
                    type="number"
                    min={5}
                    max={80}
                    step={5}
                    value={detextRegionPct}
                    onChange={(e) => setDetextRegionPct(Math.min(80, Math.max(5, Number(e.target.value) || 35)))}
                  />
                  <p className="text-xs text-muted-foreground">生成 [[0,{(1 - detextRegionPct / 100).toFixed(2)},1,{(detextRegionPct / 100).toFixed(2)}]]</p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="burn-font-size">烧录字号（占视频高度 %，默认 5）</Label>
                  <Input
                    id="burn-font-size"
                    type="number"
                    min={1}
                    max={30}
                    step={1}
                    value={burnFontSize}
                    onChange={(e) => setBurnFontSize(Math.min(30, Math.max(1, Number(e.target.value) || 5)))}
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
            <SummaryRow label="烧录模式" value={burnMode === "local" ? "本机 ffmpeg" : burnMode === "mps" ? "阿里云 MPS" : "阿里云 IMS"} />
            <SummaryRow label="字幕放置" value={placementMode === "safe_bottom" ? "safe_bottom" : "simple_bottom"} />
            <SummaryRow label="目标语言" value={targetLangs.map((v) => TARGET_LANGS.find((l) => l.value === v)?.label || v).join("、")} />
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
