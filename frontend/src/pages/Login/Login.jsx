import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { apiFetch, setToken } from "../../shared/api/auth";
import { useAuthSession } from "../../shared/auth/AuthSession";
import eyePasswordHideIcon from "../../shared/icons/eye-password-hide.svg";
import eyePasswordShowIcon from "../../shared/icons/eye-password-show.svg";
import { resolveRequestedPath } from "./loginUtils";
import "./Login.css";

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshSession } = useAuthSession();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [msg, setMsg] = useState("");
  const [msgType, setMsgType] = useState("neutral");
  const [loading, setLoading] = useState(false);
  const passwordToggleLabel = showPassword ? "Скрыть пароль" : "Показать пароль";
  const authGuardMessage =
    location.state?.reason === "forbidden"
      ? "У текущей учётной записи нет доступа к этому разделу. Войдите под другой ролью."
      : location.state?.reason === "auth"
        ? "Для доступа к этому разделу нужно войти."
        : "";

  async function requestLoginToken(nextEmail, nextPassword) {
    const form = new URLSearchParams();
    form.set("username", nextEmail.trim());
    form.set("password", nextPassword);

    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data?.detail || "не удалось войти");
    }
    return data;
  }

  function switchMode(nextMode) {
    setMode(nextMode);
    setMsg("");
    setMsgType("neutral");
    setPassword("");
    setPasswordConfirm("");
  }

  async function onSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setMsgType("neutral");

    try {
      if (mode === "register") {
        if (password !== passwordConfirm) {
          setMsgType("error");
          setMsg("Ошибка: пароли не совпадают.");
          return;
        }

        setMsg("Создаём аккаунт...");
        await apiFetch("/api/v1/auth/register", {
          method: "POST",
          body: JSON.stringify({
            email: email.trim(),
            password,
          }),
        });
      } else {
        setMsg("Проверяем логин и пароль...");
      }

      const data = await requestLoginToken(email, password);
      setToken(data.access_token);
      const me = (await refreshSession()) || (await apiFetch("/api/v1/auth/me"));
      const target = resolveRequestedPath(me?.role, location.state?.from?.pathname);
      setMsgType("success");
      setMsg(
        mode === "register"
          ? "Аккаунт создан. Перенаправляем в рабочий раздел..."
          : "Вход выполнен. Перенаправляем в рабочий раздел..."
      );
      window.setTimeout(() => {
        navigate(target, { replace: true });
      }, 250);
    } catch (error) {
      setMsgType("error");
      setMsg(`Ошибка: ${error?.message || String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-shell">
        <div className="card login-intro-card">
          <h2 className="login-title">
            {mode === "register" ? "Регистрация" : "Вход в систему"}
          </h2>
          <p className="login-copy">
            {mode === "register"
              ? "Зарегистрируйтесь, чтобы получить доступ к библиотеке."
              : "Авторизуйтесь, чтобы получить доступ к библиотеке."}
          </p>
        </div>

        <div className="card login-card">
          <div className="login-card-head">
            {authGuardMessage ? <div className="note login-guard-note">{authGuardMessage}</div> : null}
            <div className="login-mode-switch" role="tablist" aria-label="Режим авторизации">
              <button
                type="button"
                className={mode === "login" ? "login-mode-button active" : "login-mode-button"}
                onClick={() => switchMode("login")}
              >
                Вход
              </button>
              <button
                type="button"
                className={
                  mode === "register" ? "login-mode-button active" : "login-mode-button"
                }
                onClick={() => switchMode("register")}
              >
                Регистрация
              </button>
            </div>

            <h3 className="login-card-title">
              {mode === "register" ? "Создание аккаунта" : "Авторизация"}
            </h3>
            <p className="login-card-copy">
              {mode === "register"
                ? "Укажите email и пароль. Новый аккаунт создаётся с ролью student."
                : "Используйте ваш логин и пароль для входа в EcoPollen."}
            </p>
          </div>

          <form onSubmit={onSubmit} className="grid login-form">
            <label className="login-field">
              <span>Логин</span>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                autoComplete="username"
              />
            </label>

            <label className="login-field">
              <span>Пароль</span>
              <div className="login-password-row">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                />
                <button
                  type="button"
                  className="login-password-toggle"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={passwordToggleLabel}
                  title={passwordToggleLabel}
                  aria-pressed={showPassword}
                >
                  <img
                    src={showPassword ? eyePasswordHideIcon : eyePasswordShowIcon}
                    alt=""
                    aria-hidden="true"
                  />
                </button>
              </div>
            </label>

            {mode === "register" ? (
              <label className="login-field">
                <span>Повторите пароль</span>
                <div className="login-password-row">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={passwordConfirm}
                    onChange={(e) => setPasswordConfirm(e.target.value)}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="login-password-toggle"
                    onClick={() => setShowPassword((prev) => !prev)}
                    aria-label={passwordToggleLabel}
                    title={passwordToggleLabel}
                    aria-pressed={showPassword}
                  >
                    <img
                      src={showPassword ? eyePasswordHideIcon : eyePasswordShowIcon}
                      alt=""
                      aria-hidden="true"
                    />
                  </button>
                </div>
              </label>
            ) : null}

            <button type="submit" disabled={loading}>
              {loading
                ? mode === "register"
                  ? "Регистрируем..."
                  : "Входим..."
                : mode === "register"
                  ? "Зарегистрироваться"
                  : "Войти"}
            </button>

            {msg ? (
              <div className={`note login-message login-message-${msgType}`}>
                {msg}
              </div>
            ) : null}
          </form>
        </div>
      </div>
    </div>
  );
}
