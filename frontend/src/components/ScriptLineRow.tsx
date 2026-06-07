type ScriptLineRowProps = {
  lineNo: number;
  rawLine: string;
  renderedLine?: string;
  isDialogue: boolean;
};

export function ScriptLineRow({ lineNo, rawLine, renderedLine, isDialogue }: ScriptLineRowProps) {
  if (!rawLine) {
    return <div className="line-row empty-line" />;
  }

  if (!isDialogue || !renderedLine || renderedLine === rawLine) {
    return (
      <div className={`line-row ${isDialogue ? "dialogue-line" : "scene-line"}`}>
        <span className="line-number">{String(lineNo).padStart(3, "0")}</span>
        <div className="line-content">{rawLine}</div>
      </div>
    );
  }

  const suffix = renderedLine.startsWith(rawLine) ? renderedLine.slice(rawLine.length) : "";
  return (
    <div className="line-row dialogue-line">
      <span className="line-number">{String(lineNo).padStart(3, "0")}</span>
      <div className="line-content">
        <span>{rawLine}</span>
        <span className="translated-suffix">{suffix}</span>
      </div>
    </div>
  );
}
