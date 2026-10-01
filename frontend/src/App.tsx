// App.tsx : 경로(라우트) 정의. 설계서 5절의 화면 5개를 정해진 경로에 붙인다.
// /projects, /projects/:id/source, /projects/:id/settings, /runs/:runId, /projects/:id/workspace
// 처음 주소(/)와 모르는 주소는 프로젝트 목록으로 보낸다.
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import ProjectsPage from "./pages/ProjectsPage";
import RunPage from "./pages/RunPage";
import SettingsPage from "./pages/SettingsPage";
import SourcePage from "./pages/SourcePage";
import WorkspacePage from "./pages/WorkspacePage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/projects" replace />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:id/source" element={<SourcePage />} />
        <Route path="/projects/:id/settings" element={<SettingsPage />} />
        <Route path="/runs/:runId" element={<RunPage />} />
        <Route path="/projects/:id/workspace" element={<WorkspacePage />} />
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Route>
    </Routes>
  );
}
