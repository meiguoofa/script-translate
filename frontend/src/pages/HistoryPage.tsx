import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FilePlus2, FolderOpen, Inbox } from "lucide-react";
import { getScripts, getVersions } from "../api/client";
import type { ScriptSummary, TranslationVersionSummary } from "../api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const STATUS_VARIANT: Record<string, "success" | "info" | "destructive" | "muted"> = {
  done: "success",
  running: "info",
  failed: "destructive",
  pending: "muted",
};

const STATUS_LABEL: Record<string, string> = {
  done: "已完成",
  running: "进行中",
  failed: "失败",
  pending: "等待中",
};

export function HistoryPage() {
  const [scripts, setScripts] = useState<ScriptSummary[]>([]);
  const [versions, setVersions] = useState<Record<string, TranslationVersionSummary[]>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getScripts()
      .then(async (items) => {
        if (cancelled) return;
        setScripts(items);
        const pairs = await Promise.all(
          items.map(async (script) => [script.id, await getVersions(script.id)] as const)
        );
        if (cancelled) return;
        setVersions(Object.fromEntries(pairs));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-1/3" />
              <Skeleton className="mt-2 h-4 w-1/4" />
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (scripts.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-4 py-16">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-accent text-accent-foreground">
            <Inbox className="h-7 w-7" />
          </div>
          <div className="text-center">
            <h3 className="text-base font-semibold">暂无翻译历史</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              新建一个翻译任务后，这里会显示所有剧本与版本。
            </p>
          </div>
          <Button asChild>
            <Link to="/">
              <FilePlus2 className="h-4 w-4" />
              新建翻译
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {scripts.map((script) => {
        const scriptVersions = versions[script.id] ?? [];
        return (
          <Card key={script.id}>
            <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
              <div className="min-w-0 flex-1">
                <CardTitle className="truncate">{script.title}</CardTitle>
                <CardDescription className="flex items-center gap-2">
                  <Badge variant="outline">{script.source_lang ?? "未知源语言"}</Badge>
                  <span>·</span>
                  <span>{script.version_count} 个版本</span>
                </CardDescription>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to={`/scripts/${script.id}`}>
                  <FolderOpen className="h-4 w-4" />
                  打开剧本
                </Link>
              </Button>
            </CardHeader>
            <CardContent>
              {scriptVersions.length === 0 ? (
                <p className="text-sm text-muted-foreground">该剧本暂无翻译版本。</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {scriptVersions.map((version) => (
                    <Link
                      key={version.id}
                      to={`/scripts/${script.id}?versionId=${version.id}`}
                      className="group flex flex-col gap-2 rounded-lg border bg-card p-3 transition-all hover:border-primary/40 hover:shadow-sm"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium">{version.model_provider}</span>
                        <Badge variant={STATUS_VARIANT[version.status] ?? "muted"} className="shrink-0">
                          {STATUS_LABEL[version.status] ?? version.status}
                        </Badge>
                      </div>
                      <p className="truncate text-xs text-muted-foreground">{version.model_name}</p>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">目标: {version.target_lang}</span>
                        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}