import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { desk } from "../api";
import { useAuth } from "../auth";

export function Gate({ mode }: { mode: "login" | "register" }) {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result =
        mode === "login" ? await desk.login(email, password) : await desk.register(email, name, password);
      await signIn(result.token);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-wrap">
      <p className="steps">Signal Desk</p>
      <h1>{mode === "login" ? "Welcome back" : "Open your desk"}</h1>
      <p className="lede">
        One set of signals for currencies, gold, WTI cash, and Brent cash. Each person chooses automatic orders or
        signals they place themselves.
      </p>
      <form onSubmit={onSubmit} style={{ marginTop: 22 }}>
        {mode === "register" ? (
          <label className="field">
            <span>Your name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
          </label>
        ) : null}
        <label className="field">
          <span>Email</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="email" required />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={8}
            required
          />
        </label>
        {error ? <p className="error">{error}</p> : null}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
      <p className="muted" style={{ marginTop: 18 }}>
        {mode === "login" ? (
          <>New here? <Link to="/register">Create an account</Link></>
        ) : (
          <>Already have a desk? <Link to="/login">Sign in</Link></>
        )}
      </p>
    </main>
  );
}
