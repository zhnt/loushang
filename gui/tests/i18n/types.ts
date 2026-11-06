// Compile-only negative cases: unused @ts-expect-error makes tsc fail if a constraint regresses.
import { i18n } from "../../src/i18n";
function verifyTranslationTypes() {
  i18n.t("session:notice.modelChanged", { model: "example" });
  // @ts-expect-error unknown translation key
  i18n.t("session:not.a.real.key");
  // @ts-expect-error missing required interpolation
  i18n.t("session:notice.modelChanged", { wrongName: "example" });
}
void verifyTranslationTypes;
