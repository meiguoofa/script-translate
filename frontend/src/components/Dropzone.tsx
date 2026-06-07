import { useCallback, useState } from "react";
import { FileText, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";

type DropzoneProps = {
  file: File | null;
  onFileChange: (file: File | null) => void;
};

export function Dropzone({ file, onFileChange }: DropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLLabelElement>) => {
      event.preventDefault();
      setIsDragging(false);
      const dropped = event.dataTransfer.files?.[0] ?? null;
      if (dropped) {
        onFileChange(dropped);
      }
    },
    [onFileChange]
  );

  if (file) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border bg-card px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB · 已选择</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onFileChange(null)}
          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label="移除文件"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <label
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={onDrop}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed bg-card/40 px-6 py-10 text-center transition-colors",
        isDragging
          ? "border-primary bg-accent/60 text-foreground"
          : "border-border text-muted-foreground hover:border-primary/50 hover:bg-accent/30"
      )}
    >
      <input
        type="file"
        accept=".doc,.docx,.txt"
        className="sr-only"
        onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
      />
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-foreground">
        <Upload className="h-5 w-5" />
      </div>
      <span className="text-sm font-medium text-foreground">拖拽或点击上传剧本文件</span>
      <span className="text-xs">支持 .doc / .docx / .txt</span>
    </label>
  );
}