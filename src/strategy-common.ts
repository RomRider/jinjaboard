import { renderTemplate, subscribeRenderTemplate } from "./ws";
import type {
  HomeAssistant,
  JinjaboardSubscribeEvent,
  JinjaboardWsError,
  StrategyConfig,
} from "./types";

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

    if (config?.auto_update) {
      return getOrCreateSubscription(hass, template, config, buildErrorResult);
    }

    try {
      return await renderTemplate(hass, template, config?.globals, config?.macros);
    } catch (err) {
      return buildErrorResult(err as JinjaboardWsError);
    }
  };
}

// --- `auto_update` live-regeneration plumbing -------------------------------
//
// `generate()` (above) is only ever re-invoked by Home Assistant's Lovelace
// frontend when its `checkStrategyShouldRegenerate()` decides to (see
// `strategies/get-strategy.ts`) — which, once a strategy class defines
// `static shouldRegenerate`, is driven *exclusively* by that hook, bypassing
// the default registry-reference check entirely. `shouldRegenerateJinjaboard`
// below is that hook, shared by all three strategy files (each just assigns
// `static shouldRegenerate = shouldRegenerateJinjaboard`).
//
// The actual "did anything this render depends on change" decision is made
// entirely on the backend (`jinjaboard/subscribe_render`, see
// `websocket.py`) — this file never diffs `hass` state itself. All
// `shouldRegenerateJinjaboard` does for an `auto_update` config is check
// (and clear) a flag that a pushed WS event already set.

/** A raw strategy config, possibly still in the legacy `{type, options}` shape. */
interface RawStrategyConfig extends StrategyConfig {
  type?: string;
  options?: StrategyConfig;
}

/**
 * `shouldRegenerate(config, ...)` receives the *raw* strategy config —
 * unlike `generate()`, which by the time HA calls it has already been run
 * through `cleanLegacyStrategyConfig` (see `strategies/get-strategy.ts`'s
 * `generateStrategy`). Local mirror of that exact rule
 * (`legacy-strategy.ts`'s `isLegacyStrategyConfig`/`cleanLegacyStrategyConfig`:
 * a config shaped as exactly `{type, options}` gets `options` flattened onto
 * it) so `auto_update`/the cache key are read correctly regardless of which
 * shape a dashboard author used.
 */
function unwrapLegacyStrategyConfig(config: RawStrategyConfig): StrategyConfig {
  const keys = Object.keys(config);
  if (keys.length === 2 && "options" in config && typeof config.options === "object") {
    const { options, ...rest } = config;
    return { ...rest, ...options };
  }
  return config;
}

/**
 * Mirrors home-assistant-frontend's own `DEFAULT_REGISTRY_DEPENDENCIES`
 * (`strategies/get-strategy.ts`) — the check `checkStrategyShouldRegenerate`
 * falls back to when a strategy defines neither `shouldRegenerate` nor
 * `registryDependencies`. Since jinjaboard strategies define
 * `shouldRegenerate` (below), that fallback never runs for us — so for an
 * `auto_update: false` (default) config, this is replicated by hand here,
 * or every jinjaboard dashboard would silently lose the "regenerate when
 * the entity/device/area/floor registry changes" behavior it already gets
 * for free today.
 */
const DEFAULT_REGISTRY_DEPENDENCIES = ["entities", "devices", "areas", "floors"] as const;

interface CacheEntry {
  latest: unknown;
  pendingRegenerate: boolean;
  unsubscribe: () => void;
}

/**
 * Keyed by `hass.connection` (a `WeakMap`, so entries are dropped for free
 * when the connection is replaced, e.g. on a full reconnect — strategy
 * classes are stateless with no lifecycle hook to clean this up otherwise),
 * then by a stable string of the template/globals/macros being rendered.
 */
const subscriptionCache = new WeakMap<HomeAssistant["connection"], Map<string, CacheEntry>>();

function cacheKey(config: StrategyConfig): string {
  return JSON.stringify([config.template, config.globals ?? {}, config.macros ?? []]);
}

function getOrCreateSubscription(
  hass: HomeAssistant,
  template: string,
  config: StrategyConfig,
  buildErrorResult: (error: JinjaboardWsError) => unknown,
): Promise<unknown> {
  let byKey = subscriptionCache.get(hass.connection);
  if (!byKey) {
    byKey = new Map();
    subscriptionCache.set(hass.connection, byKey);
  }

  const key = cacheKey(config);
  const existing = byKey.get(key);
  if (existing) {
    return Promise.resolve(existing.latest);
  }

  return new Promise((resolve) => {
    let resolvedFirstValue = false;
    const entry: CacheEntry = {
      latest: undefined,
      pendingRegenerate: false,
      unsubscribe: () => {},
    };
    byKey.set(key, entry);

    subscribeRenderTemplate(
      hass,
      template,
      config.globals,
      config.macros,
      (event: JinjaboardSubscribeEvent) => {
        entry.latest = "error" in event ? buildErrorResult(event.error) : event.result;
        if (!resolvedFirstValue) {
          resolvedFirstValue = true;
          resolve(entry.latest);
        } else {
          entry.pendingRegenerate = true;
        }
      },
    ).then((unsubscribe) => {
      entry.unsubscribe = unsubscribe;
    });
  });
}

/**
 * Shared `static shouldRegenerate` for all three strategy files. For
 * `auto_update: false` (default), replicates the default registry-reference
 * check jinjaboard dashboards already get today. For `auto_update: true`,
 * checks-and-clears the pushed-update flag set by `getOrCreateSubscription`'s
 * subscription callback — no `hass`-state diffing happens here, the backend
 * already decided.
 */
export function shouldRegenerateJinjaboard(
  rawConfig: RawStrategyConfig,
  oldHass: HomeAssistant,
  newHass: HomeAssistant,
): boolean {
  const config = unwrapLegacyStrategyConfig(rawConfig);

  if (!config.auto_update) {
    const oldRegistries = oldHass as unknown as Record<string, unknown>;
    const newRegistries = newHass as unknown as Record<string, unknown>;
    return DEFAULT_REGISTRY_DEPENDENCIES.some((key) => oldRegistries[key] !== newRegistries[key]);
  }

  const entry = subscriptionCache.get(newHass.connection)?.get(cacheKey(config));
  if (!entry?.pendingRegenerate) {
    return false;
  }
  entry.pendingRegenerate = false;
  return true;
}
