import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  abortImsSpeechMultipart,
  completeImsSpeechMultipart,
  createImsSpeechJob,
  getImsSpeechSettings,
  requestImsSpeechMultipartUrls,
  requestImsSpeechUploadUrls,
  saveImsSpeechSettings,
} from "@/api/client";
import { MultiFolderDropzone, type Drama } from "@/components/MultiFolderDropzone";
import { PassphraseGate } from "@/components/PassphraseGate";
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
import { getPassphrase } from "@/lib/passphrase";
import { uuid } from "@/lib/uuid";

const MULTIPART_THRESHOLD = 10 * 1024 * 1024;
const PART_CONCURRENCY = 5;
const PART_MAX_RETRY = 3;

const SOURCE_LANGUAGES = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "fr", label: "法语（仅 ASR）" },
  { value: "tr", label: "土耳其语（仅 ASR）" },
];

const TARGET_LANGUAGES = [
  ["zh", "中文"],
  ["zh-tw", "繁体中文"],
  ["en", "英文"],
  ["ja", "日语"],
  ["ko", "韩语"],
  ["yue", "粤语"],
  ["de", "德语"],
  ["fr", "法语"],
  ["es", "西班牙语"],
  ["ar", "阿拉伯语"],
  ["tr", "土耳其语"],
  ["ru", "俄语"],
  ["pt", "葡萄牙语"],
  ["vi", "越南语"],
  ["ms", "马来语"],
  ["th", "泰语"],
  ["id", "印尼语"],
  ["sichuan", "四川话"],
  ["tianjin", "天津话"],
] as const;

type TextSource = "ASR" | "OCR" | "OCR_ASR";
type DetextMode = "none" | "auto" | "custom";
const FORM_SETTINGS_VERSION = 2;

type FormSettings = {
  settingsVersion: number;
  sourceLanguage: string;
  targetLanguages: string[];
  textSource: TextSource;
  detextMode: DetextMode;
  detextBottomPct: number;
  ocrBottomPct: number;
  bilingualSubtitle: boolean;
  subtitleEnabled: boolean;
  skipSong: boolean;
  fontColor: string;
  fontColorOpacity: number;
  subtitleY: number;
};

const DEFAULT_SETTINGS: FormSettings = {
  settingsVersion: FORM_SETTINGS_VERSION,
  sourceLanguage: "zh",
  targetLanguages: ["en"],
  textSource: "ASR",
  detextMode: "auto",
  detextBottomPct: 30,
  ocrBottomPct: 35,
  bilingualSubtitle: false,
  subtitleEnabled: true,
  skipSong: false,
  fontColor: "#FFFFFF",
  fontColorOpacity: 1,
  subtitleY: 0.76,
};

function migrateFormSettings(data: Record<string, unknown>): FormSettings {
  const migrated = { ...data };
  delete migrated.fontSize;
  delete migrated.subtitleX;
  delete migrated.textWidth;

  const alreadyAdaptive = migrated.settingsVersion === FORM_SETTINGS_VERSION;
  return {
    ...DEFAULT_SETTINGS,
    ...(migrated as Partial<FormSettings>),
    settingsVersion: FORM_SETTINGS_VERSION,
    subtitleY:
      alreadyAdaptive && typeof migrated.subtitleY === "number"
        ? migrated.subtitleY
        : DEFAULT_SETTINGS.subtitleY,
  };
}

type UploadedItem = {
  filename: string;
  oss_uri: string;
  public_url: string;
  key: string;
  drama_index: number;
  episode_index: number;
};

async function uploadSimple(
  file: File,
  presignedUrl: string,
  progressKey: string,
  setProgress: React.Dispatch<React.SetStateAction<Record<string, number>>>
) {
  await axios.put(presignedUrl, file, {
    headers: { "Content-Type": file.type || "video/mp4" },
    onUploadProgress: (event) => {
      if (!event.total) return;
      setProgress((previous) => ({
        ...previous,
        [progressKey]: Math.round((event.loaded / event.total!) * 100),
      }));
    },
  });
}

