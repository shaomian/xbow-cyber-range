import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import MainLayout from "./components/MainLayout";
import LoginPage from "./pages/Login";
import DashboardPage from "./pages/Dashboard";
import BenchmarksPage from "./pages/Benchmarks";
import TemplatesPage from "./pages/Templates";
import InstancesPage from "./pages/Instances";
import InstanceDetailPage from "./pages/InstanceDetail";
import UsersPage from "./pages/Users";
import SettingsPage from "./pages/Settings";
import { getToken, getUser } from "./api/client";

function RequireAuth({ children, adminOnly }: { children: React.ReactNode; adminOnly?: boolean }) {
  const loc = useLocation();
  const token = getToken();
  if (!token) return <Navigate to="/login" state={{ from: loc }} replace />;
  if (adminOnly) {
    const u = getUser();
    if (!u?.is_admin) return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="benchmarks" element={<BenchmarksPage />} />
        <Route path="templates" element={<TemplatesPage />} />
        <Route path="instances" element={<InstancesPage />} />
        <Route path="instances/:id" element={<InstanceDetailPage />} />
        <Route
          path="users"
          element={
            <RequireAuth adminOnly>
              <UsersPage />
            </RequireAuth>
          }
        />
        <Route
          path="settings"
          element={
            <RequireAuth adminOnly>
              <SettingsPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
