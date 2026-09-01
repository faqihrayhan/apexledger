import { useTranslations } from "next-intl";

/**
 * Editions pricing section — Community vs Enterprise cards.
 * List items come from the translation catalog (t.raw array).
 */
export function Editions() {
  const t = useTranslations();

  return (
    <section className="section" id="editions">
      <h2>{t("editions.title")}</h2>
      <div className="editions">
        <article className="edition">
          <h3>{t("editions.community.name")}</h3>
          <p className="price">{t("editions.community.price")}</p>
          <ul>
            {t.raw("editions.community.items").map((item: string) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
        <article className="edition edition-featured">
          <h3>{t("editions.enterprise.name")}</h3>
          <p className="price">{t("editions.enterprise.price")}</p>
          <ul>
            {t.raw("editions.enterprise.items").map((item: string) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </div>
    </section>
  );
}
