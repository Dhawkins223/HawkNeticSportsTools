import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "HawkneticSportsTools — Multi-sport algorithm decision platform",
  description: "HawkneticSports brings real Monte Carlo + no-vig math to NBA, NFL, MLB, NHL, Soccer, and Golf. Build a slate, press Run Algorithm, get a verdict. We are a decision-support tool — not a sportsbook.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><AuthProvider>{children}</AuthProvider></body></html>;
}
