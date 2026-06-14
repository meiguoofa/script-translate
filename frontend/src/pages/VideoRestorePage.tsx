import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  createVideoJob,
  listPromptTemplates,
  requestVideoUploadUrls,
} from "@/api/client";
import type { PromptTemplateOut, VideoUploadEntry } from "@/api/types";
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
import { MultiVideoDropzone } from "@/components/MultiVideoDropzone";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";

export function VideoRestorePage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [templates, setTemplates] = useState<PromptTemplateOut[]>([]);
  const [templateId, setTemplateId] = useState<string>("");
  const [progress, setProgress] = useState<Record<number, number>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!verified) return;
    listPromptTemplates()
      .then((list) => {
        setTemplates(list);
        const def = list.find((t) => t.is_default);
        setTemplateId(def?.id ?? list[0]?.id ?? "");
      })
      .catch(() => toast.error("提示词列表加载失败"));
  }, [verified]);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  const canSubmit =
    Boolean(title.trim()) && files.length > 0 && Boolean(templateId) && !submitting;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setProgress({});
    try {
      const upload = await requestVideoUploadUrls({
        files: files.map((f) => ({
          filename: f.name,
          content_type: f.type || "video/mp4",
        })),
      });

      await Promise.all(
        upload.entries.map((entry: VideoUploadEntry, index: number) =>
          axios.put(entry.presigned_url, files[index], {
            headers: {
              "Content-Type": files[index].type || "video/mp4",
            },
            onUploadProgress: (event) => {
              if (event.total) {
                setProgress((prev) => ({
                  ...prev,
                  [index]: Math.round((event.loaded / event.total!) * 100),
                }));
              }
            },
          })
        )
      );

      const job = await createVideoJob({
        job_id: upload.job_id,
        title: title.trim(),
        video_urls: upload.entries.map((e) => e.tos_uri),
        original_filenames: files.map((f) => f.name),
        prompt_template_id: templateId,
      });
      toast.success("任务已提交，正在生成剧本");
      navigate(`/video-restore/${job.id}`);
    } catch (error) {
      console.error(error);
      toast.error("上传或提交失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  const selectedTemplate = templates.find((t) => t.id === templateId);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>视频还原剧本</CardTitle>
          <CardDescription>
            上传整集短剧视频（按集顺序排列），调用 LAS 算子还原成可翻译的剧本文本。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="title">剧名 / 标题</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如：火花瞬间燃点"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>视频文件（按集顺序）</Label>
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
              <Label>提示词</Label>
              <Select value={templateId} onValueChange={setTemplateId}>
                <SelectTrigger>
                  <SelectValue placeholder="选择提示词" />
                </SelectTrigger>
                <SelectContent>
                  {templates.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                      {item.is_default ? "（默认）" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                可在「提示词管理」中新增/编辑自定义提示词。
              </p>
            </div>

            <div className="flex justify-end">
              <Button type="submit" size="lg" disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {submitting ? "处理中…" : "开始上传并生成剧本"}
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
            <SummaryRow label="视频集数" value={String(files.length)} />
            <SummaryRow label="提示词" value={selectedTemplate?.name || "未选择"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">流程说明</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
            <p>1. 浏览器直传 TOS（不经过本服务）。</p>
            <p>2. 后端调用 LAS 短剧剧本生成算子，生成产物存回 TOS。</p>
            <p>3. 完成后自动落库为剧本，可直接进入「新建翻译」流程。</p>
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
