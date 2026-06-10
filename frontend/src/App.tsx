import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { Toaster } from "./components/ui/sonner";
import { TooltipProvider } from "./components/ui/tooltip";
import { CleanScriptPage } from "./pages/CleanScriptPage";
import { HistoryPage } from "./pages/HistoryPage";
import { ScriptViewerPage } from "./pages/ScriptViewerPage";
import { UploadPage } from "./pages/UploadPage";

export default function App() {
  return (
    <TooltipProvider delayDuration={150}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<UploadPage />} />
          <Route path="/clean" element={<CleanScriptPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/scripts/:scriptId" element={<ScriptViewerPage />} />
        </Route>
      </Routes>
      <Toaster position="top-right" richColors />
    </TooltipProvider>
  );
}