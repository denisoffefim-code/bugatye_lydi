import {
  Activity,
  BarChart3,
  CloudSun,
  GitCompareArrows,
  Home,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Sun,
  ThermometerSun,
  X
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isPrivilegedRole, roleLabel } from "../utils";
import { Logo } from "./Logo";

const navItems = [
  { to: "/app", label: "Кабинет", icon: LayoutDashboard, end: true },
  { to: "/app/forecasts", label: "Прогнозы", icon: CloudSun },
  { to: "/app/observations", label: "Фактические данные", icon: ThermometerSun },
  { to: "/app/compare", label: "Разбор станции", icon: GitCompareArrows },
  { to: "/app/analytics", label: "Аналитика", icon: BarChart3 }
];

export function PublicShell({
  theme,
  onToggleTheme
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  return (
    <div className="publicFrame">
      <header className="topbar publicTopbar">
        <NavLink to="/" className="plainLink">
          <Logo />
        </NavLink>
        <nav className="publicNav" aria-label="Главная навигация">
          <a href="/#features">Возможности</a>
          <a href="/#how">Как работает</a>
        </nav>
        <div className="topbarActions">
          <button className="iconButton" type="button" onClick={onToggleTheme} aria-label="Переключить тему">
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <NavLink className="ghostButton" to="/login">
            Войти
          </NavLink>
          <NavLink className="primaryButton" to="/register">
            Регистрация
          </NavLink>
        </div>
      </header>
      <Outlet />
    </div>
  );
}

export function AppShell({
  theme,
  onToggleTheme
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const showRole = isPrivilegedRole(user?.role);

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  return (
    <div className="appFrame">
      <aside className={`sidebar ${mobileOpen ? "open" : ""}`}>
        <div className="sidebarHeader">
          <Logo />
          <button className="iconButton mobileOnly" type="button" onClick={() => setMobileOpen(false)} aria-label="Закрыть меню">
            <X size={18} />
          </button>
        </div>
        <nav className="sideNav" aria-label="Разделы SkyCast">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setMobileOpen(false)}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebarFooter">
          <div className="userMini">
            <strong>{user?.full_name || "Пользователь"}</strong>
            <span>{showRole ? roleLabel(user?.role) : user?.email || "Личный кабинет"}</span>
          </div>
          <button className="ghostButton fullWidth" type="button" onClick={handleLogout}>
            <LogOut size={17} />
            Выйти
          </button>
        </div>
      </aside>

      <div className="mainColumn">
        <header className="topbar appTopbar">
          <button className="iconButton mobileOnly" type="button" onClick={() => setMobileOpen(true)} aria-label="Открыть меню">
            <Menu size={19} />
          </button>
          <div className="topbarSummary">
            <Activity size={18} />
            <span>Аналитика факта и прогноза</span>
          </div>
          <div className="topbarActions">
            <NavLink className="ghostButton desktopOnly" to="/">
              <Home size={17} />
              На сайт
            </NavLink>
            <button className="iconButton" type="button" onClick={onToggleTheme} aria-label="Переключить тему">
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
