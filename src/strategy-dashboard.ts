import { createStrategyGenerate, errorCard } from "./strategy-common";
import type { JinjaboardWsError } from "./types";

/**
 * `ll-strategy-dashboard-jinjaboard`: generates a full Lovelace dashboard by
 * rendering a Jinja2 template file through the `jinjaboard/render` WS command.
 *
 * Lovelace looks this up as `customElements.get("ll-strategy-dashboard-<type>")`
 * and calls the static `generate(config, hass)` — it never renders into the
 * DOM itself, so this only needs to exist as a registered custom element.
 */
class LlStrategyDashboardJinjaboard extends HTMLElement {
  static generate = createStrategyGenerate(errorDashboard);
}

// Full error-code-aware rendering lands in error-panel.ts (M6); this is a
// minimal fallback so a bad template never produces a blank dashboard.
function errorDashboard(error: JinjaboardWsError) {
  return {
    views: [
      {
        title: "JinjaBoard error",
        cards: [errorCard(error)],
      },
    ],
  };
}

customElements.define("ll-strategy-dashboard-jinjaboard", LlStrategyDashboardJinjaboard);

// Registers this strategy for the "create dashboard" suggestion dialog.
// Not required for resolving an existing `strategy: {type: custom:jinjaboard}`
// in a dashboard's YAML — that only depends on customElements.define, above.
declare global {
  interface Window {
    customStrategies?: Array<Record<string, unknown>>;
  }
}
window.customStrategies = window.customStrategies || [];
window.customStrategies.push({
  type: "jinjaboard",
  strategyType: "dashboard",
  name: "JinjaBoard dashboard",
  description: "Renders a Lovelace dashboard from a Jinja2-templated file on disk.",
});
