import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HawkNetic Sports Tools",
  description: "Sports betting analytics dashboard connected to FastAPI and Railway PostgreSQL.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
