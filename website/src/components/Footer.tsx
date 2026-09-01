import { REPO_URL } from "@/lib/site";
import { useTranslations } from "next-intl";

/**
 * Site footer — tagline + GitHub link.
 */
export function Footer() {
  const t = useTranslations();

  return (
    <footer className="footer">
      <p>{t("footer.line1")}</p>
      <p>
        <a href={REPO_URL}>{t("footer.github")}</a>
      </p>
    </footer>
  );
}
