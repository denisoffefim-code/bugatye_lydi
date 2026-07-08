import { ArrowRight, Eye, EyeOff, Lock, Mail, UserRound } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { formatApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Logo } from "../components/Logo";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const isRegister = mode === "register";
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || "/app";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      if (isRegister) {
        await register(fullName, email, password);
      } else {
        await login(email, password);
      }
      navigate(redirectTo, { replace: true });
    } catch (error) {
      setFormError(formatApiError(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="authPage">
      <section className="authPanel">
        <div className="authIntro">
          <Logo />
          <h1>{isRegister ? "Создать аккаунт" : "Войти в SkyCast"}</h1>
          {isRegister ? <p>Создайте аккаунт, чтобы начать пользоваться сервисом.</p> : null}
        </div>

        <form className="formStack" onSubmit={handleSubmit}>
          {isRegister ? (
            <label>
              <span>Имя</span>
              <div className="inputShell">
                <UserRound size={18} />
                <input value={fullName} onChange={(event) => setFullName(event.target.value)} required minLength={1} />
              </div>
            </label>
          ) : null}
          <label>
            <span>Электронная почта</span>
            <div className="inputShell">
              <Mail size={18} />
              <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
            </div>
          </label>
          <label>
            <span>Пароль</span>
            <div className="inputShell">
              <Lock size={18} />
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type={passwordVisible ? "text" : "password"}
                minLength={8}
                required
              />
              <button
                className="passwordToggle"
                type="button"
                onClick={() => setPasswordVisible((current) => !current)}
                aria-label={passwordVisible ? "Скрыть пароль" : "Показать пароль"}
                title={passwordVisible ? "Скрыть пароль" : "Показать пароль"}
              >
                {passwordVisible ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>

          {!isRegister ? (
            <button className="textButton alignStart" type="button" onClick={() => setRecoveryOpen((current) => !current)}>
              Забыли пароль?
            </button>
          ) : null}

          {recoveryOpen && !isRegister ? (
            <div className="recoveryBox">
              <strong>Восстановление доступа</strong>
              <span>
                Укажите почту аккаунта и передайте запрос человеку, который выдал вам доступ к SkyCast. Он сможет назначить новый пароль.
              </span>
              <div className="inputShell">
                <Mail size={18} />
                <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="Ваша почта" />
              </div>
            </div>
          ) : null}

          {formError ? <div className="inlineError">{formError}</div> : null}

          <button className="primaryButton fullWidth" type="submit" disabled={submitting}>
            {submitting ? "Проверяем" : isRegister ? "Зарегистрироваться" : "Войти"}
            <ArrowRight size={18} />
          </button>
        </form>

        <p className="authSwitch">
          {isRegister ? "Уже есть аккаунт?" : "Нет аккаунта?"}{" "}
          <Link to={isRegister ? "/login" : "/register"}>{isRegister ? "Войти" : "Зарегистрироваться"}</Link>
        </p>
      </section>
    </main>
  );
}
