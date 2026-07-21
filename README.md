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
- ✅ `ll-strategy-view-jinjaboard` Lovelace view strategy (per-view, lazy
  generation)
- ✅ `ll-strategy-section-jinjaboard` Lovelace section strategy (per-section,
  lazy generation)
- ✅ Path-traversal guarding, typed error codes surfaced to the frontend
- ✅ `!include`/`!include_dir_list`/`!include_dir_named`/`!include_dir_merge_list`/
  `!include_dir_merge_named` — splitting a dashboard across multiple files,
  mirroring [Home Assistant's own config-splitting
  tags](https://www.home-assistant.io/docs/configuration/splitting_configuration/)

Not yet implemented (see the project plan for the full milestone list):

- ⛔ Root-level `vars:` block
- ⛔ Render caching
- ⛔ A polished in-dashboard error panel (errors currently render as a plain
  markdown card)

## Installation

Via [HACS](https://hacs.xyz/): add this repository as a custom repository
(category: Integration), then install "JinjaBoard".

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RomRider&repository=jinjaboard&category=integration)

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
- `variables` (optional) are made available in the template under the `jjb`
  namespace — `some_var` above is read as `{{ jjb.some_var }}`, not
  `{{ some_var }}`. This is deliberate: HA's template environment already
  defines a large set of its own globals (`states`, `now`, `area_id`, ...),
  and a bare top-level variable name could silently shadow one of them
  instead of erroring. Namespacing under `jjb` avoids that entirely, at the
  cost of one extra `jjb.` prefix.

Save, and the dashboard renders your template's output. Re-opening the
dashboard (or reloading the page) re-renders it — JinjaBoard does not
re-render on every entity state change, only on demand.

### 3. Use it as a view strategy

A `strategy:` can also be attached to a single view instead of the whole
dashboard — useful when only one view in an otherwise hand-authored
dashboard needs templating:

```yaml
views:
  - title: Lights
    strategy:
      type: custom:jinjaboard
      template: jinjaboard/lights_view.yaml.j2
      variables:
        some_var: 123
  - title: A normal, non-templated view
    cards:
      - type: markdown
        content: Nothing fancy here.
```

The template's rendered output replaces the view's own content (typically a
`cards:` list, optionally other view-level keys). Any sibling key already on
the view (`title`, `path`, `icon`, ...) is kept unless the render's own
output defines the same key, in which case the render wins. A render
failure in this view only shows an error card in that one view — the rest
of the dashboard, and any other views, are unaffected.

### 4. Use it as a section strategy

Inside a `type: sections` view, an individual section can likewise be
templated instead of the whole view:

```yaml
views:
  - title: Home
    type: sections
    sections:
      - type: grid
        cards:
          - type: markdown
            content: A normal, non-templated section.
      - column_span: 2
        strategy:
          type: custom:jinjaboard
          template: jinjaboard/climate_section.yaml.j2
          variables:
            some_var: 123
```

Same merge and error-isolation behavior as the view strategy, one level
down: sibling keys on the section (`column_span`, `title`, ...) are kept
unless the render's output overrides them, and a render failure only shows
an error card in that one section.

### Keeping a card's own live templating

Cards with native runtime templating — the markdown card's `content`, the
template card, tile card features — should have their Jinja stay _live_,
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

### Splitting a dashboard across files

JinjaBoard supports the same five tags as [Home Assistant's own config
splitting](https://www.home-assistant.io/docs/configuration/splitting_configuration/):
`!include`, `!include_dir_list`, `!include_dir_named`,
`!include_dir_merge_list`, `!include_dir_merge_named`. Unlike real HA config
files, an included file can itself contain Jinja — it's rendered exactly like
the root template before being parsed, so `!include`s can nest arbitrarily
deep.

```yaml
views:
  - title: Home
    cards:
      - !include cards/header.yaml.j2
      - !include_dir_list cards/lights
  - title: Named example
    cards: !include_dir_merge_list cards/climate
```

A few things that differ from a plain HA config file, worth knowing:

- **Paths are relative to the including file**, not the root template —
  `cards/header.yaml.j2` inside `home.yaml.j2` resolves next to `home.yaml.j2`
  itself, matching real HA's `!include`. Every resolved path is still
  guarded to stay inside the Home Assistant config directory, at every
  nesting level.
- **Variables are inherited.** An included file automatically sees whatever
  `variables` (and, once implemented, `vars:`) the file that included it can
  see — like Jinja's own `{% include %}` "with context" behavior. To pass
  something extra (or override a value) for just that one include, use the
  mapping form instead of a bare path:
  ```yaml
  - !include { path: cards/light.yaml.j2, vars: { area_id: kitchen } }
  ```
  Same `jjb.` namespacing as the root template's `variables:` applies —
  `cards/light.yaml.j2` reads this as `{{ jjb.area_id }}`.
- **Directory includes are recursive** and match `*.yaml`, `*.yml`,
  `*.yaml.j2`, and `*.yml.j2` (dotfiles and dot-directories are skipped).
  Every matched file is rendered through Jinja regardless of which pattern
  matched it — a plain `.yaml` file with no `{{ }}`/`{% %}` just renders
  unchanged, so static and templated snippets can live side by side.
- **`!include_dir_named`'s key** is the filename with its full recognized
  template extension stripped (`kitchen.yaml.j2` → `kitchen`), not just the
  last `.` segment.
- Circular includes and excessively deep include chains fail with a clear
  `template_error` naming the chain, rather than hanging or crashing.

## Error handling

If a template fails to render or produces invalid YAML, the affected
dashboard, view, or section shows a markdown card with the error instead of
a blank screen. Error codes:

| Code                | Meaning                                                                                                                                                                                                                                                     |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `path_missing`      | The root template file doesn't exist or can't be read                                                                                                                                                                                                       |
| `path_traversal`    | The root template, or an `!include`/`!include_dir_*` target inside it, resolves outside the Home Assistant config directory                                                                                                                                 |
| `include_not_found` | An `!include`d file doesn't exist                                                                                                                                                                                                                           |
| `template_error`    | Jinja itself failed (syntax error, undefined variable/function, etc.), or an include cycle / excessive include depth was detected — the message includes the template source line number where possible, and for nested includes, which file it happened in |
| `yaml_parse_error`  | The template rendered, but the result isn't valid YAML — usually an indentation issue around a `{% for %}`/`{% if %}` block, or an unrecognized `!tag`                                                                                                      |
| `render_timeout`    | (planned) rendering took too long                                                                                                                                                                                                                           |

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

### Tests

Backend (`pytest` + `pytest-homeassistant-custom-component`, installed into
the devcontainer's own `/home/vscode/.local/ha-venv` — done automatically on
container start, see `.devcontainer/install-deps.sh`):

```bash
uv pip install -r requirements-test.txt -p /home/vscode/.local/ha-venv/bin/python
/home/vscode/.local/ha-venv/bin/python -m pytest
```

Frontend (`vitest`):

```bash
cd src && npm install && npm run test
```

Both run in CI on every push and pull request (against a fresh, disposable
runner venv, unrelated to the devcontainer's).

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
