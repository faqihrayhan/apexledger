import fs from "node:fs";
import path from "node:path";
import { marked } from "marked";
import { getDocEntry } from "./docs";

/**
 * Server-only docs loader: reads `src/content/docs/<slug>.md`,
 * renders it to HTML with `marked`, and injects heading ids so the
 * table of contents can link to sections.
 */

const DOCS_DIR = path.join(process.cwd(), "src/content/docs");

export interface TocItem {
  text: string;
  id: string;
}

export interface RenderedDoc {
  html: string;
  toc: TocItem[];
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

/** Inject stable ids into <h2>/<h3> tags (marked does not add them). */
function withHeadingIds(html: string): string {
  return html.replace(
    /<h([23])>(.*?)<\/h\1>/g,
    (_match, level: string, inner: string) =>
      `<h${level} id="${slugify(inner.replace(/<[^>]+>/g, ""))}">${inner}</h${level}>`,
  );
}

/** Extract h2 headings for the "On this page" box, ignoring fenced code. */
function extractToc(markdown: string): TocItem[] {
  const withoutCode = markdown.replace(/```[\s\S]*?```/g, "");
  return [...withoutCode.matchAll(/^## (.+)$/gm)].map((match) => {
    const text = match[1].trim();
    return { text, id: slugify(text) };
  });
}

export function getDoc(slug: string): RenderedDoc | null {
  const entry = getDocEntry(slug);
  if (!entry) return null;

  const file = path.join(DOCS_DIR, `${entry.slug}.md`);
  if (!fs.existsSync(file)) return null;

  const markdown = fs.readFileSync(file, "utf8");
  const html = marked.parse(markdown, { async: false });
  return {
    html: withHeadingIds(html),
    toc: extractToc(markdown),
  };
}
