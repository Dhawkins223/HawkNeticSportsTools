import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "HawkNetic Predictor Tools",
  description: "Multi-sport prediction-algorithm dashboard. Build a slate, press Run Algorithm, get a verdict. No wagers placed.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><AuthProvider>{children}</AuthProvider></body></html>;
}
