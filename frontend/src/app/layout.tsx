import type { Metadata } from "next";
import "./globals.css";
import "./desktop-absolute.css";
import "./spatial-lab.css";
import "./remote.css";
import type { Viewport } from "next";

export const metadata: Metadata = {
  title: "Akashi AI",
  description: "Project ABSOLUTE local intelligence interface",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
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
