"use client";

import { type ReactElement } from "react";

const SEMI_BOLD_FONT_WEIGHT = 600;

type User = { email: string } | null | undefined;

type AuthenticatedLinksProps = {
  email: string;
  logout: () => void | Promise<void>;
};

function AuthenticatedLinks({ email, logout }: AuthenticatedLinksProps): ReactElement {
  return (
    <>
      <span data-testid="auth-user" style={{ opacity: 0.8 }}>{email}</span>
      <a href="/admin" data-testid="link-admin" style={{ color: "#d8f63a", textDecoration: "none" }}>Admin</a>
      <button
        type="button"
        data-testid="auth-logout"
        onClick={() => logout()}
        style={{ background: "transparent", color: "inherit", border: "1px solid rgba(255,255,255,0.18)", padding: "0.35rem 0.8rem", borderRadius: "999px", cursor: "pointer" }}
      >
        Log out
      </button>
    </>
  );
}

function AnonymousLinks(): ReactElement {
  return (
    <>
      <a href="/pricing" data-testid="link-pricing" style={{ color: "inherit", textDecoration: "none", opacity: 0.85 }}>Pricing</a>
      <a href="/login" data-testid="link-login" style={{ color: "inherit", textDecoration: "none", opacity: 0.85 }}>Log in</a>
      <a href="/signup" data-testid="link-signup" style={{ background: "#d8f63a", color: "#0b1606", textDecoration: "none", padding: "0.35rem 0.9rem", borderRadius: "999px", fontWeight: SEMI_BOLD_FONT_WEIGHT }}>Sign up</a>
    </>
  );
}

function AuthBarContent({ user, logout }: { user: User; logout: () => void | Promise<void> }): ReactElement {
  if (user === undefined) {
    return <span style={{ opacity: 0.5 }}>…</span>;
  }
  if (user) {
    return <AuthenticatedLinks email={user.email} logout={logout} />;
  }
  return <AnonymousLinks />;
}

export function AuthBar({ user, logout }: { user: User; logout: () => void | Promise<void> }) {
  return (
    <div
      className="hnAuthBar"
      data-testid="auth-bar"
      style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem", padding: "0.6rem 1.2rem", fontSize: "0.85rem", alignItems: "center", borderBottom: "1px solid rgba(255,255,255,0.06)" }}
    >
      <AuthBarContent user={user} logout={logout} />
    </div>
  );
}
