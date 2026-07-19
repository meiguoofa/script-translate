import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  abortBaiduVodMultipart,
  completeBaiduVodMultipart,
  createBaiduVodJob,
  getBaiduVodRuntimeLimits,
  getBaiduVodSettings,
  requestBaiduVodMultipartUrls,
  requestBaiduVodUploadUrls,
  saveBaiduVodSettings,
} from "@/api/client";
import type {
  BaiduVodFontConfig,
  BaiduVodOcrArea,
  BaiduVodRuntimeLimits,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { toast } from "@/components/ui/sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiFolderDropzone, type Drama } from "@/components/MultiFolderDropzone";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";
import { uuid } from "@/lib/uuid";

const MULTIPART_THRESHOLD = 10 * 1024 * 1024;
const PART_CONCURRENCY = 5;
const PART_MAX_RETRY = 3;

// 语言代码 -> 标签
const SOURCE_LANGS = [
  { value: "zh-CN", label: "中文" },
  { value: "en-US", label: "英文" },
  { value: "ja-JP", label: "日文" },
  { value: "ko-KR", label: "韩文" },
  { value: "de-DE", label: "德文" },
  { value: "fr-FR", label: "法文" },
  { value: "ru-RU", label: "俄文" },
  { value: "es-ES", label: "西班牙文" },
  { value: "pt-PT", label: "葡萄牙文" },
  { value: "id-ID", label: "印尼文" },
  { value: "vi-VN", label: "越南文" },
  { value: "th-TH", label: "泰文" },
];

const TARGET_LANGS = SOURCE_LANGS; // 同源语言列表

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
  const init = await requestBaiduVodMultipartUrls({
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
          etag = (resp.headers["etag"] as string) || "";
          uploadedBytes[idx] = p.size;
          updatePct();
          break;
        } catch (err) {
          if (attempt === PART_MAX_RETRY - 1) throw err;
          uploadedBytes[idx] = 0;
          await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
        }
      }
      results.push({ part_number: p.part_number, etag: etag ?? "" });
    }
  };

  await Promise.all(Array.from({ length: PART_CONCURRENCY }, worker));

  try {
    const done = await completeBaiduVodMultipart({
      job_id: init.job_id,
      key: init.key,
      upload_id: init.upload_id,
      parts: results,
    });
    return {
      filename: file.name,
      oss_uri: done.bos_uri,
      public_url: done.public_url,
      key: init.key,
      drama_index,
      episode_index,
    };
  } catch (err) {
    await abortBaiduVodMultipart(init.key, init.upload_id).catch(() => {});
    throw err;
  }
}

async function uploadOneFileSimple(
  file: File,
  presigned_url: string,
  bos_uri: string,
  public_url: string,
  key: string,
  drama_index: number,
  episode_index: number,
  setProgress: React.Dispatch<React.SetStateAction<Record<string, number>>>
): Promise<UploadedFileResult> {
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
  return {
    filename: file.name,
    oss_uri: bos_uri,
    public_url,
    key,
    drama_index,
    episode_index,
  };
}

type FormParams = {
  projectType: "ShortSeries" | "Ecommerce";
  sourceLang: string;
  targetLangs: string[];
  translationTypes: string[]; // subtitle / speech
  voiceMode: string; // VOICE_CLONE / AI_DUB
  recognitionType: string; // OCR / ASR
  textTypes: string[]; // dialog / title / other
  targetSubtitleCompose: boolean;
  desubtitleEnabled: boolean;
  desubtitleModel: string; // v4 / v3
  desubtitleType: string; // dialog / global
  fontFamily: string;
  fontSize: number;
  fontAlignment: string;
  fontBold: boolean;
  fontColor: string;
  outlineThickness: number;
  outlineColor: string;
  fontPadding: number;
};

const DEFAULT_FORM_PARAMS: FormParams = {
  projectType: "ShortSeries",
  sourceLang: "zh-CN",
  targetLangs: ["en-US"],
  translationTypes: ["subtitle"],
  voiceMode: "VOICE_CLONE",
  recognitionType: "OCR",
  textTypes: ["dialog"],
  targetSubtitleCompose: true,
  desubtitleEnabled: true,
  desubtitleModel: "v4",
  desubtitleType: "dialog",
  fontFamily: "Hei",
  fontSize: 48,
  fontAlignment: "center",
  fontBold: false,
  fontColor: "#FFFFFFFF",
  outlineThickness: 2,
  outlineColor: "#000000FF",
  fontPadding: 8,
};

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

