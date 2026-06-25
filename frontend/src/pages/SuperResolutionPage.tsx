import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2 } from "lucide-react";
import {
  createSuperResJob,
  requestSuperResUploadUrls,
} from "@/api/client";
import type { SuperResUploadEntry } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { toast } from "@/components/ui/sonner";
import { MultiVideoDropzone } from "@/components/MultiVideoDropzone";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";

export function SuperResolutionPage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [bitRate, setBitRate] = useState<number>(10);
  const [progress, setProgress] = useState<Record<number, number>>({});
  const [submitting, setSubmitting] = useState(false);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  const canSubmit =
    Boolean(title.trim()) &&
    files.length > 0 &&
    bitRate >= 1 &&
    bitRate <= 20 &&
    !submitting;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setProgress({});
    try {
      const upload = await requestSuperResUploadUrls({
        files: files.map((f) => ({
          filename: f.name,
          content_type: f.type || "video/mp4",
        })),
      });

      await Promise.all(
        upload.entries.map((entry: SuperResUploadEntry, index: number) =>
          axios.put(entry.presigned_url, files[index], {
            headers: { "Content-Type": files[index].type || "video/mp4" },
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

      const job = await createSuperResJob({
        job_id: upload.job_id,
        title: title.trim(),
        bit_rate: bitRate,
        items: upload.entries.map((e, i) => ({
          filename: files[i].name,
          oss_uri: e.oss_uri,
          public_url: e.public_url,
          key: e.key,
        })),
        original_filenames: files.map((f) => f.name),
      });
      toast.success("任务已提交，正在超分辨");
      navigate(`/super-resolution/${job.id}`);
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
          <CardTitle>视频超分辨</CardTitle>
          <CardDescription>
            上传一个或多个视频，浏览器直传到阿里云 OSS，后端调用 VIAPI 超分辨算子，输出视频写回同一个 OSS 桶。
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
                placeholder="例如：第1集超分辨测试"
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
              <Label htmlFor="bit-rate">输出码率 BitRate（Mbps，1–20）</Label>
              <Input
                id="bit-rate"
                type="number"
                min={1}
                max={20}
                step={1}
                value={bitRate}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isNaN(v)) return;
                  setBitRate(Math.min(20, Math.max(1, Math.round(v))));
                }}
              />
              <p className="text-xs text-muted-foreground">
                默认 10。所有视频共用同一个码率。
              </p>
            </div>

            <div className="flex justify-end">
              <Button type="submit" size="lg" disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {submitting ? "处理中…" : "开始上传并超分辨"}
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
            <SummaryRow label="码率" value={`${bitRate} Mbps`} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">流程说明</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
            <p>1. 浏览器直传阿里云 OSS（不经过本服务）。</p>
            <p>2. 后端为每个视频调用 VIAPI SuperResolveVideo。</p>
            <p>3. 完成后输出视频写回同一个 OSS 桶。</p>
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
