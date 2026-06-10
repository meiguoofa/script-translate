import { useEffect, useState } from "react";
import { Download, FileText, Loader2, RefreshCw, Sparkles } from "lucide-react";
import {
  createCleanedScript,
  getCleanedScriptDownloadUrl,
  getCleanedScripts,
} from "../api/client";
import type { CleanedScriptCreateResponse, CleanedScriptSummary } from "../api/types";
import { Dropzone } from "../components/Dropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/sonner";

export function CleanScriptPage() {
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [history, setHistory] = useState<CleanedScriptSummary[]>([]);
  const [latest, setLatest] = useState<CleanedScriptCreateResponse | null>(null);

  async function loadHistory() {
    setLoadingHistory(true);
    try {
      setHistory(await getCleanedScripts());
    } catch {
      toast.error("清理历史加载失败，请稍后重试。");
    } finally {
      setLoadingHistory(false);
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;

    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("title", title);
      formData.append("file", file);
      const result = await createCleanedScript(formData);
      setLatest(result);
      setTitle("");
      setFile(null);
      await loadHistory();
      toast.success("干净剧本已生成，可下载查看。");
    } catch {
      toast.error("清理失败，请确认文件格式后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = Boolean(title.trim() && file && !submitting);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>上传文档并清理译文</CardTitle>
          <CardDescription>移除对白末尾括号内译文，生成新的干净剧本 DOCX。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="clean-title">剧本标题</Label>
              <Input
                id="clean-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：火花瞬间燃点-修订版"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>上传已翻译文档</Label>
              <Dropzone file={file} onFileChange={setFile} />
              <p className="text-xs text-muted-foreground">
                支持 .doc / .docx / .txt，系统只会移除对白行尾追加的译文括号。
              </p>
            </div>

            <div className="flex justify-end pt-2">
              <Button type="submit" size="lg" disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {submitting ? "处理中…" : "生成干净剧本"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">清理规则</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
            <p>仅删除对白分隔符后、行尾最后一组括号中的译文。</p>
            <div className="rounded-md bg-muted p-3 text-xs leading-relaxed text-foreground">
              <p>艾米丽（低声）：hello(你好)</p>
              <p className="text-muted-foreground">→ 艾米丽（低声）：hello</p>
            </div>
            <p>人物动作括号、场景说明括号会保留。</p>
          </CardContent>
        </Card>

        {latest ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">最新结果</CardTitle>
              <CardDescription>{latest.output_filename}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              <StatRow label="总行数" value={String(latest.line_count)} />
              <StatRow label="清理行数" value={String(latest.stripped_count)} />
              <Button asChild>
                <a href={getCleanedScriptDownloadUrl(latest.id)}>
                  <Download className="h-4 w-4" />
                  下载干净剧本
                </a>
              </Button>
            </CardContent>
          </Card>
        ) : null}
      </div>

      <Card className="lg:col-span-3">
        <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle>清理历史</CardTitle>
            <CardDescription>历史记录会保留在数据库中，便于重复下载。</CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={loadHistory} disabled={loadingHistory}>
            <RefreshCw className={loadingHistory ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          {loadingHistory ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((item) => (
                <Skeleton key={item} className="h-28" />
              ))}
            </div>
          ) : history.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed py-12 text-center">
              <FileText className="h-8 w-8 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">暂无清理历史</p>
                <p className="mt-1 text-xs text-muted-foreground">上传文档并生成后，这里会显示记录。</p>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {history.map((item) => (
                <div key={item.id} className="flex flex-col gap-3 rounded-lg border bg-card p-4">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{item.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.source_filename ?? "上传文档"}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">{item.line_count} 行</Badge>
                    <Badge variant="success">清理 {item.stripped_count} 行</Badge>
                  </div>
                  <Separator />
                  <Button asChild variant="outline" size="sm">
                    <a href={getCleanedScriptDownloadUrl(item.id)}>
                      <Download className="h-4 w-4" />
                      下载
                    </a>
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
