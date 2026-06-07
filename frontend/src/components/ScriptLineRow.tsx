import { cn } from "@/lib/utils";

type ScriptLineRowProps = {
  lineNo: number;
  rawLine: string;
  renderedLine?: string;
  isDialogue: boolean;
};

export function ScriptLineRow({ lineNo, rawLine, renderedLine, isDialogue }: ScriptLineRowProps) {
  if (!rawLine) {
    return <div className="h-3" aria-hidden="true" />;
  }

  const lineNumber = (
    <span className="select-none pt-0.5 text-right font-mono text-[11px] text-muted-foreground">
      {String(lineNo).padStart(3, "0")}
    </span>
  );

  if (!isDialogue) {
    return (
      <div className="grid grid-cols-[3rem_1fr] items-start gap-4 rounded-md px-3 py-2 transition-colors hover:bg-muted/40">
        {lineNumber}
        <div className="text-sm italic text-muted-foreground">{rawLine}</div>
      </div>
    );
  }

  if (!renderedLine || renderedLine === rawLine) {
    return (
      <div className="grid grid-cols-[3rem_1fr] items-start gap-4 rounded-md px-3 py-2 transition-colors hover:bg-muted/40">
        {lineNumber}
        <div className="text-sm leading-relaxed">{rawLine}</div>
      </div>
    );
  }

  const suffix = renderedLine.startsWith(rawLine) ? renderedLine.slice(rawLine.length) : "";

  return (
    <div className={cn("grid grid-cols-[3rem_1fr] items-start gap-4 rounded-md px-3 py-2 transition-colors hover:bg-muted/40")}>
      {lineNumber}
      <div className="text-sm leading-relaxed">
        <span>{rawLine}</span>
        {suffix ? (
          <span className="ml-1 font-medium text-primary">{suffix}</span>
        ) : null}
      </div>
    </div>
  );
}