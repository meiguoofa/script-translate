import { useCallback, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Film, Upload, X } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
};

export function MultiVideoDropzone({ files, onChange, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const append = useCallback(
    (incoming: FileList | File[]) => {
      const list = Array.from(incoming).filter((f) =>
        f.type.startsWith("video/") || /\.(mp4|mov|m4v|avi|mkv|webm)$/i.test(f.name)
      );
      if (!list.length) return;
      onChange([...files, ...list]);
    },
    [files, onChange]
  );

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLLabelElement>) => {
      event.preventDefault();
      setIsDragging(false);
      if (disabled) return;
      const dropped = event.dataTransfer.files;
      if (dropped?.length) append(dropped);
    },
    [append, disabled]
  );

  function move(index: number, dir: -1 | 1) {
    const next = [...files];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  function remove(index: number) {
    const next = [...files];
    next.splice(index, 1);
    onChange(next);
  }

  return (
    <div className="flex flex-col gap-3">
      <label
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed bg-card/40 px-6 py-8 text-center transition-colors",
          disabled && "cursor-not-allowed opacity-60",
          isDragging
            ? "border-primary bg-accent/60 text-foreground"
            : "border-border text-muted-foreground hover:border-primary/50 hover:bg-accent/30"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept="video/*,.mp4,.mov,.m4v,.avi,.mkv,.webm"
          multiple
          className="sr-only"
          disabled={disabled}
          onChange={(event) => {
            if (event.target.files) append(event.target.files);
            event.target.value = "";
          }}
        />
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <Upload className="h-5 w-5" />
        </div>
        <span className="text-sm font-medium text-foreground">拖拽或点击选择多个视频</span>
        <span className="text-xs">列表顺序即剧集顺序，可在下方调整</span>
      </label>

      {files.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
                  <Film className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    第 {index + 1} 集 · {file.name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {(file.size / 1024 / 1024).toFixed(1)} MB
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-accent disabled:opacity-40"
                  onClick={() => move(index, -1)}
                  disabled={disabled || index === 0}
                  aria-label="上移"
                >
                  <ArrowUp className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-accent disabled:opacity-40"
                  onClick={() => move(index, 1)}
                  disabled={disabled || index === files.length - 1}
                  aria-label="下移"
                >
                  <ArrowDown className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                  onClick={() => remove(index)}
                  disabled={disabled}
                  aria-label="移除"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