async function uploadMultipart(
  file: File,
  jobId: string,
  uploadIndex: number,
  dramaIndex: number,
  episodeIndex: number,
  setProgress: React.Dispatch<React.SetStateAction<Record<string, number>>>
): Promise<UploadedItem> {
  const init = await requestImsSpeechMultipartUrls({
    filename: file.name,
    content_type: file.type || "video/mp4",
    file_size: file.size,
    job_id: jobId,
    index: uploadIndex,
  });
  const uploadedBytes = new Array(init.parts.length).fill(0);
  const completedParts: { part_number: number; etag: string }[] = [];
  let cursor = 0;

  const updateProgress = () => {
    const loaded = uploadedBytes.reduce((sum, value) => sum + value, 0);
    setProgress((previous) => ({
      ...previous,
      [`${dramaIndex}-${episodeIndex}`]: Math.round((loaded / file.size) * 100),
    }));
  };
  const worker = async () => {
    while (cursor < init.parts.length) {
      const partIndex = cursor++;
      const part = init.parts[partIndex];
      const blob = file.slice(part.offset, part.offset + part.size);
      let etag = "";
      for (let attempt = 0; attempt < PART_MAX_RETRY; attempt += 1) {
        try {
          const response = await axios.put(part.presigned_url, blob, {
            headers: { "Content-Type": file.type || "video/mp4" },
            onUploadProgress: (event) => {
              uploadedBytes[partIndex] = Math.min(part.size, event.loaded || 0);
              updateProgress();
            },
          });
          etag = String(response.headers.etag || "");
          uploadedBytes[partIndex] = part.size;
          updateProgress();
          break;
        } catch (error) {
          uploadedBytes[partIndex] = 0;
          if (attempt === PART_MAX_RETRY - 1) throw error;
          await new Promise((resolve) => window.setTimeout(resolve, 1000 * 2 ** attempt));
        }
      }
      completedParts.push({ part_number: part.part_number, etag });
    }
  };

  try {
    await Promise.all(
      Array.from({ length: Math.min(PART_CONCURRENCY, init.parts.length) }, worker)
    );
    const completed = await completeImsSpeechMultipart({
      job_id: jobId,
      key: init.key,
      upload_id: init.upload_id,
      parts: completedParts,
    });
    return {
      filename: file.name,
      oss_uri: completed.oss_uri,
      public_url: completed.public_url,
      key: init.key,
      drama_index: dramaIndex,
      episode_index: episodeIndex,
    };
  } catch (error) {
    await abortImsSpeechMultipart(init.key, init.upload_id).catch(() => undefined);
    throw error;
  }
}

