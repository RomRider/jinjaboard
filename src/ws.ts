import type { HomeAssistant, RenderRequest } from "./types";

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
  globals?: Record<string, unknown>,
  macros?: string[],
): Promise<unknown> {
  const request: RenderRequest = {
    type: "jinjaboard/render",
    template,
    globals,
    macros,
  };
  return hass.callWS(request);
}
