import "@fontsource-variable/inter";
import "./index.css";
import { lazy, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout, Logo } from "./components/Layout";
import { AuthProvider, DatasetProvider, ToastProvider, useAuth } from "./lib/context";
import { ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage } from "./pages/Auth";

const OverviewPage = lazy(() => import("./pages/Overview"));
const DatasetsPage = lazy(() => import("./pages/Datasets"));
const ExplorerPage = lazy(() => import("./pages/Explorer"));
const CleaningPage = lazy(() => import("./pages/Cleaning"));
const AnalystPage = lazy(() => import("./pages/Analyst"));
const VisualisationsPage = lazy(() => import("./pages/Visualisations"));
const AnomaliesPage = lazy(() => import("./pages/Anomalies"));
const ReportsPage = lazy(() => import("./pages/Reports"));
const ReportDetailPage = lazy(() => import("./pages/ReportDetail"));
const ConnectionsPage = lazy(() => import("./pages/Connections"));
const SettingsPage = lazy(() => import("./pages/Settings"));

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center" aria-label="Loading"><div className="animate-shimmer"><Logo /></div></div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Navigate to="/" replace /> : <>{children}</>;
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
      <Route path="/forgot-password" element={<PublicOnly><ForgotPasswordPage /></PublicOnly>} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route element={<Protected><DatasetProvider><Layout /></DatasetProvider></Protected>}>
        <Route index element={<OverviewPage />} />
        <Route path="datasets" element={<DatasetsPage />} />
        <Route path="explorer" element={<ExplorerPage />} />
        <Route path="cleaning" element={<CleaningPage />} />
        <Route path="analyst" element={<AnalystPage />} />
        <Route path="visualisations" element={<VisualisationsPage />} />
        <Route path="anomalies" element={<AnomaliesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/:reportId" element={<ReportDetailPage />} />
        <Route path="connections" element={<ConnectionsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
);
