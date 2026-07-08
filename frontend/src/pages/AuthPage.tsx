import { ArrowRight, Lock, Mail, UserRound } from "lucide-react";
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
          <p>
            {isRegister
              ? "После регистрации будет создан viewer-аккаунт с доступом к аналитическим разделам."
              : "Используйте учетную запись SkyCast для доступа к личному кабинету и аналитике."}
          </p>
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
            <span>Email</span>
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
                type="password"
                minLength={8}
                required
              />
            </div>
          </label>

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
