import type { Metadata } from "next";
import { Roboto, Roboto_Mono } from "next/font/google";
import { ReactNode } from "react";

import "./globals.css";

const roboto = Roboto({
  subsets: ["latin"],
  variable: "--font-roboto",
  weight: ["400", "500", "600", "700"],
});

const robotoMono = Roboto_Mono({
  subsets: ["latin"],
  variable: "--font-roboto-mono",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "NCC Ingestion Console",
  description: "Upload NCC PDF and XML files to run contract-backed validation.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${roboto.variable} ${robotoMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
