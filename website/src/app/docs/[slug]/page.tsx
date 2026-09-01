import { FLATTENED_DOCS, getDocEntry } from "@/lib/docs";
import { getDoc } from "@/lib/docs-loader";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";

/** Pre-render every docs page at build time (static export). */
export function generateStaticParams() {
  return FLATTENED_DOCS.map((doc) => ({ slug: doc.slug }));
}

/** Per-page <title> from the message catalog. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const entry = getDocEntry(slug);
  if (!entry) return {};
  const t = await getTranslations("docs");
  return { title: `${t(`pages.${entry.key}.title`)} — ApexLedger Docs` };
}

/** Previous/next pager across the flat reading order. */
function Pager({
  prev,
  next,
  labels,
}: {
  prev: { slug: string; title: string } | null;
  next: { slug: string; title: string } | null;
  labels: { prev: string; next: string };
}) {
  return (
    <nav className="docs-pager">
      {prev ? (
        <Link href={`/docs/${prev.slug}`} className="docs-pager-link">
          ← {labels.prev}: {prev.title}
        </Link>
      ) : (
        <span />
      )}
      {next ? (
        <Link href={`/docs/${next.slug}`} className="docs-pager-link">
          {labels.next}: {next.title} →
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}

export default async function DocPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) notFound();

  const entry = getDocEntry(slug)!;
  const t = await getTranslations("docs");
  const idx = FLATTENED_DOCS.findIndex((d) => d.slug === slug);
  const prevEntry = idx > 0 ? FLATTENED_DOCS[idx - 1] : null;
  const nextEntry =
    idx >= 0 && idx < FLATTENED_DOCS.length - 1 ? FLATTENED_DOCS[idx + 1] : null;

  const prev = prevEntry
    ? { slug: prevEntry.slug, title: t(`pages.${prevEntry.key}.title`) }
    : null;
  const next = nextEntry
    ? { slug: nextEntry.slug, title: t(`pages.${nextEntry.key}.title`) }
    : null;

  return (
    <div className="docs-page">
      <p className="docs-breadcrumb">
        <Link href="/docs">{t("index.title")}</Link> /{" "}
        {t(`pages.${entry.key}.title`)}
      </p>
      <div className="docs-columns">
        <article
          className="docs-article"
          dangerouslySetInnerHTML={{ __html: doc.html }}
        />
        {doc.toc.length > 0 && (
          <nav className="docs-toc" aria-label="On this page">
            <p>{t("toc.title")}</p>
            <ul>
              {doc.toc.map((item) => (
                <li key={item.id}>
                  <a href={`#${item.id}`}>{item.text}</a>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
      <Pager
        prev={prev}
        next={next}
        labels={{ prev: t("pager.prev"), next: t("pager.next") }}
      />
    </div>
  );
}
