import {
  BrowserRouter,
  NavLink,
  Routes,
  Route,
  Link,
  Navigate,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { Suspense, lazy, useEffect, useState } from "react";
import { apiFetch } from "../shared/api/auth";
import { AuthSessionProvider, useAuthSession } from "../shared/auth/AuthSession";
import eyePasswordHideIcon from "../shared/icons/eye-password-hide.svg";
import eyePasswordShowIcon from "../shared/icons/eye-password-show.svg";

const Home = lazy(() => import("../pages/Home/Home"));
const MapAnalytics = lazy(() => import("../pages/MapAnalytics/MapAnalytics"));
const Login = lazy(() => import("../pages/Login/Login"));
const Library = lazy(() => import("../pages/Library/Library"));
const ScienceCabinet = lazy(() => import("../pages/ScienceCabinet/ScienceCabinet"));
const Admin = lazy(() => import("../pages/Admin/Admin"));

function HeaderLink({ to, children }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "active" : "")}>
      {children}
    </NavLink>
  );
}

function AuthLoadingScreen() {
  return (
    <div className="auth-loader-page">
      <div className="card auth-loader-card">
        <div className="auth-loader-spinner" aria-hidden="true" />
        <div className="auth-loader-text">Проверяем доступ к разделу...</div>
      </div>
    </div>
  );
}

function PageLoadingScreen() {
  return (
    <div className="auth-loader-page">
      <div className="card auth-loader-card">
        <div className="auth-loader-spinner" aria-hidden="true" />
        <div className="auth-loader-text">Загружаем раздел...</div>
      </div>
    </div>
  );
}

function ProtectedRoute({ roles, children }) {
  const { user, loading } = useAuthSession();
  const location = useLocation();

  if (loading) {
    return <AuthLoadingScreen />;
  }

  const hasAccess = user && (!roles?.length || roles.includes(user.role));
  if (!hasAccess) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location, reason: user ? "forbidden" : "auth" }}
      />
    );
  }

  return children;
}

