import { DOCS_URLS, DOWNLOADS, INSTALL_URLS, RELEASES_URL } from "@/lib/site";
import { useTranslations } from "next-intl";
import { Terminal } from "./Terminal";

/**
 * Install section — three cards: Server one-liner, Desktop bundles,
 * and Browser/LAN access. All download URLs come from lib/site.ts.
 */
export function Install() {
  const t = useTranslations();

  return (
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
  );
}
