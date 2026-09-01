"use client";

import { REPO_URL } from "@/lib/site";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Top navigation bar — brand + anchor links + GitHub CTA.
 * The brand is context-aware: on the landing page it scrolls to the
 * hero (same-route click must still work); on /docs it navigates
 * back to the landing page.
 */
export function Navbar() {
  const t = useTranslations();
  const isLanding = usePathname() === "/";

  return (
    <nav className="nav">
      {isLanding ? (
        <a className="brand" href="#top">
          <span className="brand-mark">A</span>
          <span>ApexLedger</span>
        </a>
      ) : (
        <Link className="brand" href="/">
          <span className="brand-mark">A</span>
          <span>ApexLedger</span>
        </Link>
      )}
      <div className="nav-links">
        <a href="#features">{t("nav.features")}</a>
        <a href="#security">{t("nav.security")}</a>
        <a href="#editions">{t("nav.editions")}</a>
        <a href="#install">{t("nav.install")}</a>
        <Link href="/docs">{t("nav.docs")}</Link>
        <a className="nav-cta" href={REPO_URL}>
          {t("nav.github")}
        </a>
      </div>
    </nav>
  );
}
