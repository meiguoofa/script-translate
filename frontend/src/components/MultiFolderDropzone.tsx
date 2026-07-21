import { useCallback, useRef, useState } from "react";
import { FolderUp, Trash2, ArrowUp, ArrowDown, Film } from "lucide-react";
import { cn } from "@/lib/utils";

export type DramaFile = {
  filename: string;
  file: File;
};

export type Drama = {
  id: string;
  name: string;
  files: DramaFile[];
};

type Props = {
  dramas: Drama[];
  onChange: (dramas: Drama[]) => void;
  disabled?: boolean;
};

const VIDEO_RE = /\.(mp4|mov|m4v|avi|mkv|webm)$/i;

function naturalSort(a: DramaFile, b: DramaFile): number {
  return a.filename.localeCompare(b.filename, undefined, { numeric: true, sensitivity: "base" });
}

function pickVideoFiles(fileList: FileList | File[]): DramaFile[] {
  const list = Array.from(fileList).filter(
    (f) => f.type.startsWith("video/") || VIDEO_RE.test(f.name)
  );
  return list.map((file) => ({ filename: file.name, file }));
}

function traverseFileSystemEntry(entry: any): Promise<DramaFile[]> {
  if (entry.isFile) {
    return new Promise((resolve) => {
      entry.file((file: File) => {
        if (file.type.startsWith("video/") || VIDEO_RE.test(file.name)) {
          resolve([{ filename: file.name, file }]);
        } else {
          resolve([]);
        }
      });
    });
  }
  if (entry.isDirectory) {
    return new Promise((resolve) => {
      const reader = entry.createReader();
      const all: DramaFile[] = [];
      const readBatch = () => {
        reader.readEntries(async (entries: any[]) => {
          if (entries.length === 0) {
            resolve(all);
            return;
          }
          for (const e of entries) {
            const sub = await traverseFileSystemEntry(e);
            all.push(...sub);
          }
          readBatch();
        });
      };
      readBatch();
    });
  }
  return Promise.resolve([]);
}

