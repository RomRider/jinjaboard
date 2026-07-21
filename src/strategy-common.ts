import { renderTemplate } from "./ws";
import type { HomeAssistant, JinjaboardWsError, StrategyConfig } from "./types";

export function errorCard(error: JinjaboardWsError) {
  return {
    type: "markdown",
    content: `## JinjaBoard render error\n\n**${error.code ?? "error"}**\n\n${error.message ?? String(error)}`,
  };
}

/**
 * Builds the static `generate(config, hass)` HA looks up on a strategy
 * custom element — shared across the dashboard/view/section strategies,
 * which differ only in the registered tag and the error-result shape
 * `buildErrorResult` returns (a full dashboard vs a bare `{cards: [...]}`).
 */
export function createStrategyGenerate(buildErrorResult: (error: JinjaboardWsError) => unknown) {
  return async function generate(config: StrategyConfig, hass: HomeAssistant): Promise<unknown> {
    const template = config?.template;
    if (!template) {
      return buildErrorResult({
        code: "template_error",
        message:
          "jinjaboard strategy: options.template is required (a path to the " +
          "template file, relative to the Home Assistant config directory).",
      });
    }

    try {
      return await renderTemplate(hass, template, config?.globals, config?.macros);
    } catch (err) {
      return buildErrorResult(err as JinjaboardWsError);
    }
  };
}
