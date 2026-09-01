import { REPO_URL } from "@/lib/site";
import { useTranslations } from "next-intl";

/**
 * Hero section — headline, CTAs, and the three trust stats.
 */
export function Hero() {
  const t = useTranslations();

  return (
    <header className="hero" id="top">
      <div className="hero-inner">
        <p className="eyebrow">{t("hero.eyebrow")}</p>
        <h1>
          {t("hero.title1")}
          <br />
          on <span className="accent">{t("hero.titleYour")}</span> machine.
        </h1>
        <p className="lede">{t("hero.lede")}</p>
        <div className="hero-actions">
          <a className="btn btn-primary" href="#install">
            {t("hero.ctaPrimary")}
          </a>
          <a className="btn btn-ghost" href={REPO_URL}>
            {t("hero.ctaSecondary")}
          </a>
        </div>
        <div className="hero-stats">
          <div>
            <strong>{t("hero.stats.local.value")}</strong>
            <span>{t("hero.stats.local.label")}</span>
          </div>
          <div>
            <strong>{t("hero.stats.rows.value")}</strong>
            <span>{t("hero.stats.rows.label")}</span>
          </div>
          <div>
            <strong>{t("hero.stats.tests.value")}</strong>
            <span>{t("hero.stats.tests.label")}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
