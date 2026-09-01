import { DOC_SECTIONS } from "@/lib/docs";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

/**
 * Docs index — a compact catalog of every page, grouped by section,
 * with a one-line description pulled from the message catalog.
 */
export default async function DocsIndex() {
  const t = await getTranslations("docs");

  const sections = DOC_SECTIONS.map((section) => ({
    id: section.id,
    label: t(`sections.${section.key}`),
    pages: section.docs.map((doc) => ({
      slug: doc.slug,
      title: t(`pages.${doc.key}.title`),
      description: t(`pages.${doc.key}.description`),
    })),
  }));

  return (
    <div className="docs-page">
      <h1>{t("index.title")}</h1>
      <p className="docs-lede">{t("index.lede")}</p>
      {sections.map((section) => (
        <div key={section.id} className="docs-index-group">
          <h2>{section.label}</h2>
          <div className="docs-card-grid">
            {section.pages.map((page) => (
              <Link key={page.slug} href={`/docs/${page.slug}`} className="docs-card">
                <h3>{page.title}</h3>
                <p>{page.description}</p>
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
