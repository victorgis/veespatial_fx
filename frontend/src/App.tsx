import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Gate } from "./pages/gate";
import { Guide } from "./pages/guide";
import { Home } from "./pages/home";
import { SettingsPage } from "./pages/settings";
import { Setup } from "./pages/setup";
import { Journal, SignalDetail, Signals } from "./pages/signals";
import { Shell } from "./shell";
import { NotificationProvider } from "./notifications";

function RequireAuth() {
  const { ready, token } = useAuth();
  if (!ready) return <p className="auth-wrap muted">Loading your desk…</p>;
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}

function RequireSetup() {
  const { me } = useAuth();
  if (!me?.settings.onboarding_done) return <Navigate to="/setup" replace />;
  return <Outlet />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Gate mode="login" />} />
      <Route path="/register" element={<Gate mode="register" />} />
      <Route element={<RequireAuth />}>
        <Route element={<Shell />}>
          <Route path="/setup" element={<Setup />} />
          <Route element={<RequireSetup />}>
            <Route path="/" element={<Home />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/signals/:id" element={<SignalDetail />} />
            <Route path="/journal" element={<Journal />} />
            <Route path="/guide" element={<Guide />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AuthProvider>
      <NotificationProvider>
        <AppRoutes />
      </NotificationProvider>
    </AuthProvider>
  );
}
