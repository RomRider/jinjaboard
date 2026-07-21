export interface RenderRequest {
  type: "jinjaboard/render";
  template: string;
  globals?: Record<string, unknown>;
  macros?: string[];
}

export interface SubscribeRenderRequest {
  type: "jinjaboard/subscribe_render";
  template: string;
  globals?: Record<string, unknown>;
  macros?: string[];
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

/**
 * A message pushed over a `jinjaboard/subscribe_render` subscription — the
 * initial render and every subsequent one share this same shape (see
 * `websocket.py`'s `handle_subscribe_render`: the ack carries no payload,
 * home-assistant-js-websocket only ever forwards `event` messages to a
 * `subscribeMessage` callback).
 */
export type JinjaboardSubscribeEvent = { result: unknown } | { error: JinjaboardWsError };

/** Minimal shape of the `hass` object the strategy elements need. */
export interface HomeAssistant {
  callWS<T>(msg: object): Promise<T>;
  connection: {
    subscribeMessage<T>(
      callback: (result: T) => void,
      message: object,
    ): Promise<() => void>;
  };
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
  /**
   * Opt-in live re-render: when true, the dashboard/view/section pushes a
   * fresh render whenever an entity/domain it actually depends on changes,
   * and swaps it in live (no page reload) — default `false`. See
   * `strategy-common.ts`'s `shouldRegenerateJinjaboard`/
   * `getOrCreateSubscription` for how this is wired up.
   */
  auto_update?: boolean;
}
