import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  createStarlingDramaJob,
  getStarlingDramaSettings,
  requestStarlingDramaUploadUrls,
  requestStarlingDramaMultipartUrls,
  completeStarlingDramaMultipart,
  abortStarlingDramaMultipart,
  saveStarlingDramaSettings,
} from "@/api/client";
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

const MULTIPART_THRESHOLD = 10 * 1024 * 1024;
const PART_CONCURRENCY = 5;
const PART_MAX_RETRY = 3;

const SOURCE_LANGS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

const TARGET_LANGS = [
  { value: "en", label: "英文" },
  { value: "es", label: "西班牙语" },
  { value: "pt", label: "葡萄牙语" },
  { value: "th", label: "泰语" },
  { value: "id", label: "印尼语" },
  { value: "vi", label: "越南语" },
  { value: "ms", label: "马来语" },
  { value: "ja", label: "日文" },
  { value: "ko", label: "韩文" },
];

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
  const init = await requestStarlingDramaMultipartUrls({
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
    const done = await completeStarlingDramaMultipart({
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
    await abortStarlingDramaMultipart(init.key, init.upload_id).catch(() => {});
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

type FormParams = {
  dramaName: string;
  sourceLang: string;
  targetLangs: string[];
  subtitleRemovalMode: "NONE" | "BASIC" | "ADVANCED";
  burnTargetSubtitle: boolean;
  dubbingEnabled: boolean;
  dubbingSpeakerMode: "AUTO_MULTI_SPEAKER" | "REUSE_DRAMA_SPEAKERS";
  dubbingEmotionMode: "STANDARD" | "HIGH_EMOTION";
  dubbingPreserveBgAudio: boolean;
  workflowMode: "FULLY_AUTOMATIC" | "MANUAL_REVIEW";
  maxRetryCount: number;
};

const DEFAULT_FORM_PARAMS: FormParams = {
  dramaName: "",
  sourceLang: "zh",
  targetLangs: ["en"],
  subtitleRemovalMode: "BASIC",
  burnTargetSubtitle: true,
  dubbingEnabled: true,
  dubbingSpeakerMode: "AUTO_MULTI_SPEAKER",
  dubbingEmotionMode: "STANDARD",
  dubbingPreserveBgAudio: true,
  workflowMode: "FULLY_AUTOMATIC",
  maxRetryCount: 2,
};

export function StarlingDramaPage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [dramas, setDramas] = useState<Drama[]>([]);

  const [dramaName, setDramaName] = useState<string>(DEFAULT_FORM_PARAMS.dramaName);
  const [sourceLang, setSourceLang] = useState<string>(DEFAULT_FORM_PARAMS.sourceLang);
  const [targetLangs, setTargetLangs] = useState<string[]>(DEFAULT_FORM_PARAMS.targetLangs);
  const [subtitleRemovalMode, setSubtitleRemovalMode] = useState<"NONE" | "BASIC" | "ADVANCED">(
    DEFAULT_FORM_PARAMS.subtitleRemovalMode
  );
  const [burnTargetSubtitle, setBurnTargetSubtitle] = useState<boolean>(
    DEFAULT_FORM_PARAMS.burnTargetSubtitle
  );
  const [dubbingEnabled, setDubbingEnabled] = useState<boolean>(DEFAULT_FORM_PARAMS.dubbingEnabled);
  const [dubbingSpeakerMode, setDubbingSpeakerMode] = useState<
    "AUTO_MULTI_SPEAKER" | "REUSE_DRAMA_SPEAKERS"
  >(DEFAULT_FORM_PARAMS.dubbingSpeakerMode);
  const [dubbingEmotionMode, setDubbingEmotionMode] = useState<"STANDARD" | "HIGH_EMOTION">(
    DEFAULT_FORM_PARAMS.dubbingEmotionMode
  );
  const [dubbingPreserveBgAudio, setDubbingPreserveBgAudio] = useState<boolean>(
    DEFAULT_FORM_PARAMS.dubbingPreserveBgAudio
  );
  const [workflowMode, setWorkflowMode] = useState<"FULLY_AUTOMATIC" | "MANUAL_REVIEW">(
    DEFAULT_FORM_PARAMS.workflowMode
  );
  const [maxRetryCount, setMaxRetryCount] = useState<number>(DEFAULT_FORM_PARAMS.maxRetryCount);

  const [progress, setProgress] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);

  const settingsLoadedRef = useRef(false);
  const saveTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!verified) return;
    getStarlingDramaSettings()
      .then((data) => {
        if (!data || Object.keys(data).length === 0) return;
        if (data.dramaName) setDramaName(data.dramaName as string);
        if (data.sourceLang) setSourceLang(data.sourceLang as string);
        if (Array.isArray(data.targetLangs)) setTargetLangs(data.targetLangs as string[]);
        if (data.subtitleRemovalMode)
          setSubtitleRemovalMode(data.subtitleRemovalMode as "NONE" | "BASIC" | "ADVANCED");
        if (typeof data.burnTargetSubtitle === "boolean")
          setBurnTargetSubtitle(data.burnTargetSubtitle as boolean);
        if (typeof data.dubbingEnabled === "boolean")
          setDubbingEnabled(data.dubbingEnabled as boolean);
        if (data.dubbingSpeakerMode)
          setDubbingSpeakerMode(
            data.dubbingSpeakerMode as "AUTO_MULTI_SPEAKER" | "REUSE_DRAMA_SPEAKERS"
          );
        if (data.dubbingEmotionMode)
          setDubbingEmotionMode(data.dubbingEmotionMode as "STANDARD" | "HIGH_EMOTION");
        if (typeof data.dubbingPreserveBgAudio === "boolean")
          setDubbingPreserveBgAudio(data.dubbingPreserveBgAudio as boolean);
        if (data.workflowMode)
          setWorkflowMode(data.workflowMode as "FULLY_AUTOMATIC" | "MANUAL_REVIEW");
        if (typeof data.maxRetryCount === "number") setMaxRetryCount(data.maxRetryCount as number);
      })
      .finally(() => {
        settingsLoadedRef.current = true;
      });
  }, [verified]);

  // 防抖保存
  useEffect(() => {
    if (!settingsLoadedRef.current) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(() => {
      saveStarlingDramaSettings({
        dramaName,
        sourceLang,
        targetLangs,
        subtitleRemovalMode,
        burnTargetSubtitle,
        dubbingEnabled,
        dubbingSpeakerMode,
        dubbingEmotionMode,
        dubbingPreserveBgAudio,
        workflowMode,
        maxRetryCount,
      }).catch(() => {});
    }, 800);
  }, [
    dramaName,
    sourceLang,
    targetLangs,
    subtitleRemovalMode,
    burnTargetSubtitle,
    dubbingEnabled,
    dubbingSpeakerMode,
    dubbingEmotionMode,
    dubbingPreserveBgAudio,
    workflowMode,
    maxRetryCount,
  ]);

  const allFiles = dramas.flatMap((d, di) =>
    d.files.map((f, fi) => ({ ...f, drama_index: di, episode_index: fi }))
  );
  const canSubmit =
    title.trim().length > 0 &&
    dramaName.trim().length > 0 &&
    targetLangs.length > 0 &&
    allFiles.length > 0 &&
    !submitting;

  function toggleTargetLang(lang: string) {
    setTargetLangs((prev) =>
      prev.includes(lang) ? prev.filter((l) => l !== lang) : [...prev, lang]
    );
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setProgress({});
    try {
      const job_id = uuid();

      const smallIndices: number[] = [];
      const multipartIndices: number[] = [];
      allFiles.forEach((f, i) => {
        if (f.file.size >= MULTIPART_THRESHOLD) multipartIndices.push(i);
        else smallIndices.push(i);
      });

      const results: UploadedFileResult[] = new Array(allFiles.length);

      if (smallIndices.length > 0) {
        const smallResp = await requestStarlingDramaUploadUrls({
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
        drama_index: r.drama_index,
        episode_index: r.episode_index,
      }));

      const job = await createStarlingDramaJob({
        job_id,
        title: title.trim(),
        drama_name: dramaName.trim(),
        source_lang: sourceLang,
        target_langs: targetLangs,
        subtitle_removal_mode: subtitleRemovalMode,
        burn_target_subtitle: burnTargetSubtitle,
        subtitle_style_template: "white-black-outline-v1",
        dubbing_enabled: dubbingEnabled,
        dubbing_speaker_mode: dubbingSpeakerMode,
        dubbing_emotion_mode: dubbingEmotionMode,
        dubbing_preserve_bg_audio: dubbingPreserveBgAudio,
        workflow_mode: workflowMode,
        max_retry_count: maxRetryCount,
        items,
        original_filenames: allFiles.map((f) => f.filename),
      });

      toast.success("任务已提交，Starling 正在处理");
      navigate(`/starling-drama/${job.id}`);
    } catch (error: any) {
      console.error(error);
      const detail = error?.response?.data?.detail || "上传或提交失败";
      toast.error(detail);
    } finally {
      setSubmitting(false);
    }
  }

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
      <Card>
        <CardHeader>
          <CardTitle>Starling 短剧全链路翻配</CardTitle>
          <CardDescription>
            一次表单提交：字幕提取 + 擦除 + 翻译 + 多角色配音 + 压制，由火山 Starling 全自动完成。
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="title">任务标题</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：龙战玄黄 第30集 英文翻配"
              disabled={submitting}
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="drama-name">短剧名称</Label>
              <Input
                id="drama-name"
                value={dramaName}
                onChange={(e) => setDramaName(e.target.value)}
                placeholder="例如：龙战玄黄"
                disabled={submitting}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label>源语言</Label>
              <Select value={sourceLang} onValueChange={setSourceLang} disabled={submitting}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SOURCE_LANGS.map((l) => (
                    <SelectItem key={l.value} value={l.value}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <Label>目标语言（可多选）</Label>
            <div className="flex flex-wrap gap-2">
              {TARGET_LANGS.map((l) => (
                <Button
                  key={l.value}
                  type="button"
                  size="sm"
                  variant={targetLangs.includes(l.value) ? "default" : "outline"}
                  onClick={() => toggleTargetLang(l.value)}
                  disabled={submitting}
                >
                  {l.label}
                </Button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>视频上传</CardTitle>
          <CardDescription>支持多剧集文件夹批量上传。视频将传到阿里云 OSS 公开桶，由 Starling 异步拉取。</CardDescription>
        </CardHeader>
        <CardContent>
          <MultiFolderDropzone dramas={dramas} onChange={setDramas} disabled={submitting} />
          {Object.keys(progress).length > 0 ? (
            <div className="mt-4 flex flex-col gap-2">
              {Object.entries(progress).map(([key, pct]) => (
                <div key={key} className="flex flex-col gap-1">
                  <div className="text-xs text-muted-foreground">集 {key}</div>
                  <Progress value={pct} />
                </div>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>字幕处理</CardTitle>
          <CardDescription>字幕提取由 Starling AI 自动完成，无需配置。</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label>字幕擦除等级</Label>
            <Select
              value={subtitleRemovalMode}
              onValueChange={(v) =>
                setSubtitleRemovalMode(v as "NONE" | "BASIC" | "ADVANCED")
              }
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="NONE">不擦除</SelectItem>
                <SelectItem value="BASIC">基础擦除</SelectItem>
                <SelectItem value="ADVANCED">高级擦除</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>烧录目标字幕</Label>
            <Select
              value={burnTargetSubtitle ? "true" : "false"}
              onValueChange={(v) => setBurnTargetSubtitle(v === "true")}
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">烧录到视频</SelectItem>
                <SelectItem value="false">不烧录</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>配音配置</CardTitle>
          <CardDescription>多角色配音由 Starling 自动识别角色完成。</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label>启用配音</Label>
            <Select
              value={dubbingEnabled ? "true" : "false"}
              onValueChange={(v) => setDubbingEnabled(v === "true")}
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">开启配音</SelectItem>
                <SelectItem value="false">关闭配音</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>角色策略</Label>
            <Select
              value={dubbingSpeakerMode}
              onValueChange={(v) =>
                setDubbingSpeakerMode(v as "AUTO_MULTI_SPEAKER" | "REUSE_DRAMA_SPEAKERS")
              }
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="AUTO_MULTI_SPEAKER">自动识别角色</SelectItem>
                <SelectItem value="REUSE_DRAMA_SPEAKERS">复用本剧角色</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>配音模式</Label>
            <Select
              value={dubbingEmotionMode}
              onValueChange={(v) =>
                setDubbingEmotionMode(v as "STANDARD" | "HIGH_EMOTION")
              }
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="STANDARD">标准配音</SelectItem>
                <SelectItem value="HIGH_EMOTION">高情感配音</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label>背景音</Label>
            <Select
              value={dubbingPreserveBgAudio ? "true" : "false"}
              onValueChange={(v) => setDubbingPreserveBgAudio(v === "true")}
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">保留音乐和环境音</SelectItem>
                <SelectItem value="false">不保留</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>工作流配置</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label>处理模式</Label>
            <Select
              value={workflowMode}
              onValueChange={(v) =>
                setWorkflowMode(v as "FULLY_AUTOMATIC" | "MANUAL_REVIEW")
              }
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="FULLY_AUTOMATIC">全自动成片</SelectItem>
                <SelectItem value="MANUAL_REVIEW">AI 完成后人工审核</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="max-retry">失败自动重试次数</Label>
            <Input
              id="max-retry"
              type="number"
              min={0}
              max={10}
              value={maxRetryCount}
              onChange={(e) => setMaxRetryCount(Number(e.target.value) || 0)}
              disabled={submitting}
            />
          </div>
        </CardContent>
      </Card>

      <Separator />

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => navigate("/starling-drama/history")} disabled={submitting}>
          查看历史
        </Button>
        <Button type="submit" disabled={!canSubmit}>
          {submitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 提交中…
            </>
          ) : (
            "提交任务"
          )}
        </Button>
      </div>
    </form>
  );
}
