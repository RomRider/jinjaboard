import { createStrategyGenerate, errorCard } from "./strategy-common";
import type { JinjaboardWsError } from "./types";

/**
 * `ll-strategy-section-jinjaboard`: generates a single Lovelace section's
 * content (`cards`, plus any other section-level keys the render returns)
 * by rendering a Jinja2 template file through the `jinjaboard/render` WS
 * command.
 *
 * Lovelace looks this up as `customElements.get("ll-strategy-section-<type>")`
 * for a `sections: [{strategy: {...}, ...}]` entry (inside a `type: sections`
 * view), merging the returned object over any sibling keys (`column_span`,
 * `title`, ...) already on that section.
 */
class LlStrategySectionJinjaboard extends HTMLElement {
  static generate = createStrategyGenerate(errorSection);
}

function errorSection(error: JinjaboardWsError) {
  return { cards: [errorCard(error)] };
}

customElements.define("ll-strategy-section-jinjaboard", LlStrategySectionJinjaboard);
