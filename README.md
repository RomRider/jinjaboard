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
  [template engine](https://www.home-assistant.io/docs/templating/), so
  anything you can do in an automation template works here too.

A dashboard is just a loop over whatever Home Assistant already knows about
your house, so it stops needing maintenance every time you add a device.
A few things people build with it (full versions in
[Real-world examples](#real-world-examples)):

- A room-by-room view that grows on its own — add a light, it appears next
  time you open the dashboard.
- A "needs attention" view collecting every low battery and unavailable
  entity in one place.
- A curated view driven by entity labels, re-organized from Home Assistant's
  UI instead of hand-edited YAML.

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

- ⛔ A polished in-dashboard error panel (errors currently render as a plain
  markdown card)
- ⛔ Automatic re-render on entity state change — for now, a dashboard only
  re-renders when you open or refresh the page (see [Usage](#2-create-a-dashboard-that-uses-it))

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
`/config/jinjaboard/home.yaml`:

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

> [!NOTE]
> This README names templates `.yaml` throughout for readability, but the
> extension is just a convention — any path works as a `template:`,
> `!include`, or `macros:` target. Naming a file `.yaml.j2` (or `.yml.j2`)
> instead works identically, and has the extra benefit that editors like VS
> Code recognize the `.j2` suffix automatically and apply Jinja+YAML syntax
> highlighting without extra per-project configuration.

A whole-line comment (`#` as the first non-whitespace character) is safe to
use for commenting out Jinja you don't want evaluated, e.g.
`# - !include cards/lights.yaml` or `# {{ some_var }}`. This doesn't apply
to a trailing `key: value  # comment`, and it never touches a markdown card's
`content: |` block, so a literal `# Heading` there is left alone.

### 2. Create a dashboard that uses it

Go to **Settings → Dashboards → Add Dashboard**, give it a name, then open it
and switch to **Edit in YAML** (top-right pencil menu). Replace the content
with:

```yaml
strategy:
  type: custom:jinjaboard
  template: jinjaboard/home.yaml
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
      template: jinjaboard/lights_view.yaml
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
          template: jinjaboard/climate_section.yaml
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
      - !include cards/header.yaml
      - !include_dir_list cards/lights
  - title: Named example
    cards: !include_dir_merge_list cards/climate
```

A few things worth knowing:

- **Paths are relative to the including file**, not the root template —
  `cards/header.yaml` inside `home.yaml` resolves next to `home.yaml`
  itself, matching real HA's `!include`.
- **`vars:` are inherited separately from `globals:`.** An included file
  automatically sees whatever `vars:` the file that included it can see,
  exposed under `jjb.inc` (not `jjb.globals`). To pass something extra (or
  override a value for just that one include and everything nested under
  it), use the mapping form instead of a bare path:

  ```yaml
  - !include { path: cards/light.yaml, vars: { area_id: kitchen } }
  ```

  Or if you prefer the block style:

  ```yaml
  - !include
    path: cards/light.yaml
    vars:
      area_id: kitchen
  ```

  `cards/light.yaml` reads this as `{{ jjb.inc.area_id }}` — the
  dashboard's own `globals:` (`jjb.globals`) stay visible alongside it.

- **Directory includes are recursive** and match `*.yaml`, `*.yml`,
  `*.yaml.j2`, and `*.yml.j2` (dotfiles and dot-directories are skipped). A
  plain `.yaml` file with no Jinja in it just renders unchanged, so static
  and templated snippets can live side by side.
- **`!include_dir_named`'s key** is the filename with its template extension
  stripped, e.g. `kitchen.yaml.j2` → `kitchen`.
- Circular includes and excessively deep include chains fail with a clear
  error naming the chain, rather than hanging or crashing.

### Macros

Jinja's own `{% macro %}...{% endmacro %}` works out of the box, within a
single file — root template or one `!include`d file:

```yaml
{% macro light_tile(entity_id) %}
type: tile
entity: {{ entity_id }}
{% endmacro %}
views:
  - title: Home
    cards:
      {{ light_tile('light.kitchen') }}
```

To reuse a macro **across files**, declare it under the strategy's `macros:`
key — a list of files and/or directories, resolved relative to the Home
Assistant config directory (like `template`, not like `!include`):

```yaml
strategy:
  type: custom:jinjaboard
  template: jinjaboard/home.yaml
  macros:
    - jinjaboard/macros/common.yaml   # a single file
    - jinjaboard/macros/kitchen/         # or a whole directory
```

Every macro from every declared file is callable directly as
`jjb.macros.<macro>(...)` — flattened across files, so which file a macro
happens to live in doesn't matter to how it's called; a directory entry is
walked recursively (same as `!include_dir_named`), and every macro from
every matched file lands in the same flat `jjb.macros`. Given
`jinjaboard/macros/common.yaml`:

```yaml
{% macro light_tile(entity_id) %}
type: tile
entity: {{ entity_id }}
{% endmacro %}
```

any file in the render tree — the root template or any `!include`d file —
can call it:

```yaml
views:
  - title: Home
    cards:
      {{ jjb.macros.light_tile('light.kitchen') }}
```

A few things worth knowing:

- **A macro file only sees `jjb.globals`, never `jjb.inc`.** Macro files are
  compiled once, up front, before any `!include` is walked, so there's no
  tree position to give it an `jjb.inc` value for — referencing
  `jjb.inc.<name>` inside a macro body raises `template_error`.
- **Two declared files defining a macro of the same name is an error**, not
  a silent shadow — rename one of the macros rather than relying on entry
  order. Filenames themselves never collide (they're not part of
  `jjb.macros`'s namespace), only the macro names inside them.
- A missing macro file or directory surfaces the same `include_not_found`
  error as a missing `!include` target.

## Real-world examples

**Every light, grouped by room, with zero upkeep.** The example under
[Write a template](#1-write-a-template) above is this in its simplest form —
loop over `areas()`, and a card appears for every light in every room. Add a
light, or a whole new room, in Home Assistant and it shows up next time you
open the dashboard; nothing to edit.

**A "needs attention" view.** Home Assistant already tracks battery levels
and availability for every entity — this just puts what it knows somewhere
you'll actually see it, instead of buried in Settings → Devices & Services.

```yaml
views:
  - title: Needs attention
    cards:
      - type: heading
        heading: Low battery
      {% for state in states.sensor
         if state.attributes.get('device_class') == 'battery'
         and state.state not in ('unknown', 'unavailable')
         and state.state | int(100) < 20 %}
      - type: tile
        entity: {{ state.entity_id }}
      {% endfor %}
      - type: heading
        heading: Unavailable
      {% for state in states if state.state == 'unavailable' %}
      - type: tile
        entity: {{ state.entity_id }}
      {% endfor %}
```

> [!IMPORTANT]
> This reflects state as of the last render, not live — open or refresh the
> dashboard to pick up a battery that dropped or a device that went
> unavailable since (see [Status](#status)).

**A curated view driven by labels, not YAML.** Tag entities with a label
from Home Assistant's own UI (**Settings → Areas, labels & zones →
Labels**), and this card renders whatever currently carries it — re-curate
the dashboard by relabeling entities in the UI instead of hand-editing
cards.

```yaml
views:
  - title: Favorites
    cards:
      {% for entity_id in label_entities('favorite') %}
      - type: tile
        entity: {{ entity_id }}
      {% endfor %}
```

## Migrating from lovelace_gen

If you're coming from `hass-lovelace_gen`, two things work differently:

- **`!include` args are a mapping, not a following array.** `lovelace_gen`
  passes template args to an include as a YAML sequence right after the tag.
  JinjaBoard instead uses the mapping form shown above, with an explicit
  `vars:` key:

  ```yaml
  # lovelace_gen
  - !include
    - cards/light.yaml
    - area_id: kitchen

  # JinjaBoard
  - !include
    path: cards/light.yaml
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
    template: jinjaboard/home.yaml
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
