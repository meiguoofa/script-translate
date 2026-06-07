import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

type TranslationStatusProps = {
  status: string;
  errorMessage?: string | null;
};

const STATUS_MAP: Record<
  string,
  { label: string; variant: "success" | "info" | "destructive" | "muted"; icon: React.ComponentType<{ className?: string }> }
> = {
  running: { label: "翻译进行中", variant: "info", icon: Loader2 },
  done: { label: "已完成", variant: "success", icon: CheckCircle2 },
  failed: { label: "失败", variant: "destructive", icon: XCircle },
  pending: { label: "等待执行", variant: "muted", icon: Clock },
};

export function TranslationStatus({ status, errorMessage }: TranslationStatusProps) {
  const meta = STATUS_MAP[status] ?? { label: status, variant: "muted" as const, icon: Clock };
  const Icon = meta.icon;

  return (
    <div className="flex flex-col items-end gap-2">
      <Badge variant={meta.variant} className="gap-1.5 px-2.5 py-1">
        <Icon className={`h-3.5 w-3.5 ${status === "running" ? "animate-spin" : ""}`} />
        {meta.label}
      </Badge>
      {status === "running" ? (
        <div className="w-40">
          <Progress value={45} className="h-1" />
        </div>
      ) : null}
      {status === "failed" && errorMessage ? (
        <p className="max-w-xs text-right text-xs text-destructive">{errorMessage}</p>
      ) : null}
    </div>
  );
}