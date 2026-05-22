import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HawkNetic Predictor Tools",
  description: "Sportsbook-style market board powered by HawkNetic's prediction algorithms. Build a slate, press Run Algorithm, get a prediction. No wagers placed.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
