import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { Toaster } from "./components/ui/sonner";
import { TooltipProvider } from "./components/ui/tooltip";
import { CleanScriptPage } from "./pages/CleanScriptPage";
import { HistoryPage } from "./pages/HistoryPage";
import { PromptTemplatesPage } from "./pages/PromptTemplatesPage";
import { ScriptViewerPage } from "./pages/ScriptViewerPage";
import { SuperResolutionDetailPage } from "./pages/SuperResolutionDetailPage";
import { SuperResolutionHistoryPage } from "./pages/SuperResolutionHistoryPage";
import { SuperResolutionPage } from "./pages/SuperResolutionPage";
import { UploadPage } from "./pages/UploadPage";
import { VideoJobDetailPage } from "./pages/VideoJobDetailPage";
import { VideoJobHistoryPage } from "./pages/VideoJobHistoryPage";
import { VideoRestorePage } from "./pages/VideoRestorePage";

export default function App() {
  return (
    <TooltipProvider delayDuration={150}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<UploadPage />} />
          <Route path="/clean" element={<CleanScriptPage />} />
          <Route path="/video-restore" element={<VideoRestorePage />} />
          <Route path="/video-restore/history" element={<VideoJobHistoryPage />} />
          <Route path="/video-restore/:jobId" element={<VideoJobDetailPage />} />
          <Route path="/super-resolution" element={<SuperResolutionPage />} />
          <Route path="/super-resolution/history" element={<SuperResolutionHistoryPage />} />
          <Route path="/super-resolution/:jobId" element={<SuperResolutionDetailPage />} />
          <Route path="/prompts" element={<PromptTemplatesPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/scripts/:scriptId" element={<ScriptViewerPage />} />
        </Route>
      </Routes>
      <Toaster position="top-right" richColors />
    </TooltipProvider>
  );
}
