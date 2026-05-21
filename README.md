# agol-webmap-bridge

A Python CLI tool that converts an **ArcGIS Online (AGOL) AppConfiguration** into a
**GeoNode Map JSON** file.  The tool fetches the AppConfiguration from the AGOL REST API,
resolves the referenced webmap, retrieves all available datasets from a GeoNode instance,
matches operational layers by name, and writes the resulting GeoNode Map JSON to disk.

The converter is built on a pluggable writer abstraction so that support for additional output
formats (QGIS project, Mapbox GL JSON, …) can be added with minimal effort in the future.

---

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [CLI options](#cli-options)
- [Layer matching logic](#layer-matching-logic)
- [Supported AGOL webmap properties](#supported-agol-webmap-properties)
  - [Projection handling](#projection-handling)
  - [Group layer handling](#group-layer-handling)
- [Unsupported / future properties](#unsupported--future-properties)
  - [Unsupported features report](#unsupported-features-report)
- [How to POST the result to GeoNode](#how-to-post-the-result-to-geonode)
- [Extending with a new writer](#extending-with-a-new-writer)
- [Running the tests](#running-the-tests)
- [Possible future extensions](#possible-future-extensions)

---

## Features

- Fetches an AGOL AppConfiguration by item GUID via the public REST API, validates
  that it is of type `webmap`, extracts the title and webmap GUID, and then fetches
  the actual webmap.
- Paginates the GeoNode `/api/v2/datasets/` endpoint to retrieve all available datasets.
- Matches each AGOL operational layer to the most suitable GeoNode dataset using
  fuzzy name comparison (`difflib.SequenceMatcher`).  The search term is derived
  from the layer URL (see [Layer matching logic](#layer-matching-logic)).
  Unmatched layers are skipped with a warning log message.
- Produces a GeoNode-compatible Map JSON file that can be directly POSTed to the
  GeoNode Maps API.
- Meaningful output filename derived from the webmap title (slugified).
- Prompts before overwriting an existing output file; `--force` skips the prompt.
- Configurable output directory and matching threshold.
- Pluggable `BaseWriter` abstraction for adding new output formats.

---

## Installation

```bash
# Clone the repository
git clone https://github.com/bertt/agol-webmap-bridge.git
cd agol-webmap-bridge

# Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install the package
pip install -e .
```

For development (includes `pytest` and `requests-mock`):

```bash
pip install -e ".[dev]"
```

---

## Usage

```bash
agol-webmap-bridge APP_CONFIGURATION_GUID --geonode-url GEONODE_URL [OPTIONS]
```

**Example:**

```bash
agol-webmap-bridge 2b214417eea74ae9a56119c251ffa960 \
  --geonode-url https://your-geonode.example.com \
  --output-dir output \
  --match-threshold 0.6
```

This will:

1. Fetch the AppConfiguration at `https://www.arcgis.com/sharing/rest/content/items/2b214417eea74ae9a56119c251ffa960/data`
2. Validate that `type == "webmap"`, extract the title and webmap GUID (e.g. `8a9a419b704e4e03bb98d9f14226a743`)
3. Fetch the webmap at `https://www.arcgis.com/sharing/rest/content/items/8a9a419b704e4e03bb98d9f14226a743/data`
4. Fetch all datasets from `https://your-geonode.example.com/api/v2/datasets/`
5. Match layers by name and write the result to `output/<webmap-title>_geonode.json`

---

## CLI options

| Option | Short | Default | Description |
|---|---|---|---|
| `APP_CONFIGURATION_GUID` | — | *(required)* | AGOL item GUID of the AppConfiguration |
| `--geonode-url` | `-g` | *(required)* | Base URL of the GeoNode instance |
| `--output-dir` | `-o` | `output` | Directory to write the output JSON file |
| `--force` | `-f` | off | Overwrite existing output without prompting |
| `--match-threshold` | — | `0.6` | Min similarity ratio (0–1) for layer matching |
| `--log-level` | — | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `-h` / `--help` | — | — | Show help message |

---

## Layer matching logic

The tool resolves each AGOL operational layer to a GeoNode dataset by deriving a
**search term from the layer URL** and comparing it (case-insensitively, underscores
preserved) against the GeoNode `name` field of every dataset.

### Regular layers

For a layer whose URL is:

```
https://rijnland.enl-mcs.nl/arcgis/rest/services/Gebied/my_layer/MapServer/0
```

the segment immediately before `/MapServer` (or `/FeatureServer`, etc.) is extracted:

```
my_layer   →   search term: my_layer
```

This is compared against `name` values in GeoNode, e.g.:

| GeoNode `name` | Match? |
|---|---|
| `my_layer` | ✅ score 1.00 |
| `My_Layer` | ✅ score 1.00 (case-insensitive) |
| `other_layer` | ❌ score too low |

### Sublayers (ArcGISMapServiceLayer)

When a MapServer service exposes multiple sublayers (via `layers[]` in the webmap JSON),
each sublayer has no own URL — only the parent service URL is known.  In that case
the search term becomes **`<parent_service_name>_<sublayer_title>`**, with spaces in
the sublayer title replaced by underscores:

| Parent service URL | Sublayer title | Search term |
|---|---|---|
| `…/Legger_regionale_kering_vigerend/MapServer` | `Buitenbeschermingszone` | `legger_regionale_kering_vigerend_buitenbeschermingszone` |
| `…/Legger_regionale_kering_vigerend/MapServer` | `Kernzone` | `legger_regionale_kering_vigerend_kernzone` |

The expected GeoNode dataset `name` for these layers therefore follows the pattern
`<ParentService>_<SublayerTitle>`, e.g. `Legger_regionale_kering_vigerend_Buitenbeschermingszone`.

### Fallback

Layers with no URL (and no parent URL) are matched on their `title` field using
standard fuzzy matching.

### Logging

Run with `--log-level DEBUG` to see every individual candidate comparison:

```
DEBUG agol_webmap_bridge.matcher: Layer 'Buitenbeschermingszone' search candidates: ['legger_regionale_kering_vigerend_buitenbeschermingszone']
DEBUG agol_webmap_bridge.matcher:   'legger_regionale_kering_vigerend_buitenbeschermingszone' vs 'legger_regionale_kering_vigerend_buitenbeschermingszone' (dataset 'Legger_regionale_kering_vigerend_Buitenbeschermingszone') → 1.00
```

---

## Supported AGOL webmap properties

| AGOL property | Maps to GeoNode field | Notes |
|---|---|---|
| `title` (item metadata) | `title` | Passed via `--webmap-title` or taken from the webmap JSON |
| `operationalLayers[].title` | `maplayers[].dataset.title` | Matched fuzzy to GeoNode dataset name |
| `operationalLayers[].opacity` | `maplayers[].opacity` | 0–1 float preserved |
| `operationalLayers[].visibility` | `maplayers[].visibility` | Boolean preserved |
| `initialState.viewpoint.targetGeometry` | `extent` | `[xmin, ymin, xmax, ymax]` |
| `spatialReference.wkid` / `latestWkid` | `srid` | Converted to `EPSG:<code>` string |
| `baseMap.title` | `abstract` | Stored as `"Basemap: …"` in abstract field |
| Group layers (`GroupLayer`) | — | Sub-layers are flattened and matched individually |
| `ArcGISMapServiceLayer` with `layers[]` | `maplayers[]` (flat) | Leaf sublayers are extracted and matched individually; group nodes (`subLayerIds` present) are skipped; opacity/visibility inherited from the service layer |

### Projection handling

The output GeoNode map **always uses `EPSG:3857`** (Web Mercator) as its projection,
regardless of the spatial reference defined in the AGOL webmap.

If the AGOL webmap uses a different CRS (e.g. `EPSG:28992` — Dutch RD New), the
`center` point and `maxExtent` bounding box are automatically reprojected to
`EPSG:3857` using [pyproj](https://pyproj4.github.io/pyproj/).  Both the
`map.projection` and `map.center.crs` fields in the output JSON are set to
`"EPSG:3857"`.

This ensures compatibility with GeoNode's default Web Mercator tile infrastructure.

---

### Group layer handling

AGOL webmaps can contain **GroupLayers** and **ArcGISMapServiceLayers with sublayers**.
The tool maps these to a nested group structure in GeoNode (MapStore2), preserving the
original AGOL hierarchy as closely as possible.

#### How AGOL layer types are mapped

| AGOL layer type | Behaviour |
|---|---|
| `GroupLayer` | The group title becomes a parent group in GeoNode; its children are processed recursively |
| `ArcGISMapServiceLayer` with `layers[]` | The service title becomes a sub-group; leaf sublayers are extracted and matched individually; internal group nodes (`subLayerIds`) are skipped |
| `ArcGISFeatureLayer` / other leaf layers | Matched directly; placed in their enclosing group (if any) |
| Top-level layers (no parent group) | Placed in MapStore2's built-in **Default** group |

#### Nesting and dot-notation

Group membership in the GeoNode JSON is expressed using **dot-notation** group IDs.
A layer inside `GroupLayer "Legger"` → `ArcGISMapServiceLayer "Zonering"` receives the
group ID `"Legger.Zonering"`.  The `groups` array in the output JSON reflects this
nested structure:

```json
"groups": [
  {
    "id": "Legger",
    "title": "Legger",
    "expanded": true,
    "nodes": [
      { "id": "Legger.Zonering", "title": "Zonering", "expanded": true, "nodes": [] }
    ]
  }
]
```

Ancestor groups are created automatically — if only a deeply nested layer is present,
all intermediate parent groups are inserted.

#### TOC order

The GeoNode layers panel (TOC) mirrors the display order of the original AGOL webmap:

- Layers are written in reverse array order in the JSON so that MapStore2 renders them
  top-to-bottom in the same order as AGOL.
- The built-in **Default** group (top-level layers without a parent group) always appears
  **at the bottom** of the TOC, below all named groups.
- The **OpenStreetMap** basemap is placed in MapStore2's `background` group so it
  appears in the basemap switcher rather than the main layers panel.

---

## Unsupported / future properties

The following AGOL webmap features are **not yet converted**.  They are ignored silently
or noted in comments.  Contributions or later phases may add support for them.

| AGOL feature | Status |
|---|---|
| Basemap layer references | Not converted; title stored in abstract only |
| Renderer / symbology (JSON) | Not converted |
| Popup configuration (`popupInfo`) | Not converted |
| Field configurations | Not converted |
| Bookmarks | Not converted |
| Non-spatial tables (`tables[]`) | Not converted |
| Time-aware layer settings | Not converted |
| Nested group layers (> 1 level) | Only one level of flattening applied for `GroupLayer` |
| `subLayerIds` group structure in GeoNode output | Not preserved — GeoNode `maplayers` is a flat list; group nodes are skipped and only leaf sublayers are included |
| `mapFloorInfo` / indoor positioning | Not converted |
| Private/secured AGOL webmaps (token auth) | Not supported |

### Unsupported features report

After every conversion the CLI automatically scans the AGOL webmap and prints a
report of any unsupported features it found, together with the layer they belong to.

**Example output — issues found:**

```
⚠  Unsupported AGOL features detected (not converted):
   • Bookmarks  [webmap level]
   • Renderer / symbology  [layer: Grens Rijnland]
   • Popup configuration (popupInfo)  [layer: Woningbouwlocaties]
   • Time-aware layer settings  [layer: Woningbouwlocaties]
```

**Example output — nothing to report:**

```
✓  No unsupported features detected.
```

The following conditions are checked automatically:

| Check | Scope |
|---|---|
| `bookmarks` present | Webmap level |
| `tables[]` present | Webmap level |
| `mapFloorInfo` present | Webmap level |
| `renderer` present on layer | Per layer |
| `popupInfo` present on layer | Per layer |
| `layerDefinition.definitionExpression` set | Per layer |
| `timeInfo` present on layer | Per layer |
| `layerDefinition.fields` present on layer | Per layer |
| Nested `GroupLayer` (> 1 level deep) | Per layer |

---

## How to POST the result to GeoNode

The output JSON file is ready to be POSTed to the GeoNode Maps API.

**Using curl:**

```bash
curl -X POST https://your-geonode/api/v2/maps/ \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d @output/my_webmap_geonode.json
```

**Using Python (`requests`):**

```python
import json
import requests

with open("output/my_webmap_geonode.json") as f:
    map_json = json.load(f)

response = requests.post(
    "https://your-geonode/api/v2/maps/",
    headers={
        "Authorization": "Bearer <your-token>",
        "Content-Type": "application/json",
    },
    json=map_json,
)
response.raise_for_status()
print("Created map:", response.json())
```

You can obtain an API token from your GeoNode instance at `/api/v2/auth-token/` using Basic Auth.

---

## Extending with a new writer

To add a new output format, subclass `BaseWriter`:

```python
# agol_webmap_bridge/writers/my_custom_writer.py
from pathlib import Path
from agol_webmap_bridge.writers.base_writer import BaseWriter

class MyCustomWriter(BaseWriter):
    def write(self, map_config: dict, path: Path) -> None:
        # map_config keys: title, abstract, srid, extent, layers[]
        # Each layer: { geonode_dataset, opacity, visibility }
        ...
```

Then pass it to `convert()`:

```python
from agol_webmap_bridge.converter import convert
from my_custom_writer import MyCustomWriter

map_config = convert(agol_webmap, geonode_datasets, writer=MyCustomWriter(), threshold=0.6)
```

---

## Running the tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

All tests use mocked HTTP responses via `requests-mock`; no network access is required.

---

## Possible future extensions

- **Direct GeoNode upload** (`--upload` flag): POST the generated JSON to the GeoNode API automatically.
- **Authenticated AGOL access**: support private webmaps using an AGOL token (`--agol-token`).
- **Symbology conversion**: translate AGOL renderer JSON to SLD/GeoServer styles.
- **QGIS project writer**: write a `.qgs` / `.qgz` project file.
- **Mapbox GL JSON writer**: produce a Mapbox-compatible style document.
- **Basemap conversion**: map AGOL basemap IDs to OSM/XYZ tile URLs.
- **Bookmark conversion**: translate AGOL bookmarks to GeoNode saved extents.
- **Batch conversion**: accept a list of GUIDs and convert them in one run.
