import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Akashi AI",
  description: "Project ABSOLUTE local intelligence interface",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
