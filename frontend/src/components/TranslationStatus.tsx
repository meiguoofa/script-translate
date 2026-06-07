type TranslationStatusProps = {
  status: string;
  errorMessage?: string | null;
};

const STATUS_LABELS: Record<string, string> = {
  running: "翻译进行中",
  done: "翻译完成",
  failed: "翻译失败",
  pending: "等待执行",
};

export function TranslationStatus({ status, errorMessage }: TranslationStatusProps) {
  return (
    <div className={`status-card status-${status}`}>
      <strong className="status-label">{STATUS_LABELS[status] ?? status}</strong>
      {status === "running" ? <div className="loading-bar" /> : null}
      {errorMessage ? <p>{errorMessage}</p> : null}
    </div>
  );
}
