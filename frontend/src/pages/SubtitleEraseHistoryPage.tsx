import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listSubtitleEraseJobs } from "@/api/client";
import type { SubtitleEraseJobSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/sonner";

const PAGE_SIZE = 20;

const STATUS_VARIANT: Record<
  SubtitleEraseJobSummary["status"],
  "info" | "success" | "destructive" | "muted"
> = {
  pending: "muted",
  running: "info",
  completed: "success",
  failed: "destructive",
};

const STATUS_LABEL: Record<SubtitleEraseJobSummary["status"], string> = {
  pending: "排队中",
  running: "处理中",
  completed: "已完成",
  failed: "失败",
};

export function SubtitleEraseHistoryPage() {
  const [items, setItems] = useState<SubtitleEraseJobSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);

  async function loadMore(reset = false) {
    setLoading(true);
    try {
      const nextOffset = reset ? 0 : offset;
      const data = await listSubtitleEraseJobs({ limit: PAGE_SIZE, offset: nextOffset });
      setItems((prev) => (reset ? data : [...prev, ...data]));
      setOffset(nextOffset + data.length);
      setHasMore(data.length === PAGE_SIZE);
    } catch {
      toast.error("加载历史失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMore(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>字幕擦除 + 翻译 历史</CardTitle>
          <CardDescription>所有曾经提交过的字幕擦除翻译任务，按时间倒序。</CardDescription>
        </CardHeader>
      </Card>

      {items.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            暂无任务，前往「字幕擦除翻译」开始第一次处理。
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-col gap-3">
        {items.map((item) => (
          <Card key={item.id}>
            <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{item.title}</span>
                  <Badge variant={STATUS_VARIANT[item.status]}>
                    {STATUS_LABEL[item.status]}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {item.drama_count} 部剧 · {item.video_count} 集 ·{" "}
                  {item.detext_mode === "advanced" ? "高级擦除" : "基础擦除"} ·{" "}
                  {item.translate_mode === "aliyun" ? "阿里云翻译" : "LLM 翻译"} → {item.target_lang} ·
                  成功 {item.succeeded_count} · 失败 {item.failed_count} · 创建于{" "}
                  {new Date(item.created_at).toLocaleString()}
                </p>
                {item.error_message ? (
                  <p className="text-xs text-destructive">{item.error_message}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-2">
                <Link to={`/subtitle-erase/${item.id}`}>
                  <Button size="sm" variant="ghost">
                    查看详情
                  </Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {hasMore ? (
        <div className="flex justify-center">
          <Button variant="ghost" onClick={() => loadMore(false)} disabled={loading}>
            {loading ? "加载中…" : "加载更多"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
