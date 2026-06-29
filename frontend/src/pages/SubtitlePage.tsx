import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  createSubtitleJob,
  getModels,
  requestSubtitleUploadUrls,
} from "@/api/client";
import type { ModelOption, SubtitleUploadEntry } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/sonner";
import { ModelSelector } from "@/components/ModelSelector";
import { MultiVideoDropzone } from "@/components/MultiVideoDropzone";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";

export function SubtitlePage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<Record<number, number>>({});
  const [submitting, setSubmitting] = useState(false);

  const [enableTranslate, setEnableTranslate] = useState(false);
  const [enableBurn, setEnableBurn] = useState(true);
  const [placementMode, setPlacementMode] = useState<"safe_bottom" | "simple_bottom">("safe_bottom");
  const [targetLang, setTargetLang] = useState("English");

  const [models, setModels] = useState<ModelOption[]>([]);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");

  useEffect(() => {
    getModels()
      .then((opts) => {
        setModels(opts);
        const def = opts.find((m) => m.default) ?? opts[0];
        if (def) {
          setProvider(def.provider);
          setModel(def.name);
        }
      })
      .catch(() => {
        // 模型加载失败不阻塞 UI
      });
  }, []);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  const canSubmit =
    Boolean(title.trim()) &&
    files.length > 0 &&
    (!enableTranslate || (provider && model && targetLang.trim())) &&
    !submitting;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setProgress({});
    try {
      const upload = await requestSubtitleUploadUrls({
        files: files.map((f) => ({
          filename: f.name,
          content_type: f.type || "video/mp4",
        })),
      });

      // 并发双传：OSS（VIAPI 用）+ 新加坡 TOS（烧录源）
      // 上行流量免费，两路并发取较慢者
      const uploadOne = (url: string, file: File, index: number, channel: "oss" | "tos") =>
        axios.put(url, file, {
          headers: { "Content-Type": file.type || "video/mp4" },
          onUploadProgress: (event) => {
            if (event.total) {
              // 进度按两路合计：每路各占 50%
              setProgress((prev) => {
                const prevPct = prev[index] ?? 0;
                const thisPct = Math.round((event.loaded / event.total!) * 100);
                // 简单取两路平均（首个完成的 channel 会覆盖）
                return { ...prev, [index]: Math.max(prevPct, thisPct) };
              });
            }
          },
        });

      await Promise.all(
        upload.entries.flatMap((entry: SubtitleUploadEntry, index: number) => [
          uploadOne(entry.oss_presigned_url, files[index], index, "oss"),
          uploadOne(entry.tos_presigned_url, files[index], index, "tos"),
        ])
      );

      const job = await createSubtitleJob({
        job_id: upload.job_id,
        title: title.trim(),
        subtitle_source: "chinese",
        enable_translate: enableTranslate,
        enable_burn: enableBurn,
        placement_mode: placementMode,
        target_lang: enableTranslate ? targetLang.trim() : null,
        model_provider: enableTranslate ? provider : null,
        model_name: enableTranslate ? model : null,
        items: upload.entries.map((e, i) => ({
          filename: files[i].name,
          oss_uri: e.oss_uri,
          oss_public_url: e.oss_public_url,
          oss_key: e.oss_key,
          tos_uri: e.tos_uri,
          tos_public_url: e.tos_public_url,
          tos_key: e.tos_key,
        })),
        original_filenames: files.map((f) => f.name),
      });
      toast.success("任务已提交，正在处理");
      navigate(`/subtitle/${job.id}`);
    } catch (error) {
      console.error(error);
      toast.error("上传或提交失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>视频字幕提取-翻译-合并</CardTitle>
          <CardDescription>
            上传视频到火山 TOS，调用阿里云 VIAPI 识别字幕，可选翻译并烧录到新视频。三个步骤按需勾选。
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
                placeholder="例如：第1集字幕处理"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>视频文件</Label>
              <MultiVideoDropzone files={files} onChange={setFiles} disabled={submitting} />
            </div>

            {submitting && files.length > 0 ? (
              <div className="flex flex-col gap-2">
                <Label>上传进度</Label>
                {files.map((file, index) => (
                  <div key={`${file.name}-${index}`} className="flex flex-col gap-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="truncate">{file.name}</span>
                      <span>{progress[index] ?? 0}%</span>
                    </div>
                    <Progress value={progress[index] ?? 0} className="h-1.5" />
                  </div>
                ))}
              </div>
            ) : null}

            <Separator />

            <div className="flex flex-col gap-1.5">
              <Label>字幕来源</Label>
              <p className="text-xs text-muted-foreground">
                VIAPI 返回逐帧 OCR 结果，后端聚合为 SRT（按 trackId 分条）。
              </p>
            </div>

            <Separator />

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableTranslate}
                onChange={(e) => setEnableTranslate(e.target.checked)}
                className="h-4 w-4"
                disabled={submitting}
              />
              <span className="text-sm font-medium">启用翻译</span>
              <span className="text-xs text-muted-foreground">把 SRT 文本翻译到目标语言，保留时间轴</span>
            </label>

            {enableTranslate ? (
              <div className="flex flex-col gap-4 rounded-md border p-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <ModelSelector
                    models={models}
                    provider={provider}
                    model={model}
                    onChange={(p, m) => {
                      setProvider(p);
                      setModel(m);
                    }}
                  />
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="target-lang">目标语言</Label>
                    <Input
                      id="target-lang"
                      value={targetLang}
                      onChange={(e) => setTargetLang(e.target.value)}
                      placeholder="例如：English"
                    />
                  </div>
                </div>
              </div>
            ) : null}

            <Separator />

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableBurn}
                onChange={(e) => setEnableBurn(e.target.checked)}
                className="h-4 w-4"
                disabled={submitting}
              />
              <span className="text-sm font-medium">启用烧录字幕到视频</span>
              <span className="text-xs text-muted-foreground">用 FFmpeg 把字幕硬嵌到视频，生成新 mp4</span>
            </label>

            {enableBurn ? (
              <div className="flex flex-col gap-1.5 rounded-md border p-4">
                <Label htmlFor="placement-mode">字幕放置策略</Label>
                <Select value={placementMode} onValueChange={(v) => setPlacementMode(v as "safe_bottom" | "simple_bottom")}>
                  <SelectTrigger id="placement-mode">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="safe_bottom">safe_bottom 安全区（推荐，不与原字幕重叠）</SelectItem>
                    <SelectItem value="simple_bottom">simple_bottom 直接底部</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  safe_bottom：缩小原画面 + 底部黑边放新字幕；simple_bottom：直接烧到底部，可能与原字幕重叠。
                </p>
              </div>
            ) : null}

            <div className="flex justify-end">
              <Button type="submit" size="lg" disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {submitting ? "处理中…" : "开始上传并处理"}
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
            <SummaryRow label="视频数" value={String(files.length)} />
            <SummaryRow label="翻译" value={enableTranslate ? `是 → ${targetLang}` : "否"} />
            <SummaryRow label="烧录" value={enableBurn ? `是 (${placementMode})` : "否"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">流程说明</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
            <p>1. 浏览器直传 TOS（不经过本服务）。</p>
            <p>2. 后端调用 VIAPI RecognizeVideoCastCrewList 提取字幕 SRT。</p>
            <p>3. 可选：调用 LLM 翻译 SRT 文本。</p>
            <p>4. 可选：FFmpeg 把字幕硬嵌到视频。</p>
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
