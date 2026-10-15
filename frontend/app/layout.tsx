import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Discharge Explainer",
  description: "Source-grounded discharge summary explanation demo"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
