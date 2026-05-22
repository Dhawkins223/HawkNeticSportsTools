"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const FORM_MAX_WIDTH = 440;

export default function SignupPage() {
  const router = useRouter();
  const { signup } = useAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await signup(email, password, fullName);
      router.push("/");
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Signup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "2rem" }} data-testid="signup-page">
      <form onSubmit={onSubmit} style={{ width: `min(${FORM_MAX_WIDTH}px, 100%)`, display: "grid", gap: "1rem", padding: "2rem", borderRadius: "14px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(216,246,58,0.2)" }} data-testid="signup-form">
        <div>
          <p style={{ fontSize: "0.7rem", letterSpacing: "0.18em", color: "#d8f63a", margin: 0 }}>HAWKNETICSPORTS</p>
          <h1 style={{ margin: "0.3rem 0 0", fontSize: "1.6rem" }}>Create your account</h1>
          <p style={{ opacity: 0.65, fontSize: "0.85rem", margin: "0.4rem 0 0" }}>HawkneticSports provides decision support for sports betting. We do not accept wagers.</p>
        </div>
        <label style={{ display: "grid", gap: "0.4rem", fontSize: "0.85rem" }}>
          Full name
          <input data-testid="signup-name" required value={fullName} onChange={(e) => setFullName(e.target.value)} style={{ padding: "0.7rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.4)", color: "inherit" }} />
        </label>
        <label style={{ display: "grid", gap: "0.4rem", fontSize: "0.85rem" }}>
          Email
          <input data-testid="signup-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} style={{ padding: "0.7rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.4)", color: "inherit" }} />
        </label>
        <label style={{ display: "grid", gap: "0.4rem", fontSize: "0.85rem" }}>
          Password (min 6)
          <input data-testid="signup-password" type="password" minLength={6} required value={password} onChange={(e) => setPassword(e.target.value)} style={{ padding: "0.7rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.18)", background: "rgba(0,0,0,0.4)", color: "inherit" }} />
        </label>
        {err && <div data-testid="signup-error" style={{ color: "#ff6e6e", fontSize: "0.85rem" }}>{err}</div>}
        <button data-testid="signup-submit" disabled={busy} type="submit" style={{ padding: "0.8rem 1rem", borderRadius: "999px", border: "none", background: "#d8f63a", color: "#0b1606", fontWeight: 700, cursor: busy ? "not-allowed" : "pointer" }}>
          {busy ? "Creating…" : "Create account"}
        </button>
        <p style={{ textAlign: "center", fontSize: "0.85rem", margin: 0, opacity: 0.75 }}>
          Already have an account? <a href="/login" data-testid="link-login" style={{ color: "#d8f63a" }}>Log in</a>
        </p>
      </form>
    </main>
  );
}
