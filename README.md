# JinjaBoard

Author Home Assistant Lovelace dashboards as **YAML files with embedded
Jinja2**, rendered live by Home Assistant's own template engine — the same
engine, functions, and filters available to automations (`states()`,
`areas()`, `devices()`, `labels()`, and everything else) — and displayed
through a custom Lovelace [dashboard
strategy](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-strategy/).

It's a spiritual successor to
[`hass-lovelace_gen`](https://github.com/thomasloven/hass-lovelace_gen), with
two differences:

- **Live, not pre-generated.** `lovelace_gen` renders your templates to a
  static YAML file via a script/service call. JinjaBoard renders on demand,
  through an authenticated WebSocket API, when you open (or refresh) the
  dashboard.
- **Real automation templating.** JinjaBoard renders through
  `homeassistant.helpers.template.Template` — the actual engine, sandbox, and
  function set HA uses for automations — not a JavaScript reimplementation of
  Jinja running against the frontend's cached state (which is what
  [`ha-nunjucks`](https://github.com/iantrich/ha-nunjucks)-based tools do).

## Status

This is under active development. Implemented so far:

- ✅ Config flow (single-instance, no fields — just enables the integration)
- ✅ `jinjaboard/render` WebSocket command: resolves a template path, renders
  it, returns the parsed structure
- ✅ Templates authored as plain YAML with embedded Jinja (`{{ }}` / `{% %}`),
  the same convention `lovelace_gen` used
- ✅ `ll-strategy-dashboard-jinjaboard` Lovelace dashboard strategy
- ✅ Path-traversal guarding, typed error codes surfaced to the frontend

Not yet implemented (see the project plan for the full milestone list):

- ⛔ `!include path {params}` — splitting a dashboard across multiple files
- ⛔ Root-level `vars:` block
- ⛔ `ll-strategy-view-jinjaboard` (per-view, lazy generation)
- ⛔ Render caching
- ⛔ A polished in-dashboard error panel (errors currently render as a plain
  markdown card)

## Installation

Via [HACS](https://hacs.xyz/): add this repository as a custom repository
(category: Integration), then install "JinjaBoard".

After installing, go to **Settings → Devices & Services → Add Integration**
and add **JinjaBoard**. There's nothing to configure — this step just enables
the integration (registers the WebSocket command and the frontend resource).
Only one instance is needed per Home Assistant install.

## Usage

### 1. Write a template

Templates are plain YAML files with Jinja mixed in, living anywhere under
your Home Assistant config directory (`/config`). For example,
`/config/jinjaboard/home.yaml.j2`:

```yaml
views:
  - title: Home
    cards:
      {% for a in areas() %}
      - type: heading
        heading: {{ area_name(a) }}
      {% for entity_id in area_entities(a) if entity_id.startswith("light.") %}
      - type: tile
        entity: {{ entity_id }}
      {% endfor %}
      {% endfor %}
```

The rendered output is parsed as YAML, so ordinary YAML indentation rules
apply around any `{% for %}` / `{% if %}` blocks — the same tradeoff
`lovelace_gen` has. The
[`yaml-jinja-highlight`](https://marketplace.visualstudio.com/items?itemName=samuelcolvin.jinjahtml)
VS Code extension is a good companion for editing these.

### 2. Create a dashboard that uses it

Go to **Settings → Dashboards → Add Dashboard**, give it a name, then open it
and switch to **Edit in YAML** (top-right pencil menu). Replace the content
with:

```yaml
strategy:
  type: custom:jinjaboard
  template: jinjaboard/home.yaml.j2
  variables:
    some_var: 123
```

- `template` is a path to your file, **relative to the Home Assistant config
  directory** (`/config`). It's validated on every render and can't escape
  that directory.
- `variables` (optional) is passed into the template exactly like an
  automation's `variables:` block.

Save, and the dashboard renders your template's output. Re-opening the
dashboard (or reloading the page) re-renders it — JinjaBoard does not
re-render on every entity state change, only on demand.

### Keeping a card's own live templating

Cards with native runtime templating — the markdown card's `content`, the
template card, tile card features — should have their Jinja stay *live*,
evaluated by the card itself, not baked in at generation time. Wrap those
blocks in Jinja's own `{% raw %}...{% endraw %}` tag:

```yaml
- type: markdown
  content: >
    {% raw %}
    The kitchen light is {{ states('light.kitchen') }}.
    {% endraw %}
```

`{% raw %}` is a core Jinja2 feature, independent of HA's sandboxing, so it
passes straight through JinjaBoard's render untouched — the literal `{{ }}`
text ends up in the rendered dashboard config, and the markdown card
evaluates it itself via its own `render_template` subscription.

## Error handling

If a template fails to render or produces invalid YAML, the dashboard shows
a markdown card with the error instead of a blank screen. Error codes:

| Code | Meaning |
|---|---|
| `path_missing` | The template file doesn't exist or can't be read |
| `path_traversal` | The path resolves outside the Home Assistant config directory |
| `template_error` | Jinja itself failed (syntax error, undefined function, etc.) |
| `yaml_parse_error` | The template rendered, but the result isn't valid YAML — usually an indentation issue around a `{% for %}`/`{% if %}` block |
| `include_not_found` | (planned) an `!include`d file is missing |
| `render_timeout` | (planned) rendering took too long |

## Development

This repo includes a devcontainer
(`romrider/hass-custom-devcontainer`) that runs a real Home Assistant
instance with this integration mounted at
`/config/custom_components/jinjaboard`, plus HACS and a demo platform for
test entities. `.devcontainer/test/jinjaboard/` holds example/fixture
templates used during development.

Frontend source lives in `src/` (TypeScript, bundled with
[esbuild](https://esbuild.github.io/)):

```bash
cd src
npm install
npm run typecheck   # tsc --noEmit
npm run build        # bundles to custom_components/jinjaboard/www/jinjaboard-strategy.js
```

The built bundle is `.gitignore`d and rebuilt as part of the release
workflow — don't commit it.

## Why not `add_extra_js_url`?

If you're reading the source: the frontend bundle is registered as a
[Lovelace resource](https://www.home-assistant.io/dashboards/resources/)
(`hass.data[LOVELACE_DATA].resources`) rather than via the more commonly used
`homeassistant.components.frontend.add_extra_js_url`. That was a deliberate,
tested choice: `add_extra_js_url` embeds a classic
`<script>import(url)</script>` tag in the server-rendered HTML, and that
dynamic import is unreliable in Firefox specifically — it can silently never
resolve, which makes Lovelace's dashboard-strategy loader hit its hardcoded
5-second timeout ("Timeout waiting for strategy element ... to be
registered"). Registering as a Lovelace resource goes through
home-assistant-frontend's own `loadModule()` (a real
`<script type="module" src="...">` element), which tested reliably in both
Chrome and Firefox.