export function ImsSpeechPage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [dramas, setDramas] = useState<Drama[]>([]);
  const [settings, setSettings] = useState<FormSettings>(DEFAULT_SETTINGS);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const settingsLoaded = useRef(false);
  const saveTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!verified) return;
    getImsSpeechSettings()
      .then((data) => {
        if (data && Object.keys(data).length > 0) {
          setSettings(migrateFormSettings(data));
        }
      })
      .catch(() => undefined)
      .finally(() => {
        settingsLoaded.current = true;
      });
  }, [verified]);

  useEffect(() => {
    if (!settingsLoaded.current) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveImsSpeechSettings(settings).catch(() => undefined);
    }, 800);
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, [settings]);

  useEffect(() => {
    if (
      settings.textSource !== "ASR" &&
      !["zh", "en"].includes(settings.sourceLanguage)
    ) {
      setSettings((current) => ({ ...current, sourceLanguage: "zh" }));
    }
  }, [settings.textSource, settings.sourceLanguage]);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  const allFiles = dramas.flatMap((drama, dramaIndex) =>
    drama.files.map((entry, episodeIndex) => ({
      ...entry,
      dramaIndex,
      episodeIndex,
    }))
  );
  const canSubmit =
    title.trim().length > 0 &&
    allFiles.length > 0 &&
    settings.targetLanguages.length > 0 &&
    !submitting;

  function patchSettings(patch: Partial<FormSettings>) {
    setSettings((current) => ({ ...current, ...patch }));
  }

  function toggleTarget(language: string) {
    const exists = settings.targetLanguages.includes(language);
    patchSettings({
      targetLanguages: exists
        ? settings.targetLanguages.filter((value) => value !== language)
        : [...settings.targetLanguages, language],
    });
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setProgress({});
    try {
      const jobId = uuid();
      const small = allFiles
        .map((entry, index) => ({ entry, index }))
        .filter(({ entry }) => entry.file.size < MULTIPART_THRESHOLD);
      const large = allFiles
        .map((entry, index) => ({ entry, index }))
        .filter(({ entry }) => entry.file.size >= MULTIPART_THRESHOLD);
      const uploaded: UploadedItem[] = new Array(allFiles.length);

      if (small.length > 0) {
        const uploadUrls = await requestImsSpeechUploadUrls({
          job_id: jobId,
          files: small.map(({ entry }) => ({
            filename: entry.filename,
            content_type: entry.file.type || "video/mp4",
          })),
        });
        await Promise.all(
          uploadUrls.entries.map(async (upload, position) => {
            const { entry, index } = small[position];
            await uploadSimple(
              entry.file,
              upload.presigned_url,
              `${entry.dramaIndex}-${entry.episodeIndex}`,
              setProgress
            );
            uploaded[index] = {
              filename: entry.filename,
              oss_uri: upload.oss_uri,
              public_url: upload.public_url,
              key: upload.key,
              drama_index: entry.dramaIndex,
              episode_index: entry.episodeIndex,
            };
          })
        );
      }

      const largeResults = await Promise.all(
        large.map(({ entry }, position) =>
          uploadMultipart(
            entry.file,
            jobId,
            small.length + position,
            entry.dramaIndex,
            entry.episodeIndex,
            setProgress
          )
        )
      );
      large.forEach(({ index }, position) => {
        uploaded[index] = largeResults[position];
      });

      const detextHeight = settings.detextBottomPct / 100;
      const ocrHeight = settings.ocrBottomPct / 100;
      const job = await createImsSpeechJob({
        job_id: jobId,
        title: title.trim(),
        source_language: settings.sourceLanguage,
        target_languages: settings.targetLanguages,
        text_source: settings.textSource,
        detext_mode: settings.detextMode,
        detext_areas:
          settings.detextMode === "custom"
            ? [{ x: 0, y: 1 - detextHeight, width: 1, height: detextHeight }]
            : null,
        ocr_area:
          settings.textSource === "ASR"
            ? null
            : { x: 0, y: 1 - ocrHeight, width: 1, height: ocrHeight },
        bilingual_subtitle: settings.bilingualSubtitle,
        subtitle_enabled: settings.subtitleEnabled,
        skip_song: settings.skipSong,
        font_color: settings.fontColor,
        font_color_opacity: settings.fontColorOpacity,
        subtitle_y: settings.subtitleY,
        items: uploaded,
        original_filenames: allFiles.map((entry) => entry.filename),
      });
      toast.success("IMS 语音翻译任务已提交");
      navigate(`/ims-speech/${job.id}`);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "上传或提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>阿里云 IMS 语音级视频翻译</CardTitle>
          <CardDescription>
            一个 API 完成原文识别、字幕擦除、语音翻译、配音和成片输出。该模块与现有字幕擦除翻译任务完全独立。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <Label htmlFor="ims-title">批次标题</Label>
              <Input
                id="ims-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：短剧 A 英西语配音"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label>视频文件夹</Label>
              <MultiFolderDropzone
                dramas={dramas}
                onChange={setDramas}
                disabled={submitting}
              />
            </div>

            {submitting ? (
              <div className="space-y-2">
                <Label>OSS 上传进度</Label>
                {allFiles.map((entry) => {
                  const value = progress[`${entry.dramaIndex}-${entry.episodeIndex}`] || 0;
                  return (
                    <div key={`${entry.dramaIndex}-${entry.episodeIndex}`} className="space-y-1">
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span className="truncate">{entry.filename}</span>
                        <span>{value}%</span>
                      </div>
                      <Progress value={value} />
                    </div>
                  );
                })}
              </div>
            ) : null}

            <Separator />

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>原文来源</Label>
                <Select
                  value={settings.textSource}
                  onValueChange={(value: TextSource) => patchSettings({ textSource: value })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ASR">ASR（识别语音）</SelectItem>
                    <SelectItem value="OCR">OCR（识别画面文字）</SelectItem>
                    <SelectItem value="OCR_ASR">OCR + ASR</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>源语言</Label>
                <Select
                  value={settings.sourceLanguage}
                  onValueChange={(value) => patchSettings({ sourceLanguage: value })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {SOURCE_LANGUAGES.map((language) => (
                      <SelectItem
                        key={language.value}
                        value={language.value}
                        disabled={
                          settings.textSource !== "ASR" &&
                          !["zh", "en"].includes(language.value)
                        }
                      >
                        {language.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label>目标语言（可多选）</Label>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {TARGET_LANGUAGES.map(([value, label]) => (
                  <label
                    key={value}
                    className="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={settings.targetLanguages.includes(value)}
                      onChange={() => toggleTarget(value)}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>原字幕擦除</Label>
                <Select
                  value={settings.detextMode}
                  onValueChange={(value: DetextMode) => patchSettings({ detextMode: value })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">不擦除</SelectItem>
                    <SelectItem value="auto">自动识别区域</SelectItem>
                    <SelectItem value="custom">自定义底部区域</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {settings.detextMode === "custom" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="detext-height">擦除底部高度（%）</Label>
                  <Input
                    id="detext-height"
                    type="number"
                    min={5}
                    max={100}
                    value={settings.detextBottomPct}
                    onChange={(event) =>
                      patchSettings({ detextBottomPct: Number(event.target.value) })
                    }
                  />
                </div>
              ) : null}
              {settings.textSource !== "ASR" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="ocr-height">OCR 底部识别高度（%）</Label>
                  <Input
                    id="ocr-height"
                    type="number"
                    min={5}
                    max={100}
                    value={settings.ocrBottomPct}
                    onChange={(event) =>
                      patchSettings({ ocrBottomPct: Number(event.target.value) })
                    }
                  />
                </div>
              ) : null}
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ["bilingualSubtitle", "保留双语字幕"],
                ["subtitleEnabled", "成片显示字幕"],
                ["skipSong", "跳过歌曲翻译"],
              ].map(([key, label]) => (
                <label
                  key={key}
                  className="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={Boolean(settings[key as keyof FormSettings])}
                    onChange={(event) =>
                      patchSettings({ [key]: event.target.checked } as Partial<FormSettings>)
                    }
                  />
                  {label}
                </label>
              ))}
            </div>

            <div className="rounded-md border p-4">
              <p className="mb-3 text-sm font-medium">字幕样式</p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="space-y-1.5">
                  <Label>自动字号</Label>
                  <div className="min-h-10 rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                    {settings.bilingualSubtitle
                      ? "双语：画面高度约 3.5%"
                      : "单语：画面高度约 4%"}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="font-color">颜色</Label>
                  <Input
                    id="font-color"
                    type="color"
                    disabled={!settings.subtitleEnabled}
                    value={settings.fontColor}
                    onChange={(event) => patchSettings({ fontColor: event.target.value })}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="font-color-opacity">颜色透明度</Label>
                  <Input
                    id="font-color-opacity"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    disabled={!settings.subtitleEnabled}
                    value={settings.fontColorOpacity}
                    onChange={(event) =>
                      patchSettings({ fontColorOpacity: Number(event.target.value) })
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="subtitleY">垂直位置 Y</Label>
                  <Input
                    id="subtitleY"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    disabled={!settings.subtitleEnabled}
                    value={settings.subtitleY}
                    onChange={(event) =>
                      patchSettings({ subtitleY: Number(event.target.value) })
                    }
                  />
                </div>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                字幕以 1080 × 1920 参考画布按成片分辨率等比缩放；水平居中，文本宽度固定为画面
                90%，超长内容自动换行。
              </p>
            </div>

            <Button type="submit" disabled={!canSubmit}>
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  正在上传并提交
                </>
              ) : (
                `提交 ${allFiles.length} 集语音翻译`
              )}
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">处理边界</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>当前仅支持 ASR、OCR、OCR + ASR，不导入外部 SRT。</p>
            <p>每集只提交一次 IMS 请求，多个目标语言随同一个任务处理。</p>
            <p>任务完成后保留成片、翻译音轨、普通/修订/双语字幕地址。</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">费用提示</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            停止按钮只能终止本地轮询，已提交的阿里云任务可能继续运行并产生费用。
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
