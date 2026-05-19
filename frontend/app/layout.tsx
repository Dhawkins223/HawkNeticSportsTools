import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HawkNetic Sports Tools",
  description: "Bet365-style slip evaluator for betting decision support.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
