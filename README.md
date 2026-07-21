# JinjaBoard

Author Home Assistant Lovelace dashboards as **YAML files with embedded
Jinja2**, rendered live by Home Assistant's own template engine — the same
one used by automations (`states()`, `areas()`, `devices()`, `labels()`, and
everything else) — and displayed through a custom Lovelace dashboard
strategy.

It's a spiritual successor to
[`hass-lovelace_gen`](https://github.com/thomasloven/hass-lovelace_gen), with
two differences:

- **Live, not pre-generated.** Your dashboard re-renders whenever you open or
  refresh it, instead of needing a script/service call to regenerate a static
  file.
- **Real Home Assistant templating.** JinjaBoard uses Home Assistant's actual
  template engine, so anything you can do in an automation template works
  here too — unlike JavaScript-based Jinja reimplementations that only see
  the frontend's cached state.

## Status

This is under active development. Implemented so far:

- ✅ Dashboards, views, and sections authored as plain YAML with embedded
  Jinja (`{{ }}` / `{% %}`)
- ✅ Lovelace dashboard, view, and section strategies
- ✅ Path-traversal protection, with clear error messages instead of a blank
  dashboard
- ✅ Splitting a dashboard across multiple files with `!include` and friends,
  mirroring [Home Assistant's own config-splitting
  tags](https://www.home-assistant.io/docs/configuration/splitting_configuration/)

Not yet implemented:

- ⛔ Root-level `vars:` block
- ⛔ Render caching
- ⛔ A polished in-dashboard error panel (errors currently render as a plain
  markdown card)

## Installation

Via [HACS](https://hacs.xyz/): add this repository as a custom repository
(category: Integration), then install "JinjaBoard".

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RomRider&repository=jinjaboard&category=integration)

After installing, go to **Settings → Devices & Services → Add Integration**
and add **JinjaBoard**. There's nothing to configure — this step just
activates the integration. Only one instance is needed per Home Assistant
install.

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
apply around any `{% for %}` / `{% if %}` blocks. The
[`yaml-jinja-highlight`](https://marketplace.visualstudio.com/items?itemName=samuelcolvin.jinjahtml)
VS Code extension is a good companion for editing these.

A whole-line comment (`#` as the first non-whitespace character) is safe to
use for commenting out Jinja you don't want evaluated, e.g.
`# - !include cards/lights.yaml.j2` or `# {{ some_var }}`. This doesn't apply
to a trailing `key: value  # comment`, and it never touches a markdown card's
`content: |` block, so a literal `# Heading` there is left alone.

### 2. Create a dashboard that uses it

Go to **Settings → Dashboards → Add Dashboard**, give it a name, then open it
and switch to **Edit in YAML** (top-right pencil menu). Replace the content
with:

```yaml
strategy:
  type: custom:jinjaboard
  template: jinjaboard/home.yaml.j2
  globals:
    some_var: 123
```

- `template` is a path to your file, relative to the Home Assistant config
  directory (`/config`).
- `globals` (optional) are made available in the template under
  `jjb.globals` — `some_var` above is read as `{{ jjb.globals.some_var }}`,
  not `{{ some_var }}`. This keeps your variables from accidentally clashing
  with Home Assistant's own built-in template variables (`states`, `now`,
  `area_id`, ...).

Save, and the dashboard renders your template's output. Re-opening the
dashboard (or reloading the page) re-renders it — JinjaBoard doesn't
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
      globals:
        some_var: 123
  - title: A normal, non-templated view
    cards:
      - type: markdown
        content: Nothing fancy here.
```

The template's rendered output replaces the view's own content (typically a
`cards:` list). Other view-level keys (`title`, `path`, `icon`, ...) are kept
unless your render's output sets them too. If this one view fails to render,
only that view shows an error — the rest of the dashboard is unaffected.

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
          globals:
            some_var: 123
```

Same behavior as the view strategy, one level down: a render failure only
shows an error card in that one section.

### Keeping a card's own live templating

Cards with native runtime templating — the markdown card's `content`, the
template card, tile card features — should have their Jinja stay _live_,
evaluated by the card itself rather than baked in when JinjaBoard renders.
Wrap those blocks in Jinja's own `{% raw %}...{% endraw %}` tag so JinjaBoard
leaves them untouched:

```yaml
- type: markdown
  content: >
    {% raw %}
    The kitchen light is {{ states('light.kitchen') }}.
    {% endraw %}
```

The literal `{{ }}` text ends up in the rendered dashboard config, and the
markdown card evaluates it live itself.

### Splitting a dashboard across files

JinjaBoard supports the same five tags as [Home Assistant's own config
splitting](https://www.home-assistant.io/docs/configuration/splitting_configuration/):
`!include`, `!include_dir_list`, `!include_dir_named`,
`!include_dir_merge_list`, `!include_dir_merge_named`. Unlike a plain HA
config file, an included file can itself contain Jinja, and includes can
nest arbitrarily deep.

```yaml
views:
  - title: Home
    cards:
      - !include cards/header.yaml.j2
      - !include_dir_list cards/lights
  - title: Named example
    cards: !include_dir_merge_list cards/climate
```

A few things worth knowing:

- **Paths are relative to the including file**, not the root template —
  `cards/header.yaml.j2` inside `home.yaml.j2` resolves next to `home.yaml.j2`
  itself, matching real HA's `!include`.
- **`vars:` are inherited separately from `globals:`.** An included file
  automatically sees whatever `vars:` the file that included it can see,
  exposed under `jjb.inc` (not `jjb.globals`). To pass something extra (or
  override a value for just that one include and everything nested under
  it), use the mapping form instead of a bare path:

  ```yaml
  - !include { path: cards/light.yaml.j2, vars: { area_id: kitchen } }
  ```

  Or if you prefer the block style:

  ```yaml
  - !include
    path: cards/light.yaml.j2
    vars:
      area_id: kitchen
  ```

  `cards/light.yaml.j2` reads this as `{{ jjb.inc.area_id }}` — the
  dashboard's own `globals:` (`jjb.globals`) stay visible alongside it.

- **Directory includes are recursive** and match `*.yaml`, `*.yml`,
  `*.yaml.j2`, and `*.yml.j2` (dotfiles and dot-directories are skipped). A
  plain `.yaml` file with no Jinja in it just renders unchanged, so static
  and templated snippets can live side by side.
- **`!include_dir_named`'s key** is the filename with its template extension
  stripped, e.g. `kitchen.yaml.j2` → `kitchen`.
- Circular includes and excessively deep include chains fail with a clear
  error naming the chain, rather than hanging or crashing.

## Migrating from lovelace_gen

If you're coming from `hass-lovelace_gen`, two things work differently:

- **`!include` args are a mapping, not a following array.** `lovelace_gen`
  passes template args to an include as a YAML sequence right after the tag.
  JinjaBoard instead uses the mapping form shown above, with an explicit
  `vars:` key:

  ```yaml
  # lovelace_gen
  - !include
    - cards/light.yaml.j2
    - area_id: kitchen

  # JinjaBoard
  - !include
    path: cards/light.yaml.j2
    vars:
      area_id: kitchen
  ```

  Inside the included file, read the value as `{{ jjb.inc.area_id }}` rather
  than a bare `{{ area_id }}`.

- **Global variables move from `configuration.yaml` into the dashboard
  file, and `_global` becomes `jjb.globals`.** `lovelace_gen` defines global
  vars once under its own key in `configuration.yaml`, available everywhere
  as `_global.some_var`. JinjaBoard has no equivalent global config — instead,
  put them under `globals:` in each dashboard's `strategy:` block (see
  [Usage](#2-create-a-dashboard-that-uses-it) above) and read them as
  `jjb.globals.some_var`:

  ```yaml
  # lovelace_gen (configuration.yaml)
  lovelace_gen:
    vars:
      some_var: 123
  # template
  {{ _global.some_var }}

  # JinjaBoard (dashboard strategy)
  strategy:
    type: custom:jinjaboard
    template: jinjaboard/home.yaml.j2
    globals:
      some_var: 123
  # template
  {{ jjb.globals.some_var }}
  ```

  If several dashboards need the same variables, repeat the `globals:`
  block in each one, or have each dashboard `!include` a shared file and pass
  the values down via `vars:`.

## Error handling

If a template fails to render or produces invalid YAML, the affected
dashboard, view, or section shows a markdown card with the error instead of
a blank screen. Error codes:

| Code                | Meaning                                                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `path_missing`      | The root template file doesn't exist or can't be read                                                                       |
| `path_traversal`    | A template or include path resolves outside the Home Assistant config directory                                             |
| `include_not_found` | An `!include`d file doesn't exist                                                                                           |
| `template_error`    | Jinja itself failed (syntax error, undefined variable/function, etc.), or an include problem was detected                   |
| `yaml_parse_error`  | The template rendered, but the result isn't valid YAML — usually an indentation issue around a `{% for %}`/`{% if %}` block |
| `render_timeout`    | (planned) rendering took too long                                                                                           |

## Development

This repo includes a devcontainer
(`romrider/hass-custom-devcontainer`) that runs a real Home Assistant
instance with this integration mounted at
`/config/custom_components/jinjaboard`, plus HACS and a demo platform for
test entities. `.devcontainer/test/jinjaboard/` holds example/fixture
templates used during development.

A `Makefile` at the repo root wraps the common commands — run `make help` to
list all targets.

```bash
make install       # install backend + frontend dependencies
make build          # bundle src/ into custom_components/jinjaboard/www/
make run            # start a real HA instance against /config (devcontainer only)
```

The built frontend bundle is `.gitignore`d and rebuilt as part of the release
workflow — don't commit it.

### Tests

```bash
make test            # backend + frontend
make test-backend    # pytest
make test-frontend   # vitest
make typecheck        # tsc --noEmit
```

Both suites also run in CI on every push and pull request.
