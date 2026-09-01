/**
 * Docs manifest — the sidebar structure, modeled after the classic
 * Docusaurus `sidebars.ts`: sections -> pages, each with a slug
 * (content file `src/content/docs/<slug>.md`) and an i18n key
 * (title/description live in messages/en.json).
 *
 * Pure data — safe to import from client components.
 * File reading/rendering lives in `src/lib/docs-loader.ts` (server only).
 */

export type DocKey =
  | "installation"
  | "firstBoot"
  | "configuration"
  | "journals"
  | "monthEndClose"
  | "procureToPay"
  | "orderToCash"
  | "roles"
  | "cli"
  | "modules";

export type SectionKey = "gettingStarted" | "userGuide" | "reference";

export interface DocEntry {
  /** URL slug; content file is `src/content/docs/<slug>.md`. */
  slug: string;
  /** Key into `docs.pages.*` in the message catalog. */
  key: DocKey;
}

export interface DocSection {
  id: string;
  /** Key into `docs.sections.*` in the message catalog. */
  key: SectionKey;
  docs: DocEntry[];
}

export const DOC_SECTIONS: DocSection[] = [
  {
    id: "getting-started",
    key: "gettingStarted",
    docs: [
      { slug: "installation", key: "installation" },
      { slug: "first-boot", key: "firstBoot" },
      { slug: "configuration", key: "configuration" },
    ],
  },
  {
    id: "user-guide",
    key: "userGuide",
    docs: [
      { slug: "journals", key: "journals" },
      { slug: "month-end-close", key: "monthEndClose" },
      { slug: "procure-to-pay", key: "procureToPay" },
      { slug: "order-to-cash", key: "orderToCash" },
    ],
  },
  {
    id: "reference",
    key: "reference",
    docs: [
      { slug: "roles", key: "roles" },
      { slug: "cli", key: "cli" },
      { slug: "modules", key: "modules" },
    ],
  },
];

/** Flat reading order — used for prev/next pager and generateStaticParams. */
export const FLATTENED_DOCS: DocEntry[] = DOC_SECTIONS.flatMap(
  (section) => section.docs,
);

export function getDocEntry(slug: string): DocEntry | undefined {
  return FLATTENED_DOCS.find((doc) => doc.slug === slug);
}
