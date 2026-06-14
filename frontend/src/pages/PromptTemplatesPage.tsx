import { useEffect, useState } from "react";
import { Loader2, Pencil, Plus, X } from "lucide-react";
import {
  createPromptTemplate,
  listPromptTemplates,
  updatePromptTemplate,
} from "@/api/client";
import type { PromptTemplateOut } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/sonner";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";

export function PromptTemplatesPage() {
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [items, setItems] = useState<PromptTemplateOut[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newContent, setNewContent] = useState("");
  const [editName, setEditName] = useState("");
  const [editContent, setEditContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function refresh() {
    try {
      const list = await listPromptTemplates();
      setItems(list);
    } catch {
      toast.error("提示词加载失败");
    }
  }

  useEffect(() => {
    if (verified) {
      refresh();
    }
  }, [verified]);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await createPromptTemplate({ name: newName.trim(), content: newContent });
      toast.success("已创建提示词");
      setNewName("");
      setNewContent("");
      setCreating(false);
      await refresh();
    } catch {
      toast.error("创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  function startEdit(item: PromptTemplateOut) {
    setEditingId(item.id);
    setEditName(item.name);
    setEditContent(item.content);
  }

  async function handleEdit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingId) return;
    setSubmitting(true);
    try {
      await updatePromptTemplate(editingId, {
        name: editName.trim(),
        content: editContent,
      });
      toast.success("已更新提示词");
      setEditingId(null);
      await refresh();
    } catch {
      toast.error("更新失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>提示词管理</CardTitle>
            <CardDescription>用于「视频还原剧本」时控制 LAS 算子的生成风格。默认提示词不可编辑。</CardDescription>
          </div>
          {!creating ? (
            <Button onClick={() => setCreating(true)} size="sm">
              <Plus className="h-4 w-4" /> 新增
            </Button>
          ) : null}
        </CardHeader>
        {creating ? (
          <CardContent>
            <form className="flex flex-col gap-4" onSubmit={handleCreate}>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="new-name">名称</Label>
                <Input
                  id="new-name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="例如：偏写实风格"
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="new-content">内容</Label>
                <Textarea
                  id="new-content"
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  rows={12}
                  required
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                  取消
                </Button>
                <Button type="submit" disabled={submitting || !newName.trim() || !newContent.trim()}>
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  保存
                </Button>
              </div>
            </form>
          </CardContent>
        ) : null}
      </Card>

      {items === null ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">暂无提示词</p>
      ) : (
        items.map((item) => (
          <Card key={item.id}>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div className="min-w-0">
                <CardTitle className="flex items-center gap-2 text-base">
                  {item.name}
                  {item.is_default ? <Badge variant="info">默认</Badge> : null}
                </CardTitle>
                <CardDescription>
                  更新时间 {new Date(item.updated_at).toLocaleString()}
                </CardDescription>
              </div>
              {!item.is_default && editingId !== item.id ? (
                <Button size="sm" variant="ghost" onClick={() => startEdit(item)}>
                  <Pencil className="h-4 w-4" /> 编辑
                </Button>
              ) : null}
              {editingId === item.id ? (
                <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                  <X className="h-4 w-4" /> 取消
                </Button>
              ) : null}
            </CardHeader>
            <CardContent>
              {editingId === item.id ? (
                <form className="flex flex-col gap-4" onSubmit={handleEdit}>
                  <div className="flex flex-col gap-1.5">
                    <Label>名称</Label>
                    <Input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>内容</Label>
                    <Textarea
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      rows={14}
                      required
                    />
                  </div>
                  <div className="flex justify-end">
                    <Button type="submit" disabled={submitting}>
                      {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      保存
                    </Button>
                  </div>
                </form>
              ) : (
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">
                  {item.content}
                </pre>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
