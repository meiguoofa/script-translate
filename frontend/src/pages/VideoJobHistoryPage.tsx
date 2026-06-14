import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listVideoJobs } from "@/api/client";
import type { VideoJobSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/sonner";

const PAGE_SIZE = 20;

const STATUS_VARIANT: Record<
  VideoJobSummary["status"],
  "info" | "success" | "destructive" | "muted"
> = {
  pending: "muted",
  submitted: "info",
  running: "info",
  completed: "success",
  failed: "destructive",
};

const STATUS_LABEL: Record<VideoJobSummary["status"], string> = {
  pending: "排队中",
  submitted: "已提交",
  running: "生成中",
  completed: "已完成",
  failed: "失败",
};

export function VideoJobHistoryPage() {
  const [items, setItems] = useState<VideoJobSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);

  async function loadMore(reset = false) {
    setLoading(true);
    try {
      const nextOffset = reset ? 0 : offset;
      const data = await listVideoJobs({ limit: PAGE_SIZE, offset: nextOffset });
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
          <CardTitle>视频还原历史</CardTitle>
          <CardDescription>所有曾经提交过的视频还原任务，按时间倒序。</CardDescription>
        </CardHeader>
      </Card>

      {items.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            暂无任务，前往「视频还原剧本」开始第一次还原。
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
                  {item.video_count} 个视频 · 提示词 {item.prompt_template_name ?? "—"} ·{" "}
                  创建于 {new Date(item.created_at).toLocaleString()}
                </p>
                {item.error_message ? (
                  <p className="text-xs text-destructive">{item.error_message}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-2">
                <Link to={`/video-restore/${item.id}`}>
                  <Button size="sm" variant="ghost">
                    查看详情
                  </Button>
                </Link>
                {item.status === "completed" && item.generated_script_id ? (
                  <Link to={`/scripts/${item.generated_script_id}`}>
                    <Button size="sm">打开剧本</Button>
                  </Link>
                ) : null}
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
