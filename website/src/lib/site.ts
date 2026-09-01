/**
 * Central site configuration for the ApexLedger landing page.
 *
 * Every URL, version, and download link rendered by the page comes from
 * this single module — edit here, not in the components.
 */

const GITHUB_OWNER = "faqihrayhan";
const SYSTEM_REPO = "apexledger";
const LATEST_VERSION = "v0.1.0";

export const REPO_URL = `https://github.com/${GITHUB_OWNER}/${SYSTEM_REPO}`;

export const INSTALL_URLS = {
  sh: `https://raw.githubusercontent.com/${GITHUB_OWNER}/${SYSTEM_REPO}/main/install.sh`,
  ps1: `https://raw.githubusercontent.com/${GITHUB_OWNER}/${SYSTEM_REPO}/main/install.ps1`,
};

export const RELEASES_URL = `${REPO_URL}/releases`;
export const DOCS_URLS = {
  setup: `${REPO_URL}/blob/main/docs/SETUP.md`,
};

/** Installer download links for the latest release (filename -> URL). */
export const DOWNLOADS = {
  exe: installer("ApexLedger_0.1.0_x64-setup.exe"),
  msi: installer("ApexLedger_0.1.0_x64_en-US.msi"),
  dmg: installer("ApexLedger_0.1.0_universal.dmg"),
  appimage: installer("ApexLedger_0.1.0_amd64.AppImage"),
} as const;

function installer(filename: string): string {
  return `${REPO_URL}/releases/download/${LATEST_VERSION}/${filename}`;
}
