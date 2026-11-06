import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Logo } from "../components/Layout";
import { Button, ErrorNote, Field, Notice } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useToast } from "../lib/context";
import type { User } from "../lib/types";

function Shell({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-5 flex justify-center"><Logo /></div>
        <div className="rounded-lg border border-line bg-surface p-5 shadow-card">
          <h1 className="text-base font-semibold">{title}</h1>
          {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
          <div className="mt-4">{children}</div>
        </div>
        {footer && <p className="mt-4 text-center text-[13px] text-muted">{footer}</p>}
      </div>
    </div>
  );
}

const linkClass = "font-medium text-blue-300 hover:underline";

export function LoginPage() {
  const { setUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setUser(await api.post<User>("/auth/login", { email, password }));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Sign in" subtitle="Continue to your analytics workspace." footer={<>New to DataForge AI? <Link className={linkClass} to="/register">Create an account</Link></>}>
      <form onSubmit={submit} className="space-y-3">
        {error && <ErrorNote message={error} />}
        <Field label="Email"><input className="field" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input className="field" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <div className="text-right"><Link className="text-xs text-muted hover:text-ink" to="/forgot-password">Forgot password?</Link></div>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>Sign in</Button>
      </form>
    </Shell>
  );
}

export function RegisterPage() {
  const { setUser } = useAuth();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setUser(await api.post<User>("/auth/register", form));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Create your account" subtitle="A private workspace is created for you." footer={<>Already registered? <Link className={linkClass} to="/login">Sign in</Link></>}>
      <form onSubmit={submit} className="space-y-3">
        {error && <ErrorNote message={error} />}
        <Field label="Full name"><input className="field" autoComplete="name" required maxLength={200} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
        <Field label="Email"><input className="field" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
        <Field label="Password" hint="At least 10 characters, mixing letters with numbers or symbols."><input className="field" type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>Create account</Button>
      </form>
    </Shell>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ message: string; dev_reset_link?: string; dev_note?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post("/auth/password-reset/request", { email }));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const devPath = result?.dev_reset_link ? new URL(result.dev_reset_link).pathname + new URL(result.dev_reset_link).search : null;
  return (
    <Shell title="Reset your password" subtitle="Enter your email to receive a reset link." footer={<Link className={linkClass} to="/login">Back to sign in</Link>}>
      {result ? (
        <div className="space-y-3">
          <Notice>{result.message}</Notice>
          {devPath && <Notice tone="warn">Development mode has no email service, so the link is shown here: <Link className="underline" to={devPath}>Reset password</Link></Notice>}
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          {error && <ErrorNote message={error} />}
          <Field label="Email"><input className="field" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
    </Shell>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/password-reset/confirm", { token: params.get("token") ?? "", new_password: password });
      toast("Password updated. Sign in with your new password.");
      navigate("/login");
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Choose a new password" footer={<Link className={linkClass} to="/login">Back to sign in</Link>}>
      <form onSubmit={submit} className="space-y-3">
        {error && <ErrorNote message={error} />}
        <Field label="New password" hint="At least 10 characters, mixing letters with numbers or symbols."><input className="field" type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <Button type="submit" variant="primary" className="w-full" loading={busy}>Update password</Button>
      </form>
    </Shell>
  );
}