function AppFrame() {
  const { user, loading, logout } = useAuthSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [showPasswords, setShowPasswords] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState("");
  const [passwordMessageType, setPasswordMessageType] = useState("neutral");
  const [isPasswordSaving, setIsPasswordSaving] = useState(false);
  const isMapPage = location.pathname === "/map";
  const canSeeScience = user && (user.role === "scientist" || user.role === "admin");
  const canSeeAdmin = user?.role === "admin";
  const passwordToggleLabel = showPasswords ? "Скрыть пароль" : "Показать пароль";

  useEffect(() => {
    if (!isPasswordModalOpen) {
      return undefined;
    }

    function handleKeyDown(event) {
      if (event.key === "Escape" && !isPasswordSaving) {
        setIsPasswordModalOpen(false);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isPasswordModalOpen, isPasswordSaving]);

  function resetPasswordModal() {
    setCurrentPassword("");
    setNewPassword("");
    setNewPasswordConfirm("");
    setShowPasswords(false);
    setPasswordMessage("");
    setPasswordMessageType("neutral");
    setIsPasswordSaving(false);
  }

  function openPasswordModal() {
    resetPasswordModal();
    setIsPasswordModalOpen(true);
  }

  function closePasswordModal() {
    if (isPasswordSaving) return;
    setIsPasswordModalOpen(false);
    resetPasswordModal();
  }

  async function handlePasswordSubmit(event) {
    event.preventDefault();
    setPasswordMessage("");
    setPasswordMessageType("neutral");

    if (newPassword !== newPasswordConfirm) {
      setPasswordMessageType("error");
      setPasswordMessage("Ошибка: новые пароли не совпадают.");
      return;
    }

    setIsPasswordSaving(true);
    try {
      await apiFetch("/api/v1/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      setPasswordMessageType("success");
      setPasswordMessage("Пароль изменён.");
      window.setTimeout(() => {
        setIsPasswordModalOpen(false);
        resetPasswordModal();
      }, 700);
    } catch (error) {
      setPasswordMessageType("error");
      setPasswordMessage(`Ошибка: ${error?.message || String(error)}`);
    } finally {
      setIsPasswordSaving(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="site-header-inner">
          <div className="brand">
            <div className="brand-badge">🌿</div>
            <div className="brand-text">
              <h1 className="brand-title">
                <Link to="/">EcoPollen</Link>
              </h1>
              <p className="brand-subtitle">Мониторинг пыльцы и поиск научных публикаций по аллергенам</p>
            </div>
          </div>

          <div className="site-header-actions">
            <nav className="site-nav">
              <HeaderLink to="/">Главная</HeaderLink>
              <HeaderLink to="/map">Карта</HeaderLink>
              <HeaderLink to="/library">Библиотека</HeaderLink>
              {!loading && canSeeScience ? <HeaderLink to="/science">Кабинет</HeaderLink> : null}
              {!loading && canSeeAdmin ? <HeaderLink to="/admin">Админ</HeaderLink> : null}
              {!loading && !user ? <HeaderLink to="/login">Вход</HeaderLink> : null}
            </nav>

            {!loading && user ? (
              <div className="site-auth">
                <button
                  type="button"
                  className="secondary site-user-pill site-user-trigger"
                  onClick={openPasswordModal}
                  title="Изменить пароль"
                >
                  {user.email}
                </button>
                <button
                  type="button"
                  className="secondary site-auth-button"
                  onClick={() => {
                    logout();
                    navigate("/login", { replace: true });
                  }}
                >
                  Выйти
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="page-main">
        <div className={isMapPage ? "page-container page-container-fluid" : "page-container"}>
          <Suspense fallback={<PageLoadingScreen />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/map" element={<MapAnalytics />} />
              <Route
                path="/library"
                element={
                  <ProtectedRoute>
                    <Library />
                  </ProtectedRoute>
                }
              />
              <Route path="/login" element={<Login />} />
              <Route
                path="/science"
                element={
                  <ProtectedRoute roles={["scientist", "admin"]}>
                    <ScienceCabinet />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute roles={["admin"]}>
                    <Admin />
                  </ProtectedRoute>
                }
              />
            </Routes>
          </Suspense>
        </div>
      </main>

      <footer className="site-footer">
        <div className="site-footer-inner">
          <div className="site-footer-contact">
            <span>По всем вопросам: </span>
            <a href="mailto:tvgoroshenkin@edu.hse.ru">tvgoroshenkin@edu.hse.ru</a>
          </div>
          <div className="site-footer-copy">© EcoPollen, 2026</div>
        </div>
      </footer>

      {isPasswordModalOpen ? (
        <div className="account-modal-backdrop" onClick={closePasswordModal}>
          <div
            className="card account-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="account-password-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="account-modal-head">
              <div>
                <h3 id="account-password-title" className="account-modal-title">
                  Изменить пароль
                </h3>
                <p className="account-modal-copy">{user?.email}</p>
              </div>
              <button
                type="button"
                className="secondary account-modal-close"
                onClick={closePasswordModal}
              >
                Закрыть
              </button>
            </div>

            <form className="account-password-form" onSubmit={handlePasswordSubmit}>
              <label className="account-password-field">
                <span>Текущий пароль</span>
                <div className="account-password-row">
                  <input
                    type={showPasswords ? "text" : "password"}
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    className="secondary account-password-toggle"
                    onClick={() => setShowPasswords((prev) => !prev)}
                    aria-label={passwordToggleLabel}
                    title={passwordToggleLabel}
                    aria-pressed={showPasswords}
                  >
                    <img
                      src={showPasswords ? eyePasswordHideIcon : eyePasswordShowIcon}
                      alt=""
                      aria-hidden="true"
                    />
                  </button>
                </div>
              </label>

              <label className="account-password-field">
                <span>Новый пароль</span>
                <div className="account-password-row">
                  <input
                    type={showPasswords ? "text" : "password"}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="secondary account-password-toggle"
                    onClick={() => setShowPasswords((prev) => !prev)}
                    aria-label={passwordToggleLabel}
                    title={passwordToggleLabel}
                    aria-pressed={showPasswords}
                  >
                    <img
                      src={showPasswords ? eyePasswordHideIcon : eyePasswordShowIcon}
                      alt=""
                      aria-hidden="true"
                    />
                  </button>
                </div>
              </label>

              <label className="account-password-field">
                <span>Повторите новый пароль</span>
                <div className="account-password-row">
                  <input
                    type={showPasswords ? "text" : "password"}
                    value={newPasswordConfirm}
                    onChange={(event) => setNewPasswordConfirm(event.target.value)}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="secondary account-password-toggle"
                    onClick={() => setShowPasswords((prev) => !prev)}
                    aria-label={passwordToggleLabel}
                    title={passwordToggleLabel}
                    aria-pressed={showPasswords}
                  >
                    <img
                      src={showPasswords ? eyePasswordHideIcon : eyePasswordShowIcon}
                      alt=""
                      aria-hidden="true"
                    />
                  </button>
                </div>
              </label>

              {passwordMessage ? (
                <div className={`note account-password-message account-password-message-${passwordMessageType}`}>
                  {passwordMessage}
                </div>
              ) : null}

              <div className="account-modal-actions">
                <button type="button" className="secondary" onClick={closePasswordModal}>
                  Отмена
                </button>
                <button type="submit" disabled={isPasswordSaving}>
                  {isPasswordSaving ? "Сохраняем..." : "Сохранить пароль"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function App() {
  return (
    <AuthSessionProvider>
      <BrowserRouter>
        <AppFrame />
      </BrowserRouter>
    </AuthSessionProvider>
  );
}