export function BaiduVodPage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [dramas, setDramas] = useState<Drama[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [runtimeLimits, setRuntimeLimits] = useState<BaiduVodRuntimeLimits | null>(null);

  const [p, setP] = useState<FormParams>(DEFAULT_FORM_PARAMS);
  const saveTimerRef = useRef<number | null>(null);

  // 加载/保存表单参数
  useEffect(() => {
    if (!verified) return;
    (async () => {
      try {
        const data = await getBaiduVodSettings();
        if (data && typeof data === "object") {
          const saved = { ...data };
          delete saved.qps;
          setP((prev) => ({ ...prev, ...(saved as Partial<FormParams>) }));
        }
      } catch {
        // 静默
      }
    })();
    getBaiduVodRuntimeLimits().then(setRuntimeLimits).catch(() => {
      setRuntimeLimits(null);
    });
  }, [verified]);

  useEffect(() => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveBaiduVodSettings(p as unknown as Record<string, unknown>).catch(() => {});
    }, 800);
    return () => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    };
  }, [p]);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  const canSubmit = title.trim() && dramas.length > 0 && dramas.some((d) => d.files.length > 0)
    && p.targetLangs.length > 0 && p.translationTypes.length > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
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
        if (f.file.size >= MULTIPART_THRESHOLD) multipartIndices.push(i);
        else smallIndices.push(i);
      });

      const results: UploadedFileResult[] = new Array(allFiles.length);

      if (smallIndices.length > 0) {
        const smallResp = await requestBaiduVodUploadUrls({
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
              f.file, entry.presigned_url, entry.bos_uri, entry.public_url, entry.key,
              f.drama_index, f.episode_index, setProgress
            ).then((r) => { results[i] = r; });
          })
        );
      }

      if (multipartIndices.length > 0) {
        const multipartResults = await Promise.all(
          multipartIndices.map((i) => {
            const f = allFiles[i];
            return uploadOneFileMultipart(f.file, job_id, i, f.drama_index, f.episode_index, setProgress);
          })
        );
        multipartIndices.forEach((i, idx) => { results[i] = multipartResults[idx]; });
      }

      const items = results.map((r) => ({
        filename: r.filename,
        oss_uri: r.oss_uri,
        public_url: r.public_url,
        key: r.key,
        drama_index: r.drama_index,
        episode_index: r.episode_index,
      }));

      const fontConfig: BaiduVodFontConfig = {
        family: p.fontFamily,
        alignment: p.fontAlignment,
        size: p.fontSize,
        bold: p.fontBold,
        color: p.fontColor,
        outline_thickness: p.outlineThickness,
        outline_color: p.outlineColor,
        padding: p.fontPadding,
      };

      const job = await createBaiduVodJob({
        job_id,
        title: title.trim(),
        project_type: p.projectType,
        source_language: p.sourceLang,
        target_langs: p.targetLangs,
        translation_type_list: p.translationTypes,
        voice_mode: p.translationTypes.includes("speech") ? p.voiceMode : null,
        recognition_type: p.recognitionType,
        text_type_list: p.textTypes,
        target_subtitle_compose: p.targetSubtitleCompose,
        desubtitle_enabled: p.desubtitleEnabled,
        desubtitle_model: p.desubtitleModel,
        desubtitle_type: p.desubtitleType,
        ocr_area_list: null,
        font_config: fontConfig,
        items,
        original_filenames: allFiles.map((f) => f.filename),
      });
      toast.success("任务已提交");
      navigate(`/baidu-vod/${job.id}`);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "提交失败";
      toast.error(typeof detail === "string" ? detail : JSON.stringify(detail));
    } finally {
      setSubmitting(false);
    }
  }

  const totalFiles = dramas.reduce((sum, d) => sum + d.files.length, 0);

  function toggleArr(arr: string[], v: string): string[] {
    return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4">
      <div>
        <h1 className="text-2xl font-bold">百度云 VOD 视频翻译</h1>
        <p className="text-sm text-muted-foreground">
          字幕擦除 + 字幕翻译 + 语音翻译(声音复刻/AI 配音)
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>上传视频</CardTitle>
          <CardDescription>拖拽一部短剧的所有视频(可多文件夹),直传百度 BOS</CardDescription>
        </CardHeader>
        <CardContent>
          <MultiFolderDropzone dramas={dramas} onChange={setDramas} />
          {totalFiles > 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">
              共 {dramas.length} 部剧 · {totalFiles} 集
            </p>
          ) : null}
          {totalFiles > 0 && submitting ? (
            <div className="mt-4 space-y-2">
              {dramas.flatMap((d, di) =>
                d.files.map((f, fi) => {
                  const key = `${di}-${fi}`;
                  const pct = progress[key] || 0;
                  return (
                    <div key={key} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="truncate">{f.filename}</span>
                        <span>{pct}%</span>
                      </div>
                      <Progress value={pct} />
                    </div>
                  );
                })
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>任务参数</CardTitle>
          <CardDescription>百度 VOD 翻译配置(所有 API 参数暴露)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>标题</Label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="短剧名称" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>项目类型</Label>
              <Select value={p.projectType} onValueChange={(v) => setP({ ...p, projectType: v as "ShortSeries" | "Ecommerce" })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="ShortSeries">短剧 ShortSeries</SelectItem>
                  <SelectItem value="Ecommerce">电商 Ecommerce</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>源语言</Label>
              <Select value={p.sourceLang} onValueChange={(v) => setP({ ...p, sourceLang: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SOURCE_LANGS.map((l) => <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>运行限制</Label>
              <div className="flex min-h-10 items-center rounded-md border bg-muted/40 px-3 text-sm">
                {runtimeLimits
                  ? `全局 ${runtimeLimits.global_qps} QPS · ${runtimeLimits.max_concurrent_jobs} 个 Job · ${runtimeLimits.max_concurrent_episodes} 集`
                  : "正在读取服务端限制…"}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>目标语言(可多选)</Label>
            <div className="flex flex-wrap gap-3 rounded-md border p-3">
              {TARGET_LANGS.map((l) => {
                const checked = p.targetLangs.includes(l.value);
                return (
                  <label key={l.value} className="flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={checked}
                      onChange={(e) => {
                        if (e.target.checked) setP({ ...p, targetLangs: [...p.targetLangs, l.value] });
                        else setP({ ...p, targetLangs: p.targetLangs.length > 1 ? p.targetLangs.filter((x) => x !== l.value) : p.targetLangs });
                      }} className="h-4 w-4" />
                    <span className="text-sm">{l.label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <Separator />

          <div className="flex flex-col gap-1.5">
            <Label>翻译类型(可多选)</Label>
            <div className="flex flex-wrap gap-3 rounded-md border p-3">
              {[
                { value: "subtitle", label: "字幕翻译 subtitle" },
                { value: "speech", label: "语音翻译 speech(配音)" },
              ].map((l) => {
                const checked = p.translationTypes.includes(l.value);
                return (
                  <label key={l.value} className="flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={checked}
                      onChange={(e) => setP({ ...p, translationTypes: toggleArr(p.translationTypes, l.value) })}
                      className="h-4 w-4" />
                    <span className="text-sm">{l.label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {p.translationTypes.includes("speech") ? (
            <div className="flex flex-col gap-1.5">
              <Label>配音模式</Label>
              <Select value={p.voiceMode} onValueChange={(v) => setP({ ...p, voiceMode: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="VOICE_CLONE">声音复刻 VOICE_CLONE(多角色)</SelectItem>
                  <SelectItem value="AI_DUB">AI 音色 AI_DUB(单音色)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          ) : null}

          <Separator />

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>字幕识别方式</Label>
              <Select value={p.recognitionType} onValueChange={(v) => setP({ ...p, recognitionType: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="OCR">OCR 画面文字识别</SelectItem>
                  <SelectItem value="ASR">ASR 语音识别</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>文本类型(可多选)</Label>
              <div className="flex flex-wrap gap-3">
                {[
                  { value: "dialog", label: "对白" },
                  { value: "title", label: "标题" },
                  { value: "other", label: "其他" },
                ].map((l) => {
                  const checked = p.textTypes.includes(l.value);
                  return (
                    <label key={l.value} className="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" checked={checked}
                        onChange={(e) => setP({ ...p, textTypes: toggleArr(p.textTypes, l.value) })}
                        className="h-4 w-4" />
                      <span className="text-sm">{l.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={p.desubtitleEnabled}
                onChange={(e) => setP({ ...p, desubtitleEnabled: e.target.checked })} className="h-4 w-4" />
              <span className="text-sm">擦除原字幕(desubtitle)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={p.targetSubtitleCompose}
                onChange={(e) => setP({ ...p, targetSubtitleCompose: e.target.checked })} className="h-4 w-4" />
              <span className="text-sm">烧录译文字幕到视频</span>
            </label>
          </div>

          {p.desubtitleEnabled ? (
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <Label>擦除模型</Label>
                <Select value={p.desubtitleModel} onValueChange={(v) => setP({ ...p, desubtitleModel: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="v4">v4 最新</SelectItem>
                    <SelectItem value="v3">v3 旧版</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>擦除类型</Label>
                <Select value={p.desubtitleType} onValueChange={(v) => setP({ ...p, desubtitleType: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="dialog">dialog 对白字幕</SelectItem>
                    <SelectItem value="global">global 全局字幕</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : null}

          <Separator />

          <div>
            <Label className="mb-2 block">字幕样式(fontConfig,烧录时生效)</Label>
            <div className="grid grid-cols-3 gap-3">
              <div className="flex flex-col gap-1">
                <Label className="text-xs">字体</Label>
                <Select value={p.fontFamily} onValueChange={(v) => setP({ ...p, fontFamily: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {["Hei", "Song", "Kai", "Yuan"].map((f) => <SelectItem key={f} value={f}>{f}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">字号</Label>
                <Input type="number" value={p.fontSize} onChange={(e) => setP({ ...p, fontSize: Number(e.target.value) })} />
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">对齐</Label>
                <Select value={p.fontAlignment} onValueChange={(v) => setP({ ...p, fontAlignment: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="center">居中</SelectItem>
                    <SelectItem value="left">左对齐</SelectItem>
                    <SelectItem value="right">右对齐</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">字体颜色</Label>
                <Input type="color" value={p.fontColor.slice(0, 7)}
                  onChange={(e) => setP({ ...p, fontColor: e.target.value + "FF" })} />
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">描边颜色</Label>
                <Input type="color" value={p.outlineColor.slice(0, 7)}
                  onChange={(e) => setP({ ...p, outlineColor: e.target.value + "FF" })} />
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">描边粗细</Label>
                <Input type="number" value={p.outlineThickness} onChange={(e) => setP({ ...p, outlineThickness: Number(e.target.value) })} />
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs">内边距</Label>
                <Input type="number" value={p.fontPadding} onChange={(e) => setP({ ...p, fontPadding: Number(e.target.value) })} />
              </div>
              <label className="flex items-center gap-2 cursor-pointer pt-5">
                <input type="checkbox" checked={p.fontBold}
                  onChange={(e) => setP({ ...p, fontBold: e.target.checked })} className="h-4 w-4" />
                <span className="text-sm">粗体</span>
              </label>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>提交任务</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <SummaryRow label="标题" value={title || "(未填)"} />
          <SummaryRow label="视频" value={`${dramas.length} 部剧 / ${totalFiles} 集`} />
          <SummaryRow label="源语言" value={SOURCE_LANGS.find((l) => l.value === p.sourceLang)?.label || p.sourceLang} />
          <SummaryRow label="目标语言" value={p.targetLangs.map((v) => TARGET_LANGS.find((l) => l.value === v)?.label || v).join("、")} />
          <SummaryRow label="翻译类型" value={p.translationTypes.join("、")} />
          {p.translationTypes.includes("speech") ? (
            <SummaryRow label="配音模式" value={p.voiceMode} />
          ) : null}
          <SummaryRow label="识别方式" value={p.recognitionType} />
          <SummaryRow label="擦除字幕" value={p.desubtitleEnabled ? `${p.desubtitleModel} / ${p.desubtitleType}` : "否"} />
          <SummaryRow label="烧录译文字幕" value={p.targetSubtitleCompose ? "是" : "否"} />
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit || submitting} className="w-full">
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {submitting ? "上传中..." : "提交任务"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
