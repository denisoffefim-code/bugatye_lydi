import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AppShell, PublicShell } from "./components/Shell";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { AuthPage } from "./pages/AuthPage";
import { ComparePage } from "./pages/ComparePage";
import { DashboardPage } from "./pages/DashboardPage";
import { ForecastsPage } from "./pages/ForecastsPage";
import { LandingPage } from "./pages/LandingPage";
import { ObservationsPage } from "./pages/ObservationsPage";

export function App() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = localStorage.getItem("skycast.theme");
    return stored === "light" || stored === "dark" ? stored : "dark";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("skycast.theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((current) => (current === "dark" ? "light" : "dark"));

  return (
    <Routes>
      <Route element={<PublicShell theme={theme} onToggleTheme={toggleTheme} />}>
        <Route index element={<LandingPage />} />
        <Route path="login" element={<AuthPage mode="login" />} />
        <Route path="register" element={<AuthPage mode="register" />} />
      </Route>

      <Route element={<ProtectedRoute />}>
        <Route path="app" element={<AppShell theme={theme} onToggleTheme={toggleTheme} />}>
          <Route index element={<DashboardPage />} />
          <Route path="forecasts" element={<ForecastsPage />} />
          <Route path="observations" element={<ObservationsPage />} />
          <Route path="compare" element={<ComparePage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
