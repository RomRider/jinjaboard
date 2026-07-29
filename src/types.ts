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
  /** The display path (relative to the HA config directory) of the entry-point template. */
  root_path: string;
  /**
   * Every touched file's post-Jinja, pre-YAML-parse text, keyed by display
   * path — root included, under `root_path`. A file `!include`d more than
   * once keeps only its last occurrence's rendered text.
   */
  raw_texts: Record<string, string>;
  /**
   * The effective `!include ... vars:` in scope for each file that has
   * any (i.e. exactly what `jjb.inc` resolves to inside it, including
   * anything inherited from an ancestor include's own `vars:`) — keyed by
   * display path like `raw_texts`, root never present since it never has
   * `inc_vars`. A file `!include`d more than once keeps only its last
   * occurrence's vars.
   */
  include_vars: Record<string, Record<string, unknown>>;
  /**
   * Maps a dot-path into the parsed result (e.g. `"views.2.cards.0"`) to
   * the display path of the file that subtree came from, for every part
   * of the result that originated from an `!include` whose resolved value
   * was a dict/list — a path with no entry here lives directly in
   * `root_path`. Only the most specific (deepest) path a given node
   * matches is guaranteed present; see `resolveOrigin` in
   * strategy-common.ts.
   */
  origins: Record<string, string>;
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
