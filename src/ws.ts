import type {
  HomeAssistant,
  JinjaboardSubscribeEvent,
  RenderRequest,
  SubscribeRenderRequest,
} from "./types";

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

/**
 * Subscribe to the `jinjaboard/subscribe_render` WS command: `callback` is
 * invoked once with the initial render, then again every time the backend
 * decides a tracked entity/domain changed (see `websocket.py`'s
 * `handle_subscribe_render`) — no polling or frontend-side diffing.
 *
 * `subscribeMessage`'s default `resubscribe: true` means a WS reconnect
 * (e.g. an HA restart) transparently re-sends the subscribe message on the
 * same `Connection` and re-invokes `callback` as if freshly subscribed —
 * no extra reconnect handling needed here.
 *
 * Returns the unsubscribe function `subscribeMessage` resolves to.
 */
export function subscribeRenderTemplate(
  hass: HomeAssistant,
  template: string,
  globals: Record<string, unknown> | undefined,
  macros: string[] | undefined,
  callback: (event: JinjaboardSubscribeEvent) => void,
): Promise<() => void> {
  const request: SubscribeRenderRequest = {
    type: "jinjaboard/subscribe_render",
    template,
    globals,
    macros,
  };
  return hass.connection.subscribeMessage<JinjaboardSubscribeEvent>(callback, request);
}
