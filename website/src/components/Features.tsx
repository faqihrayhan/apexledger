import { useTranslations } from "next-intl";

/**
 * "Why ApexLedger" — six feature cards.
 * Card list is data-driven from the translation catalog keys.
 */
export function Features() {
  const t = useTranslations();

  return (
    <section className="section" id="features">
      <h2>{t("features.title")}</h2>
      <div className="grid">
        {(
          [
            "doubleEntry",
            "immutable",
            "ai",
            "ui",
            "setup",
            "backup",
          ] as const
        ).map((key) => (
          <article className="card" key={key}>
            <h3>{t(`features.items.${key}.title`)}</h3>
            <p>{t(`features.items.${key}.body`)}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
