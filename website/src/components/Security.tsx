import { useTranslations } from "next-intl";

/**
 * Security model section — three columns (RLS, dual bookkeeping, roles).
 */
export function Security() {
  const t = useTranslations();

  return (
    <section className="section section-alt" id="security">
      <h2>{t("security.title")}</h2>
      <div className="security-cols">
        {(["rls", "dual", "roles"] as const).map((key) => (
          <div key={key}>
            <h3>{t(`security.cols.${key}.title`)}</h3>
            <p>{t(`security.cols.${key}.body`)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
