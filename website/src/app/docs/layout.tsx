import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { DocsSidebar } from "@/components/DocsSidebar";

/**
 * Shell for every /docs page — same navbar/footer as the landing plus
 * the section sidebar. The sidebar derives its active item from the
 * pathname, so pages stay pure content.
 */
export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <Navbar />
      <div className="docs-shell">
        <DocsSidebar />
        <main className="docs-main">{children}</main>
      </div>
      <Footer />
    </>
  );
}
