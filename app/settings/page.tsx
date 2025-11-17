"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";

interface User {
  id: number;
  email: string;
  name: string | null;
  createdAt?: string;
}

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  
  // Profile form state
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  
  // Password form state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  // LLM settings state
  const [llmProvider, setLlmProvider] = useState<string>("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [isSavingLlm, setIsSavingLlm] = useState(false);
  const [hasApiKey, setHasApiKey] = useState(false);

  useEffect(() => {
    fetchUser();
    fetchLlmSettings();
  }, []);

  const fetchLlmSettings = async () => {
    try {
      const response = await fetch("/api/auth/llm");
      if (response.ok) {
        const data = await response.json();
        setLlmProvider(data.provider || "");
        setLlmModel(data.model || "");
        setHasApiKey(data.hasApiKey || false);
      }
    } catch (error) {
      console.error("Failed to fetch LLM settings:", error);
    }
  };

  const fetchUser = async () => {
    try {
      const response = await fetch("/api/auth/me");
      if (response.ok) {
        const data = await response.json();
        setUser(data.user);
        setName(data.user.name || "");
        setEmail(data.user.email || "");
      } else {
        router.push("/login");
      }
    } catch (error) {
      console.error("Failed to fetch user:", error);
      router.push("/login");
    } finally {
      setIsLoading(false);
    }
  };

  const handleProfileUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingProfile(true);

    try {
      const response = await fetch("/api/auth/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to update profile");
      }

      toast.success("Profile updated successfully!");
      setUser(data.user);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to update profile");
    } finally {
      setIsSavingProfile(false);
    }
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();

    if (newPassword !== confirmPassword) {
      toast.error("New passwords do not match");
      return;
    }

    if (newPassword.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }

    setIsChangingPassword(true);

    try {
      const response = await fetch("/api/auth/password", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currentPassword, newPassword }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to change password");
      }

      toast.success("Password changed successfully!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to change password");
    } finally {
      setIsChangingPassword(false);
    }
  };

  const handleLlmUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingLlm(true);

    try {
      const response = await fetch("/api/auth/llm", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: llmProvider || null,
          apiKey: llmApiKey || null,
          model: llmModel || null,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to update LLM settings");
      }

      toast.success("LLM settings updated successfully!");
      setLlmApiKey(""); // Clear the API key field after saving
      setHasApiKey(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to update LLM settings");
    } finally {
      setIsSavingLlm(false);
    }
  };

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      toast.success("Logged out successfully");
      router.push("/login");
    } catch (error) {
      toast.error("Failed to logout");
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-textSecondary">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6">
      <div className="card p-6">
        <h2 className="text-2xl font-bold text-text mb-6">Settings</h2>

        {/* Profile Settings */}
        <section className="mb-8">
          <h3 className="text-xl font-semibold text-text mb-4">Profile Information</h3>
          <form onSubmit={handleProfileUpdate} className="space-y-4">
            <div>
              <label htmlFor="name" className="block text-sm font-semibold text-text mb-2">
                Full Name
              </label>
              <input
                id="name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                placeholder="Enter your full name"
              />
            </div>

            <div>
              <label htmlFor="email" className="block text-sm font-semibold text-text mb-2">
                Email Address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                placeholder="Enter your email"
              />
            </div>

            <button
              type="submit"
              disabled={isSavingProfile}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSavingProfile ? "Saving..." : "Save Changes"}
            </button>
          </form>
        </section>

        {/* Password Change */}
        <section className="mb-8">
          <h3 className="text-xl font-semibold text-text mb-4">Change Password</h3>
          <form onSubmit={handlePasswordChange} className="space-y-4">
            <div>
              <label htmlFor="currentPassword" className="block text-sm font-semibold text-text mb-2">
                Current Password
              </label>
              <input
                id="currentPassword"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                placeholder="Enter current password"
              />
            </div>

            <div>
              <label htmlFor="newPassword" className="block text-sm font-semibold text-text mb-2">
                New Password
              </label>
              <input
                id="newPassword"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                placeholder="Enter new password (min. 8 characters)"
              />
            </div>

            <div>
              <label htmlFor="confirmPassword" className="block text-sm font-semibold text-text mb-2">
                Confirm New Password
              </label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={8}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                placeholder="Confirm new password"
              />
            </div>

            <button
              type="submit"
              disabled={isChangingPassword}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isChangingPassword ? "Changing..." : "Change Password"}
            </button>
          </form>
        </section>

        {/* LLM Settings */}
        <section className="mb-8">
          <h3 className="text-xl font-semibold text-text mb-4">AI Chat Settings</h3>
          <form onSubmit={handleLlmUpdate} className="space-y-4">
            <div className="p-4 bg-surface2 border border-border rounded-lg mb-4">
              <p className="text-sm text-textSecondary mb-2">
                Connect your own LLM API key to use third-party AI services. Your API key is stored securely and only used for your chat sessions.
              </p>
              {hasApiKey && (
                <p className="text-sm text-accent font-semibold">
                  ✓ API key is configured
                </p>
              )}
            </div>

            <div>
              <label htmlFor="llmProvider" className="block text-sm font-semibold text-text mb-2">
                LLM Provider
              </label>
              <select
                id="llmProvider"
                value={llmProvider}
                onChange={(e) => {
                  setLlmProvider(e.target.value);
                  // Set default model based on provider
                  if (e.target.value === "openai") {
                    setLlmModel("gpt-4o-mini");
                  } else if (e.target.value === "anthropic") {
                    setLlmModel("claude-3-haiku-20240307");
                  } else if (e.target.value === "google") {
                    setLlmModel("gemini-pro");
                  }
                }}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
              >
                <option value="">Use default (OpenAI)</option>
                <option value="openai">OpenAI (GPT-4, GPT-3.5)</option>
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="google">Google (Gemini)</option>
              </select>
            </div>

            {llmProvider && (
              <div>
                <label htmlFor="llmModel" className="block text-sm font-semibold text-text mb-2">
                  Model
                </label>
                <input
                  id="llmModel"
                  type="text"
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                  placeholder={
                    llmProvider === "openai"
                      ? "e.g., gpt-4o-mini, gpt-4, gpt-3.5-turbo"
                      : llmProvider === "anthropic"
                      ? "e.g., claude-3-haiku-20240307, claude-3-opus-20240229"
                      : "e.g., gemini-pro, gemini-pro-vision"
                  }
                />
                <p className="text-xs text-textSecondary mt-1">
                  Leave empty to use default model for selected provider
                </p>
              </div>
            )}

            <div>
              <label htmlFor="llmApiKey" className="block text-sm font-semibold text-text mb-2">
                API Key
              </label>
              <input
                id="llmApiKey"
                type="password"
                value={llmApiKey}
                onChange={(e) => setLlmApiKey(e.target.value)}
                className="w-full bg-surface border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent transition-all"
                placeholder={
                  llmProvider === "openai"
                    ? "sk-..."
                    : llmProvider === "anthropic"
                    ? "sk-ant-..."
                    : "Enter your API key"
                }
              />
              <p className="text-xs text-textSecondary mt-1">
                {hasApiKey
                  ? "Enter a new API key to update, or leave empty to keep current key"
                  : "Your API key will be stored securely"}
              </p>
            </div>

            <button
              type="submit"
              disabled={isSavingLlm}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSavingLlm ? "Saving..." : "Save LLM Settings"}
            </button>
          </form>
        </section>

        {/* Account Management */}
        <section>
          <h3 className="text-xl font-semibold text-text mb-4">Account Management</h3>
          <div className="space-y-4">
            <div className="p-4 bg-surface2 border border-border rounded-lg">
              {user.createdAt && (
                <p className="text-sm text-textSecondary mb-2">
                  Account created: {new Date(user.createdAt).toLocaleDateString()}
                </p>
              )}
              <p className="text-sm text-textSecondary">
                Email: {user.email}
              </p>
            </div>

            <button
              onClick={handleLogout}
              className="btn-secondary w-full"
            >
              Logout
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

