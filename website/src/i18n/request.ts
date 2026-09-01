import { getRequestConfig } from "next-intl/server";
import en from "../messages/en.json";

/**
 * Locale resolution for the static landing page.
 *
 * The site is English-only for now (single `en` message catalog); the
 * shape follows the repo convention (next-intl, EN default) so adding
 * `id` later is a matter of dropping a messages file and a locale
 * link in the nav.
 */
export default getRequestConfig(async () => ({
  locale: "en",
  messages: en,
}));
