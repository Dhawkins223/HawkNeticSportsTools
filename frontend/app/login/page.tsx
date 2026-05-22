"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push("/");
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "2rem" }} data-testid="login-page">
      <form onSubmit={onSubmit} style={{ width: "min(420px, 100%)", display: "grid", gap: "1rem", padding: "2rem", borderRadius: "14px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(216,246,58,0.2)" }} data-testid="login-form">
        <div>
          <p style={{ fontSize: "0.7rem", letterSpacing: "0.18em", color: "#d8f63a", margin: 0 }}>HAWKNETICSPORTS</p>
          <h1 style={{ margin: "0.3rem 0 0", fontSize: "1.6rem" }}>Welcome back</h1>
          <p style={{ opacity: 0.65, fontSize: "0.85rem", margin: "0.4rem 0 0" }}>Log in to run the algorithm and save slips.</p>
        </div>
        <label style={{ display: "grid", gap: "0.4rem", fontSize: "0.85rem" }}>
          Email
          <input data-testid="login-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} style={{ padding: "0.7rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.4)", color: "inherit" }} />
        </label>
        <label style={{ display: "grid", gap: "0.4rem", fontSize: "0.85rem" }}>
          Password
          <input data-testid="login-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} style={{ padding: "0.7rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.4)", color: "inherit" }} />
        </label>
        {err && <div data-testid="login-error" style={{ color: "#ff6e6e", fontSize: "0.85rem" }}>{err}</div>}
        <button data-testid="login-submit" disabled={busy} type="submit" style={{ padding: "0.8rem 1rem", borderRadius: "999px", border: "none", background: "#d8f63a", color: "#0b1606", fontWeight: 700, cursor: busy ? "not-allowed" : "pointer" }}>
          {busy ? "Signing in…" : "Log in"}
        </button>
        <p style={{ textAlign: "center", fontSize: "0.85rem", margin: 0, opacity: 0.75 }}>
          New here? <a href="/signup" data-testid="link-signup" style={{ color: "#d8f63a" }}>Create an account</a>
        </p>
      </form>
    </main>
  );
}
