import "./globals.css";
import type { Metadata } from "next";
import { Providers } from "./providers";
import { Navigation } from "@/components/Navigation";

export const metadata: Metadata = {
  title: "NBA Edge Dashboard",
  description: "NBA betting insights with transparency and +EV discovery"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background text-white">
        <Providers>
          <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-8 px-4 py-6 sm:px-6 sm:py-8">
            <header className="card p-6 mb-4 relative z-10">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex-shrink-0">
                  <h1 className="text-4xl font-bold text-text mb-2 bg-gradient-to-r from-accent to-accentHover bg-clip-text text-transparent">
                    NBA Edge Dashboard
                  </h1>
                  <p className="text-sm text-textSecondary">
                    Built on predictive simulations, injury insights, and fatigue modeling.
                  </p>
                </div>
                <Navigation />
              </div>
            </header>
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
