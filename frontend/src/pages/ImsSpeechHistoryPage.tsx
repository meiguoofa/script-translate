import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listImsSpeechJobs } from "@/api/client";
import type { ImsSpeechJobSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/sonner";

const PAGE_SIZE = 20;
const STATUS = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
} as const;

export function ImsSpeechHistoryPage() {
  const [items, setItems] = useState<ImsSpeechJobSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);

  async function load(reset: boolean, search: string) {
    setLoading(true);
    try {
      const nextOffset = reset ? 0 : offset;
      const data = await listImsSpeechJobs({
        limit: PAGE_SIZE,
        offset: nextOffset,
        q: search || undefined,
      });
      setItems((current) => (reset ? data : [...current, ...data]));
      setOffset(nextOffset + data.length);
      setHasMore(data.length === PAGE_SIZE);
    } catch {
      toast.error("加载 IMS 语音翻译历史失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => load(true, query.trim()), 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>IMS 语音翻译历史</CardTitle>
          <CardDescription>
            独立记录阿里云 IMS 一站式语音级翻译任务，不与字幕擦除翻译历史混合。
          </CardDescription>
        </CardHeader>
      </Card>

      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="搜索任务标题…"
      />

      {items.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            暂无 IMS 语音翻译任务。
          </CardContent>
        </Card>
      ) : null}

      <div className="space-y-3">
        {items.map((item) => {
          const status = STATUS[item.status];
          return (
            <Card key={item.id}>
              <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{item.title}</span>
                    <Badge variant={status.variant}>{status.label}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {item.drama_count} 部剧 · {item.video_count} 集 · {item.text_source} ·{" "}
                    {item.source_language} → {item.target_languages.join(", ")} · 成功{" "}
                    {item.succeeded_count} · 部分失败 {item.partial_failed_count} · 失败{" "}
                    {item.failed_count} · {new Date(item.created_at).toLocaleString()}
                  </p>
                  {item.error_message ? (
                    <p className="text-xs text-destructive">{item.error_message}</p>
                  ) : null}
                </div>
                <Link to={`/ims-speech/${item.id}`}>
                  <Button size="sm" variant="ghost">查看详情</Button>
                </Link>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {hasMore ? (
        <div className="flex justify-center">
          <Button
            variant="ghost"
            disabled={loading}
            onClick={() => load(false, query.trim())}
          >
            {loading ? "加载中…" : "加载更多"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
