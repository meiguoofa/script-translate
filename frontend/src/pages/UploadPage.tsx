import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, ChevronRight } from "lucide-react";
import { createScript, getModels, startTranslation } from "../api/client";
import type { ModelOption } from "../api/types";
import { Dropzone } from "../components/Dropzone";
import { ModelSelector } from "../components/ModelSelector";
import { resolveInitialModelSelection, saveDoubaoModel } from "../modelPreferences";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { toast } from "@/components/ui/sonner";

const TARGET_LANG_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英语" },
  { value: "th", label: "泰语" },
  { value: "ar", label: "阿拉伯语" },
];

const WORKFLOW_STEPS = [
  { title: "导入剧本", desc: "上传文件或粘贴文本，自动识别对话行" },
  { title: "调用模型", desc: "按所选模型批量翻译人物对白" },
  { title: "校对导出", desc: "逐行对照核对并导出 DOCX" },
];

export function UploadPage() {
  const navigate = useNavigate();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rawText, setRawText] = useState("");
  const [targetLang, setTargetLang] = useState("zh");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getModels()
      .then((data) => {
        setModels(data);
        const initialSelection = resolveInitialModelSelection(data);
        if (initialSelection) {
          setProvider(initialSelection.provider);
          setModel(initialSelection.model);
          return;
        }
        toast.error("当前没有可用模型，请先在后端配置豆包或其他 Provider。");
      })
      .catch(() => {
        toast.error("模型列表加载失败，请检查后端 Provider 配置。");
      });
  }, []);

  useEffect(() => {
    saveDoubaoModel(provider, model);
  }, [provider, model]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("title", title);
      if (file) {
        formData.append("file", file);
      } else {
        formData.append("raw_text", rawText);
      }

      const script = await createScript(formData);
      const translation = await startTranslation(script.script_id, {
        target_lang: targetLang,
        provider,
        model,
      });
      navigate(`/scripts/${script.script_id}?versionId=${translation.version_id}`);
    } catch {
      toast.error("上传或翻译启动失败，请检查输入后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  const targetLangLabel =
    TARGET_LANG_OPTIONS.find((option) => option.value === targetLang)?.label ?? targetLang;
  const canSubmit = Boolean(provider && model && (file || rawText.trim()) && title.trim() && !submitting);

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>新建翻译任务</CardTitle>
          <CardDescription>填写基本信息并选择模型，提交后即可在剧本详情页查看进度。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="title">剧本标题</Label>
              <Input
                id="title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：火花瞬间燃点"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>上传剧本文件</Label>
              <Dropzone file={file} onFileChange={setFile} />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="raw-text">或直接粘贴纯文本</Label>
              <Textarea
                id="raw-text"
                value={rawText}
                onChange={(event) => setRawText(event.target.value)}
                placeholder="如果不上传文件，可以直接粘贴剧本文本。"
                rows={10}
                disabled={Boolean(file)}
              />
              {file ? <p className="text-xs text-muted-foreground">已选择文件，文本输入已禁用。</p> : null}
            </div>

            <Separator />

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label>目标语言</Label>
                <Select value={targetLang} onValueChange={setTargetLang}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TARGET_LANG_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <ModelSelector
              models={models}
              provider={provider}
              model={model}
              onChange={(nextProvider, nextModel) => {
                setProvider(nextProvider);
                setModel(nextModel);
              }}
            />

            <div className="flex justify-end pt-2">
              <Button type="submit" size="lg" disabled={!canSubmit}>
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {submitting ? "处理中…" : "开始翻译"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">任务配置摘要</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            <SummaryRow label="输入源" value={file ? "文件上传" : rawText.trim() ? "纯文本粘贴" : "未填写"} />
            <SummaryRow label="目标语言" value={targetLangLabel} />
            <SummaryRow label="模型厂商" value={provider || "未选择"} />
            <SummaryRow label="模型名称" value={model || "未选择"} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">处理流程</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {WORKFLOW_STEPS.map((step, index) => (
              <div key={step.title} className="flex items-start gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
                  {index + 1}
                </div>
                <div>
                  <p className="text-sm font-medium">{step.title}</p>
                  <p className="text-xs text-muted-foreground">{step.desc}</p>
                </div>
              </div>
            ))}
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
      <span className="flex items-center gap-1 truncate font-medium">
        {value}
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40" />
      </span>
    </div>
  );
}