import type { ClientContext, HomeAssistant, RenderRequest } from "./types";

// The localStorage key `browser_mod`'s own frontend uses to persist a
// browser's id across reloads — reading it here is the only way to
// correlate this render request with a specific `browser_mod` device
// entity, since the backend has no way to derive it on its own.
const BROWSER_MOD_ID_STORAGE_KEY = "browser_mod-browser-id";

/**
 * Gathers frontend-only, unverifiable render context for `jjb.client` —
 * see `ClientContext`'s doc comment in types.ts for the trust distinction
 * from `jjb.user` (which the backend derives itself, from the
 * authenticated WS connection, and never trusts to the frontend).
 *
 * A field is omitted entirely (not sent as `null`/empty string) when its
 * source isn't available, e.g. no `browser_mod` installed — `jjb.client.*`
 * lookups default safely via Jinja's `| default(...)` either way.
 */
function gatherClientContext(hass: HomeAssistant): ClientContext {
  const browserModId = localStorage.getItem(BROWSER_MOD_ID_STORAGE_KEY);
  return {
    user_agent: window.navigator.userAgent,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    ...(browserModId ? { browser_mod_id: browserModId } : {}),
    ...(hass.language ? { language: hass.language } : {}),
    ...(hass.themes?.darkMode !== undefined ? { is_dark_theme: hass.themes.darkMode } : {}),
  };
}

/**
 * Call the `jinjaboard/render` WebSocket command.
 *
 * On failure, `hass.callWS` (home-assistant-js-websocket) rejects with the
 * raw `{code, message}` error object sent by `connection.send_error` on the
 * backend — matches `JinjaboardWsError` in types.ts, no translation needed.
 */
export function renderTemplate(
  hass: HomeAssistant,
  template: string,
  globals?: Record<string, unknown> | string,
  macros?: string[],
  debug?: boolean | string | string[],
): Promise<unknown> {
  // A list is only meaningfully "set" when non-empty — an explicit `[]`
  // (or `false`/`""`) is folded to `undefined` so it's omitted from the
  // request entirely, same as `globals`/`macros` above.
  const hasDebug = Array.isArray(debug) ? debug.length > 0 : Boolean(debug);
  const request: RenderRequest = {
    type: "jinjaboard/render",
    template,
    globals,
    macros,
    debug: hasDebug ? debug : undefined,
    client: gatherClientContext(hass),
  };
  return hass.callWS(request);
}
