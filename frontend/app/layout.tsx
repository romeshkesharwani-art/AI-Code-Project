import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Coverwise — Policy intelligence",
  description: "Search and understand your insurance policies.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
