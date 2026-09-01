import { useTranslations } from "next-intl";
import {
  REPO_URL,
  RELEASES_URL,
  DOCS_URLS,
  INSTALL_URLS,
  DOWNLOADS,
} from "@/lib/site";

/**
 * Terminal-styled code block with fake window chrome.
 * Server-rendered (no client JS) — static-export friendly.
 */
function Terminal({ lines }: { lines: string[] }) {
  return (
    <div className="terminal">
      <div className="term-bar">
        <span />
        <span />
        <span />
      </div>
      <pre>
        <code>{lines.join("\n")}</code>
      </pre>
    </div>
  );
}

export default function Home() {
  const t = useTranslations();

  return (
    <>
      <nav className="nav">
        <a className="brand" href="#top">
          <span className="brand-mark">A</span>
          <span>ApexLedger</span>
        </a>
        <div className="nav-links">
          <a href="#features">{t("nav.features")}</a>
          <a href="#security">{t("nav.security")}</a>
          <a href="#editions">{t("nav.editions")}</a>
          <a href="#install">{t("nav.install")}</a>
          <a className="nav-cta" href={REPO_URL}>
            {t("nav.github")}
          </a>
        </div>
      </nav>

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

      <section className="section section-alt" id="install">
        <h2>{t("install.title")}</h2>
        <p className="lede-small">{t("install.subtitle")}</p>

        <div className="install-grid">
          <div className="install-card">
            <h3>{t("install.server.title")}</h3>
            <p className="install-for">{t("install.server.for")}</p>
            <p>{t("install.server.body")}</p>
            <Terminal
              lines={[`curl -fsSL ${INSTALL_URLS.sh} | bash`]}
            />
            <p>{t("install.server.windowsLabel")}</p>
            <Terminal
              lines={[`irm ${INSTALL_URLS.ps1} | iex`]}
            />
            <p className="install-note">{t("install.server.note")}</p>
          </div>

          <div className="install-card">
            <h3>{t("install.desktop.title")}</h3>
            <p className="install-for">{t("install.desktop.for")}</p>
            <p>{t("install.desktop.body")}</p>
            <ul className="install-list">
              <li>
                {t("install.desktop.windows")} —{" "}
                <a href={DOWNLOADS.exe}>.exe</a> / <a href={DOWNLOADS.msi}>.msi</a>
              </li>
              <li>
                {t("install.desktop.macos")} — <a href={DOWNLOADS.dmg}>.dmg</a>{" "}
                ({t("install.desktop.macosNote")})
              </li>
              <li>
                {t("install.desktop.linux")} —{" "}
                <a href={DOWNLOADS.appimage}>.AppImage</a>
              </li>
            </ul>
            <p className="install-note">
              {t("install.desktop.note")}{" "}
              <a href={RELEASES_URL}>GitHub Releases</a>
            </p>
          </div>

          <div className="install-card">
            <h3>{t("install.browser.title")}</h3>
            <p className="install-for">{t("install.browser.for")}</p>
            <p>{t("install.browser.body")}</p>
            <Terminal
              lines={[
                "# on the server machine",
                "python cli.py serve          # API + UI on :8000",
                "",
                "# then, from any PC on the LAN",
                "http://192.168.1.100:8000",
              ]}
            />
            <p className="install-note">{t("install.browser.note")}</p>
          </div>
        </div>

        <p className="lede-small" style={{ marginTop: 32 }}>
          {t("install.advanced")}{" "}
          <a href={DOCS_URLS.setup}>docs/SETUP.md</a>
        </p>
      </section>

      <footer className="footer">
        <p>{t("footer.line1")}</p>
        <p>
          <a href={REPO_URL}>{t("footer.github")}</a>
        </p>
      </footer>
    </>
  );
}
