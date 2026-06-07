import { NavLink, Route, Routes } from "react-router-dom";
import { HistoryPage } from "./pages/HistoryPage";
import { ScriptViewerPage } from "./pages/ScriptViewerPage";
import { UploadPage } from "./pages/UploadPage";

export default function App() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <header className="topbar chrome-card">
        <div className="brand-block">
          <p className="eyebrow">Script Translate Workspace</p>
          <h1>短剧剧本翻译工作台</h1>
          <p className="topbar-subtitle">上传剧本、切换模型、逐行校对、导出成稿</p>
        </div>
        <nav className="topnav" aria-label="主导航">
          <NavLink to="/" end>
            新建翻译
          </NavLink>
          <NavLink to="/history">历史记录</NavLink>
        </nav>
      </header>
      <main className="page-shell" id="main-content">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/scripts/:scriptId" element={<ScriptViewerPage />} />
        </Routes>
      </main>
    </div>
  );
}
