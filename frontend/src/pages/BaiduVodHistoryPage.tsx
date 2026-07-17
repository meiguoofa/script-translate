import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listBaiduVodJobs } from "@/api/client";
import type { BaiduVodJobSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PassphraseGate } from "@/components/PassphraseGate";
import { getPassphrase } from "@/lib/passphrase";

const JOB_BADGE: Record<string, { label: string; variant: "info" | "success" | "destructive" | "muted" }> = {
  pending: { label: "排队中", variant: "muted" },
  running: { label: "处理中", variant: "info" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

const LANG_LABELS: Record<string, string> = {
  "zh-CN": "中文", "en-US": "英文", "ja-JP": "日文", "ko-KR": "韩文",
  "de-DE": "德文", "fr-FR": "法文", "ru-RU": "俄文", "es-ES": "西班牙文",
  "pt-PT": "葡萄牙文", "id-ID": "印尼文", "vi-VN": "越南文", "th-TH": "泰文",
};

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "--";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function BaiduVodHistoryPage() {
  const navigate = useNavigate();
  const [verified, setVerified] = useState<boolean>(Boolean(getPassphrase()));
  const [jobs, setJobs] = useState<BaiduVodJobSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!verified) return;
    (async () => {
      try {
        const data = await listBaiduVodJobs({ limit: 50 });
        setJobs(data);
      } catch {
        // 静默
      } finally {
        setLoading(false);
      }
    })();
  }, [verified]);

  if (!verified) {
    return <PassphraseGate onVerified={() => setVerified(true)} />;
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">百度 VOD 翻译历史</h1>
        <Button variant="outline" onClick={() => navigate("/baidu-vod")}>新建任务</Button>
      </div>
      {loading ? (
        <p className="text-muted-foreground">加载中...</p>
      ) : jobs.length === 0 ? (
        <p className="text-muted-foreground">暂无任务</p>
      ) : (
        <div className="space-y-2">
          {jobs.map((j) => {
            const badge = JOB_BADGE[j.status] || { label: j.status, variant: "muted" as const };
            return (
              <Card key={j.id} className="cursor-pointer hover:bg-muted/50"
                onClick={() => navigate(`/baidu-vod/${j.id}`)}>
                <CardContent className="flex items-center justify-between py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{j.title}</span>
                      <Badge variant={badge.variant}>{badge.label}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {j.drama_count} 部剧 · {j.video_count} 集 · 总时长 {formatDuration(j.total_duration_seconds)} ·{" "}
                      {LANG_LABELS[j.source_language] || j.source_language}{" -> "}
                      {j.target_langs.map((l) => LANG_LABELS[l] || l).join("、")} ·{" "}
                      成功 {j.succeeded_count} · 失败 {j.failed_count}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {new Date(j.created_at).toLocaleString("zh-CN")}
                  </span>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
