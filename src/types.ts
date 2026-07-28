/**
 * Frontend-supplied, best-effort render-time context — entirely gathered
 * client-side and unverifiable server-side (unlike `jjb.user`, which the
 * backend derives from the authenticated WS connection itself). Useful for
 * cosmetic/conditional-layout branching in a template, not for anything
 * security-sensitive.
 */
export interface ClientContext {
  user_agent?: string;
  viewport?: { width: number; height: number };
  browser_mod_id?: string;
  language?: string;
  is_dark_theme?: boolean;
}

export interface RenderRequest {
  type: "jinjaboard/render";
  template: string;
  globals?: Record<string, unknown>;
  macros?: string[];
  client?: ClientContext;
}

export type JinjaboardErrorCode =
  | "path_missing"
  | "path_traversal"
  | "template_not_authorized"
  | "include_not_found"
  | "template_error"
  | "yaml_parse_error"
  | "render_timeout";

export interface JinjaboardWsError {
  code: JinjaboardErrorCode;
  message: string;
}

/**
 * Minimal shape of the `hass` object the strategy elements need — a
 * structural subset of home-assistant-frontend's real `HomeAssistant`
 * interface (not installed as a dependency here), extended only with the
 * fields actually read (`language`/`themes.darkMode`, for `jjb.client`).
 */
export interface HomeAssistant {
  callWS<T>(msg: object): Promise<T>;
  language?: string;
  themes?: { darkMode?: boolean };
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
  globals?: Record<string, unknown>;
  macros?: string[];
}
