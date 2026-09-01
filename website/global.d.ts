// Type-Safe i18n (repo convention): the EN catalog is the source of truth.
// `AppConfig.Messages` is consumed by next-intl's type generation
// (tsconfig includes this file via the `next-intl` types entry).
import "next-intl";

declare module "next-intl" {
  interface AppConfig {
    Messages: typeof import("./src/messages/en.json");
    Locale: "en";
  }
}
