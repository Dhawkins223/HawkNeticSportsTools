import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "NBA Edge Dashboard",
  description: "NBA betting insights with transparency and +EV discovery"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background text-white">
        <Providers>
          <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-10 px-6 py-10">
            <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-3xl font-bold text-white">NBA Edge Dashboard</h1>
                <p className="text-sm text-white/60">
                  Built on predictive simulations, injury insights, and fatigue modeling.
                </p>
              </div>
              <nav className="flex gap-3 text-sm">
                <Link href="/games" className="rounded-xl bg-white/5 px-4 py-2 font-semibold hover:bg-white/10">
                  Games
                </Link>
                <Link href="/props" className="rounded-xl bg-white/5 px-4 py-2 font-semibold hover:bg-white/10">
                  Props
                </Link>
                <Link href="/tickets" className="rounded-xl bg-white/5 px-4 py-2 font-semibold hover:bg-white/10">
                  Tickets
                </Link>
                <Link href="/about-model" className="rounded-xl bg-white/5 px-4 py-2 font-semibold hover:bg-white/10">
                  Transparency
                </Link>
              </nav>
            </header>
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
