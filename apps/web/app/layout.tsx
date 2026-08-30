import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { Providers } from "@/app/providers";
import { SiteHeader } from "@/components/site-header";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "WHAT IF",
    template: "%s · WHAT IF",
  },
  description:
    "A counterfactual possibility explorer. Fork reality and explore the paths hidden behind your decisions.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <Providers>
          <SiteHeader />
          <main className="flex-1">{children}</main>
          <footer className="border-t py-6">
            <div className="mx-auto max-w-6xl px-4 text-xs text-muted-foreground">
              WHAT IF proposes structured possibilities — it does not predict, decide,
              or invent facts.
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
