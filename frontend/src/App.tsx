import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./layouts/AppLayout";
import { OverviewPage } from "./pages/OverviewPage";
import { SetupPage } from "./pages/SetupPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { NewReviewPage } from "./pages/NewReviewPage";
import { PreviewPage } from "./pages/PreviewPage";
import { QueuePage } from "./pages/QueuePage";
import { JobLivePage } from "./pages/JobLivePage";
import { ReviewHistoryPage } from "./pages/ReviewHistoryPage";
import { ResultPage } from "./pages/ResultPage";
import { SessionPage } from "./pages/SessionPage";
import { JobLogsPage } from "./pages/JobLogsPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { ProviderEditorPage } from "./pages/ProviderEditorPage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { McpPage } from "./pages/McpPage";
import { DocsPage } from "./pages/DocsPage";
import { WebhooksPage } from "./pages/WebhooksPage";
import { DeliveriesPage } from "./pages/DeliveriesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="setup" element={<SetupPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="reviews/new" element={<NewReviewPage />} />
        <Route path="reviews/preview" element={<PreviewPage />} />
        <Route path="reviews/:jobId" element={<ResultPage />} />
          <Route path="reviews/:jobId/session" element={<SessionPage />} />
          <Route path="reviews/:jobId/logs" element={<JobLogsPage />} />
        <Route path="reviews" element={<ReviewHistoryPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="jobs/:jobId" element={<JobLivePage />} />
        <Route path="providers" element={<ProvidersPage />} />
        <Route path="providers/new" element={<ProviderEditorPage />} />
        <Route path="providers/:providerId" element={<ProviderEditorPage />} />
        <Route path="profiles" element={<ProfilesPage />} />
        <Route path="profiles/:profileId" element={<ProfilesPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="integrations/webhooks" element={<WebhooksPage />} />
        <Route path="integrations/deliveries" element={<DeliveriesPage />} />
        <Route path="mcp" element={<McpPage />} />
        <Route path="docs" element={<DocsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="diagnostics" element={<DiagnosticsPage />} />
        <Route path="404" element={<NotFoundPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/404" replace />} />
    </Routes>
  );
}
