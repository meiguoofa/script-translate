import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { Captions, Eraser, FileText, Film, History, Languages, Settings, Sparkles, Wand2, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "新建翻译", icon: FileText, end: true },
  { to: "/clean", label: "清理译文", icon: Sparkles, end: false },
  { to: "/video-restore", label: "视频还原剧本", icon: Film, end: true },
  { to: "/video-restore/history", label: "视频任务历史", icon: History, end: false },
  { to: "/super-resolution", label: "视频超分辨", icon: Zap, end: true },
  { to: "/super-resolution/history", label: "超分辨历史", icon: History, end: false },
  { to: "/subtitle", label: "视频字幕", icon: Captions, end: true },
  { to: "/subtitle/history", label: "字幕历史", icon: History, end: false },
  { to: "/subtitle-erase", label: "字幕擦除翻译", icon: Eraser, end: true },
  { to: "/subtitle-erase/history", label: "擦除翻译历史", icon: History, end: false },
  { to: "/prompts", label: "提示词管理", icon: Wand2, end: false },
  { to: "/history", label: "翻译历史", icon: History, end: false },
];

function pageTitle(pathname: string, scriptId?: string) {
  if (pathname === "/") return { title: "新建翻译", subtitle: "上传剧本、选择模型、启动翻译任务" };
  if (pathname.startsWith("/clean")) return { title: "清理译文", subtitle: "上传已翻译文档，移除括号内译文并导出干净剧本" };
  if (pathname === "/video-restore") return { title: "视频还原剧本", subtitle: "上传整集短剧视频，自动还原成可翻译的剧本" };
  if (pathname === "/video-restore/history") return { title: "视频任务历史", subtitle: "查看所有视频还原任务" };
  if (pathname.startsWith("/video-restore/")) return { title: "视频任务详情", subtitle: "查看 LAS 还原进度并启动翻译" };
  if (pathname === "/super-resolution") return { title: "视频超分辨", subtitle: "上传视频，调用阿里云 VIAPI 超分辨增强" };
  if (pathname === "/super-resolution/history") return { title: "超分辨历史", subtitle: "查看所有视频超分辨任务" };
  if (pathname.startsWith("/super-resolution/")) return { title: "超分辨任务详情", subtitle: "查看处理进度并下载结果" };
  if (pathname === "/subtitle") return { title: "视频字幕", subtitle: "提取字幕 → 翻译 → 烧录到新视频" };
  if (pathname === "/subtitle/history") return { title: "字幕历史", subtitle: "查看所有字幕处理任务" };
  if (pathname.startsWith("/subtitle/")) return { title: "字幕任务详情", subtitle: "查看提取/翻译/烧录进度并下载" };
  if (pathname === "/subtitle-erase") return { title: "字幕擦除翻译", subtitle: "提取 → 擦除原字幕 → 翻译 → 烧录译文字幕" };
  if (pathname === "/subtitle-erase/history") return { title: "擦除翻译历史", subtitle: "查看所有字幕擦除翻译任务" };
  if (pathname.startsWith("/subtitle-erase/")) return { title: "擦除翻译任务详情", subtitle: "查看各阶段进度并下载" };
  if (pathname.startsWith("/prompts")) return { title: "提示词管理", subtitle: "维护视频还原使用的提示词" };
  if (pathname.startsWith("/history")) return { title: "翻译历史", subtitle: "查看所有剧本及历史翻译版本" };
  if (pathname.startsWith("/scripts/")) return { title: "剧本详情", subtitle: scriptId ? `脚本 ${scriptId.slice(0, 8)}…` : "" };
  return { title: "", subtitle: "" };
}

export function AppShell() {
  const location = useLocation();
  const { scriptId } = useParams();
  const { title, subtitle } = pageTitle(location.pathname, scriptId);

  return (
    <div className="flex min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        跳到主要内容
      </a>

      <aside className="hidden md:flex md:w-60 md:flex-col md:border-r md:bg-card">
        <div className="flex h-16 items-center gap-2 border-b px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Languages className="h-4 w-4" />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold tracking-tight">Script Translate</span>
            <span className="text-[11px] text-muted-foreground">剧本翻译工作台</span>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="主导航">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t p-3">
          <button
            type="button"
            disabled
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground opacity-60"
            title="设置（即将推出）"
          >
            <Settings className="h-4 w-4" />
            设置
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b bg-card/80 px-6 backdrop-blur supports-[backdrop-filter]:bg-card/60">
          <div className="md:hidden flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Languages className="h-4 w-4" />
            </div>
            <span className="text-sm font-semibold">Script Translate</span>
          </div>
          <div className="hidden md:flex flex-col">
            <h1 className="text-base font-semibold tracking-tight">{title}</h1>
            {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
          </div>
          <nav className="flex items-center gap-2 md:hidden">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground"
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main id="main-content" className="flex-1 overflow-x-hidden">
          <div className="mx-auto w-full max-w-7xl p-6 md:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}