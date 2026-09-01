"use client";

import { DOC_SECTIONS } from "@/lib/docs";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Docs sidebar — sections with their pages, current page highlighted.
 * Modeled after the Docusaurus sidebar; structure comes from the
 * manifest in `src/lib/docs.ts` and labels from next-intl.
 *
 * The active page is derived from the pathname, so the shell in
 * `app/docs/layout.tsx` can render this once for every docs route.
 */
export function DocsSidebar() {
  const t = useTranslations("docs");
  const pathname = usePathname();
  const activeSlug = pathname.startsWith("/docs/")
    ? pathname.replace("/docs/", "")
    : undefined;

  return (
    <aside className="docs-sidebar">
      <nav>
        {DOC_SECTIONS.map((section) => (
          <div key={section.id} className="docs-nav-group">
            <p className="docs-nav-label">{t(`sections.${section.key}`)}</p>
            {section.docs.map((doc) => (
              <Link
                key={doc.slug}
                href={`/docs/${doc.slug}`}
                className={
                  doc.slug === activeSlug
                    ? "docs-nav-link active"
                    : "docs-nav-link"
                }
              >
                {t(`pages.${doc.key}.title`)}
              </Link>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}
