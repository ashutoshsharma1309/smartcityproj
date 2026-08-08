import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "UrbanPulse — Flood Risk Command Centre",
  description:
    "Predictive urban flood and waterlogging risk, and its impact on roads and traffic.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-ground-950 text-ink-100 antialiased">
        {children}
      </body>
    </html>
  );
}
