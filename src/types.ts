export interface RenderRequest {
  type: "jinjaboard/render";
  template: string;
  variables?: Record<string, unknown>;
}

export type JinjaboardErrorCode =
  | "path_missing"
  | "path_traversal"
  | "include_not_found"
  | "template_error"
  | "yaml_parse_error"
  | "render_timeout";

export interface JinjaboardWsError {
  code: JinjaboardErrorCode;
  message: string;
}

/** Minimal shape of the `hass` object the strategy elements need. */
export interface HomeAssistant {
  callWS<T>(msg: object): Promise<T>;
}

/**
 * Fields live directly on the strategy config, not nested under `options`.
 *
 * home-assistant-frontend's `cleanLegacyStrategyConfig` treats any strategy
 * config shaped as exactly `{type, options}` as a "legacy" config and
 * flattens `options` onto the top level (deleting `options` itself) before
 * calling `generate()` — see strategies/legacy-strategy.ts. Since our config
 * is only ever `{type, options: {...}}` in the dashboard YAML, it always
 * matches that legacy shape, so `generate()` receives `config.template`
 * directly, never `config.options.template`.
 */
export interface StrategyConfig {
  template?: string;
  variables?: Record<string, unknown>;
}
