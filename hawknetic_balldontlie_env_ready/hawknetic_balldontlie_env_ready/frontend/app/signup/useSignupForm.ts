"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export function useSignupForm() {
  const router = useRouter();
  const { signup } = useAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>): Promise<void> {
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

  return { fullName, setFullName, email, setEmail, password, setPassword, err, busy, onSubmit };
}
