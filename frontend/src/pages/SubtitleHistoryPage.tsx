import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listSubtitleJobs } from "@/api/client";
import type { SubtitleJobSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/sonner";

const PAGE_SIZE = 20;

const STATUS_VARIANT: Record<
  SubtitleJobSummary["status"],
  "info" | "success" | "destructive" | "muted"
> = {
  pending: "muted",
  running: "info",
  completed: "success",
  failed: "destructive",
};

const STATUS_LABEL: Record<SubtitleJobSummary["status"], string> = {
  pending: "排队中",
  running: "处理中",
  completed: "已完成",
  failed: "失败",
};

const SOURCE_LABEL: Record<string, string> = {
  chinese: "中文",
  all: "全部",
};

export function SubtitleHistoryPage() {
  const [items, setItems] = useState<SubtitleJobSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);

  async function loadMore(reset = false) {
    setLoading(true);
    try {
      const nextOffset = reset ? 0 : offset;
      const data = await listSubtitleJobs({ limit: PAGE_SIZE, offset: nextOffset });
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
          <CardTitle>视频字幕历史</CardTitle>
          <CardDescription>所有曾经提交过的字幕处理任务，按时间倒序。</CardDescription>
        </CardHeader>
      </Card>

      {items.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            暂无任务，前往「视频字幕」开始第一次处理。
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
                  {item.video_count} 个视频 · 字幕来源 {SOURCE_LABEL[item.subtitle_source] ?? item.subtitle_source}
                  {item.enable_translate ? " · 翻译" : ""}
                  {item.enable_burn ? " · 烧录" : ""}
                  {" · 成功 "}
                  {item.succeeded_count}
                  {" · 失败 "}
                  {item.failed_count}
                  {" · 创建于 "}
                  {new Date(item.created_at).toLocaleString()}
                </p>
                {item.error_message ? (
                  <p className="text-xs text-destructive">{item.error_message}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-2">
                <Link to={`/subtitle/${item.id}`}>
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
