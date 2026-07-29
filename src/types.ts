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
  /** A YAML mapping (inline) or a string path to a `globals:` file, relative to the HA config directory. */
  globals?: Record<string, unknown> | string;
  macros?: string[];
  /**
   * `true` logs everything to the browser console; a string (or list of
   * strings) is a dot-separated output path (e.g. `"views.2.cards.0"`,
   * numeric segments index into arrays) narrowing which subtree(s) of the
   * parsed result get logged. Only takes effect for an admin connection —
   * the backend silently ignores it (returns the ordinary bare result) for
   * anyone else.
   */
  debug?: boolean | string | string[];
  client?: ClientContext;
}

export type JinjaboardErrorCode =
  | "path_missing"
  | "path_traversal"
  | "template_not_authorized"
  | "include_not_found"
  | "template_error"
  | "yaml_parse_error"
  | "globals_error"
  | "render_timeout";

export interface JinjaboardWsError {
  code: JinjaboardErrorCode;
  message: string;
}

/** Debug metadata accompanying a render result — see `JinjaboardDebugEnvelope`. */
export interface JinjaboardDebugInfo {
  duration_ms: number;
  /** The root template's post-Jinja, pre-YAML-parse text. */
  raw_root_text: string;
  /** Every `!include`/`!include_dir_*` file touched, root excluded. */
  include_paths: string[];
}

/**
 * The `jinjaboard/render` result shape when `debug` was honored (a truthy
 * request value *and* an admin connection) — otherwise the bare parsed
 * config is returned exactly as before, unwrapped. Callers must check the
 * actual response shape (see `isDebugEnvelope` in strategy-common.ts)
 * rather than assume the wrapped shape just because `debug` was requested,
 * since a non-admin's request is silently downgraded server-side.
 */
export interface JinjaboardDebugEnvelope {
  config: unknown;
  debug: JinjaboardDebugInfo;
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
  /** A YAML mapping (inline) or a string path to a `globals:` file, relative to the HA config directory. */
  globals?: Record<string, unknown> | string;
  macros?: string[];
  /** See `RenderRequest.debug` — forwarded to the WS request unchanged. */
  debug?: boolean | string | string[];
}
