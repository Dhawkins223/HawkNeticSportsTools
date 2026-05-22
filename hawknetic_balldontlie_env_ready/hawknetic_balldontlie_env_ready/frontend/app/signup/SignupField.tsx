"use client";

import type { ReactElement, ReactNode } from "react";

export const SIGNUP_INPUT_STYLE = {
  padding: "0.7rem 0.9rem",
  borderRadius: "8px",
  border: "1px solid rgba(255,255,255,0.18)",
  background: "rgba(0,0,0,0.4)",
  color: "inherit",
};

type Props = {
  label: ReactNode;
  testid: string;
  type?: "text" | "email" | "password";
  minLength?: number;
  value: string;
  onChange: (value: string) => void;
};

export function SignupField({ label, testid, type = "text", minLength, value, onChange }: Props): ReactElement {
  return (
    <label style={{ display: "grid", gap: "0.4rem", fontSize: "0.85rem" }}>
      {label}
      <input
        data-testid={testid}
        type={type}
        minLength={minLength}
        required
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={SIGNUP_INPUT_STYLE}
      />
    </label>
  );
}