export function MultiFolderDropzone({ dramas, onChange, disabled }: Props) {
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const addFilesAsOneDrama = useCallback(
    (incoming: DramaFile[], folderName?: string) => {
      if (!incoming.length) return;
      const sorted = [...incoming].sort(naturalSort);
      const drama: Drama = {
        id: `drama-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        name: folderName || `剧 ${dramas.length + 1}`,
        files: sorted,
      };
      onChange([...dramas, drama]);
    },
    [dramas, onChange]
  );

  const handleFolderPick = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;

      // 优先使用 webkitRelativePath 拿到文件夹结构
      const byFolder = new Map<string, DramaFile[]>();
      const fallback: DramaFile[] = [];
      for (const file of Array.from(files)) {
        const rel = (file as any).webkitRelativePath as string | undefined;
        if (rel && rel.includes("/")) {
          const parts = rel.split("/");
          const folder = parts.slice(0, -1).join("/");
          if (!byFolder.has(folder)) byFolder.set(folder, []);
          byFolder.get(folder)!.push({ filename: file.name, file });
        } else {
          fallback.push({ filename: file.name, file });
        }
      }

      if (byFolder.size > 0) {
        const newDramas: Drama[] = [];
        byFolder.forEach((files, folder) => {
          const filtered = files.filter(
            (f) => f.file.type.startsWith("video/") || VIDEO_RE.test(f.filename)
          );
          if (filtered.length > 0) {
            newDramas.push({
              id: `drama-${Date.now()}-${Math.random().toString(36).slice(2, 6)}-${folder}`,
              name: folder,
              files: filtered.sort(naturalSort),
            });
          }
        });
        onChange([...dramas, ...newDramas]);
      } else if (fallback.length > 0) {
        addFilesAsOneDrama(fallback);
      }

      event.target.value = "";
    },
    [dramas, onChange, addFilesAsOneDrama]
  );

  const handleFilePick = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files || files.length === 0) return;
      const picked = pickVideoFiles(files);
      if (picked.length > 0) addFilesAsOneDrama(picked);
      event.target.value = "";
    },
    [addFilesAsOneDrama]
  );

  const handleDrop = useCallback(
    async (event: React.DragEvent<HTMLLabelElement>) => {
      event.preventDefault();
      setIsDragging(false);
      if (disabled) return;

      const items = event.dataTransfer.items;
      if (items && items.length > 0 && typeof items[0].webkitGetAsEntry === "function") {
        const entries: any[] = [];
        for (let i = 0; i < items.length; i++) {
          const entry = items[i].webkitGetAsEntry();
          if (entry) entries.push(entry);
        }

        // 浏览器对每个被拖拽的对象单独创建一个 entry:
        // - 拖拽文件夹:1 个 isDirectory entry,entry.name = 文件夹名
        // - 拖拽文件:N 个 isFile entry(每个文件一个),浏览器出于安全
        //   考虑不暴露父目录路径(entry.fullPath 只有 "/filename"),
        //   无法按父目录分组,只能把所有散文件合并为一部剧
        const dramaByName = new Map<string, DramaFile[]>();
        const scattered: DramaFile[] = [];
        for (const entry of entries) {
          const files = await traverseFileSystemEntry(entry);
          if (files.length === 0) continue;
          if (entry.isDirectory) {
            const dramaName = entry.name || `剧 ${dramas.length + dramaByName.size + 1}`;
            if (!dramaByName.has(dramaName)) dramaByName.set(dramaName, []);
            dramaByName.get(dramaName)!.push(...files);
          } else {
            // 散文件:浏览器不暴露父目录,无法分组,合并为一部剧
            scattered.push(...files);
          }
        }
        if (scattered.length > 0) {
          const dramaName = `剧 ${dramas.length + dramaByName.size + 1}`;
          dramaByName.set(dramaName, scattered);
        }

        const allDramas: Drama[] = [];
        dramaByName.forEach((files, name) => {
          if (files.length > 0) {
            allDramas.push({
              id: `drama-${Date.now()}-${Math.random().toString(36).slice(2, 6)}-${name}`,
              name,
              files: files.sort(naturalSort),
            });
          }
        });
        if (allDramas.length > 0) {
          onChange([...dramas, ...allDramas]);
        }
        return;
      }

      const dropped = event.dataTransfer.files;
      if (dropped && dropped.length > 0) {
        const picked = pickVideoFiles(dropped);
        if (picked.length > 0) addFilesAsOneDrama(picked);
      }
    },
    [dramas, onChange, addFilesAsOneDrama, disabled]
  );

  function removeDrama(id: string) {
    onChange(dramas.filter((d) => d.id !== id));
  }

  function moveFile(dramaId: string, index: number, dir: -1 | 1) {
    const next = dramas.map((d) => {
      if (d.id !== dramaId) return d;
      const files = [...d.files];
      const target = index + dir;
      if (target < 0 || target >= files.length) return d;
      [files[index], files[target]] = [files[target], files[index]];
      return { ...d, files };
    });
    onChange(next);
  }

  function removeFile(dramaId: string, index: number) {
    const next = dramas
      .map((d) => {
        if (d.id !== dramaId) return d;
        const files = [...d.files];
        files.splice(index, 1);
        return { ...d, files };
      })
      .filter((d) => d.files.length > 0);
    onChange(next);
  }

  const totalFiles = dramas.reduce((s, d) => s + d.files.length, 0);

  return (
    <div className="flex flex-col gap-3">
      <label
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed bg-card/40 px-6 py-8 text-center transition-colors",
          disabled && "cursor-not-allowed opacity-60",
          isDragging
            ? "border-primary bg-accent/60 text-foreground"
            : "border-border text-muted-foreground hover:border-primary/50 hover:bg-accent/30"
        )}
      >
        <input
          ref={folderInputRef}
          type="file"
          // @ts-expect-error - non-standard but widely supported attribute for folder upload
          webkitdirectory=""
          directory=""
          multiple
          className="sr-only"
          disabled={disabled}
          onChange={handleFolderPick}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*,.mp4,.mov,.m4v,.avi,.mkv,.webm"
          multiple
          className="sr-only"
          disabled={disabled}
          onChange={handleFilePick}
        />
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <FolderUp className="h-5 w-5" />
        </div>
        <span className="text-sm font-medium text-foreground">
          拖拽文件夹到此处，或点击选择文件夹
        </span>
        <span className="text-xs">
          每个文件夹 = 一部短剧；文件夹内文件按文件名顺序作为各集
        </span>
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            className="rounded-md border bg-background px-3 py-1 text-xs hover:bg-accent"
            onClick={(event) => {
              event.preventDefault();
              folderInputRef.current?.click();
            }}
            disabled={disabled}
          >
            选择文件夹
          </button>
          <button
            type="button"
            className="rounded-md border bg-background px-3 py-1 text-xs hover:bg-accent"
            onClick={(event) => {
              event.preventDefault();
              fileInputRef.current?.click();
            }}
            disabled={disabled}
          >
            选择多个文件
          </button>
        </div>
      </label>

      {dramas.length > 0 ? (
        <div className="flex flex-col gap-3">
          {dramas.map((drama, di) => (
            <div
              key={drama.id}
              className="rounded-md border bg-card/60 px-3 py-3"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                    第 {di + 1} 部剧
                  </span>
                  <span className="truncate text-sm font-medium">{drama.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {drama.files.length} 集
                  </span>
                </div>
                <button
                  type="button"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                  onClick={() => removeDrama(drama.id)}
                  disabled={disabled}
                  aria-label="移除整剧"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <ul className="flex flex-col gap-1.5">
                {drama.files.map((f, fi) => (
                  <li
                    key={`${f.filename}-${fi}`}
                    className="flex items-center justify-between gap-3 rounded-md border bg-background/60 px-2 py-1.5"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
                        <Film className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium">
                          第 {fi + 1} 集 · {f.filename}
                        </p>
                        <p className="text-[11px] text-muted-foreground">
                          {(f.file.size / 1024 / 1024).toFixed(1)} MB
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5">
                      <button
                        type="button"
                        className="rounded-md p-1 text-muted-foreground hover:bg-accent disabled:opacity-40"
                        onClick={() => moveFile(drama.id, fi, -1)}
                        disabled={disabled || fi === 0}
                        aria-label="上移"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        className="rounded-md p-1 text-muted-foreground hover:bg-accent disabled:opacity-40"
                        onClick={() => moveFile(drama.id, fi, 1)}
                        disabled={disabled || fi === drama.files.length - 1}
                        aria-label="下移"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                        onClick={() => removeFile(drama.id, fi)}
                        disabled={disabled}
                        aria-label="移除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            共 {dramas.length} 部剧 / {totalFiles} 集
          </p>
        </div>
      ) : null}
    </div>
  );
}
