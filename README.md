# CFA Fire Danger Period declaration areas

Victoria's 81 Fire Danger Period (FDP) declaration areas as a single polygon
layer, assembled from CFA's per-area restriction maps and Vicmap's LGA
boundaries, with the validation behind it.

The 81 areas are not the 79 LGAs: 64 councils where CFA declares an FDP (the 79
minus the 15 wholly inside the former Metropolitan Fire District), 5
unincorporated areas (French Island and the Falls Creek, Mount Buller, Mount
Hotham and Mount Stirling alpine resorts), and 12 extra rows from 10 councils
split into sub-areas.

Geometry is a **2024/25-season snapshot** (`fdp_boundaries20241017_final`,
Job ID FDP 2024/2025, all 81 maps exported 20/10/2024). The legal instrument is
the gazettal, not these maps:
<https://www.cfa.vic.gov.au/warnings-restrictions/fire-danger-period/gazetted-details>

## Prerequisites

1. Install `WSL (Ubuntu)`

2. Install `uv`

```bash
sudo snap install astral-uv --classic
```

3. Install `GDAL`

```bash
sudo apt-get update && sudo apt-get install -y libgdal-dev gdal-bin
uv pip install --python .venv/bin/python -r requirements.txt
```

4. Create a `venv`:

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Pipeline

| Step | Script | Does |
|---|---|---|
| 1 | `download_municipalities.py` | Scrapes the CFA index page, fetches the 81 source GeoPDFs into `files/municipalities_pdf/` |
| 2 | `check_municipalities.sh` | Confirms georeferencing is present |
| 3 | `extract_municipalities_geo.sh` | Per-file layer discovery + `ogr2ogr` into `files/municipalities_geo/` |
| 4 | `assemble_fdp_areas.py` | Builds the layer: `output/fdp_areas.gpkg`, `output/fdp_areas.geojson` |
| 5 | `validate_fdp_areas.py` | Runs the checks, writes `output/validation.md`, exits non-zero on failure |
| 6 | `visualise_fdp_areas.py` | Writes `output/map.html` and `output/splits.png` |

Steps 4-6 are re-runnable from the files already on disk:

```bash
python assemble_fdp_areas.py && python validate_fdp_areas.py && python visualise_fdp_areas.py
```

`assemble_fdp_areas.py --refresh-vicmap` re-pulls the LGA boundaries; otherwise
they come from `~/.cache/fdp/lga.gpkg`.

## Outputs

| File | |
|---|---|
| `output/fdp_areas.gpkg` | 81 polygons, EPSG:3111, layer `fdp_areas` |
| `output/fdp_areas.geojson` | the same, EPSG:4326 |
| `output/validation.md` | all checks with their numbers |
| `output/map.html` | interactive map, toggleable Vicmap LGA overlay |
| `output/splits.png` | the two three-way splits against their parent outline |

Schema: `area_name`, `lga_name` (null for the 5 unincorporated areas),
`is_split`, `source_pdf`, `source_layer`, `geometry_source`.

## How the subject area is separated from its neighbours

Each map draws its subject area *and* its neighbours in one unstructured PDF
layer with no attributes — the Alpine map also draws East Gippsland, Indigo,
Wangaratta, Towong, Wellington and Mansfield. Two facts make the subject
recoverable without reading any names:

- a neighbour's outline runs off the map frame and never closes, so
  **polygonizing the layer's linework yields the subject as a closed face**;
- the GeoPDF `NEATLINE` is fitted to the subject, so **its centroid falls inside
  that face**.

Geometry then comes from the best available source:

- **59 unsplit areas** — the declaration area *is* the LGA, so the Vicmap polygon
  is used verbatim (authoritative, 1:25,000). `geometry_source='vicmap'`.
- **22 split areas** from 10 councils — the Vicmap parent supplies the outer
  boundary and only the internal dividing line comes from the PDF, so the
  authoritative edge is preserved and only the cut is PDF-derived.
  `geometry_source='pdf'`.

## Source-data gotchas

Three properties of the source PDFs that are easy to undo by accident:

- **`-a_srs EPSG:3111` in `extract_municipalities_geo.sh` is mandatory, not
  decorative.** The PDFs are GDA94/VicGrid94, but GDAL reports them as
  `CONVERSION["unnamed"]` with no EPSG code. An unnamed WKT propagates
  downstream and breaks tools that expect an authority code, so the SRS is
  asserted on extraction. `validate_fdp_areas.py` checks the output CRS still
  carries its authority code.
- **The PDF layer name is not stable.** It is
  `Layers_fdp_boundaries<date>_final`, where the date belongs to the source
  dataset (currently 20241017) and changes between seasons. Both
  `extract_municipalities_geo.sh` and `assemble_fdp_areas.py` discover it per
  file; never hardcode it. It is carried into the output as `source_layer` so
  every row records which dataset it came from.
- **The repo is on `/mnt/d` under WSL, where SQLite locking is unreliable.**
  GPKG writes there fail intermittently with `unable to open database file`, so
  `assemble_fdp_areas.py` builds each GPKG under `$HOME` and copies the finished
  file across. The Vicmap cache lives at `~/.cache/fdp/lga.gpkg` for the same
  reason.

## Findings that differ from the original handover notes

Three assumptions in `HANDOVER.md` did not survive contact with the data. All
three are handled in the code, but they matter if the pipeline is re-pointed at
a later season.

- **`OGR_STYLE` is not a discriminator.** The expectation was a `BRUSH(...)` fill
  on the subject and stroke-only neighbours. In fact *every* feature in these
  layers is `PEN(c:#E64C00)` — stroke only, one colour, no fills anywhere. The
  polygonize-plus-neatline method above replaces it.
- **The internal dividing lines are drawn dashed.** They arrive as dozens of
  1-4 km fragments, so they do not cut the parent polygon as they stand;
  `assemble_fdp_areas.py` extends each dash to bridge the gaps before cutting.
- **The unincorporated areas *are* in `lga_polygon`.** All five appear, under
  `... (UNINC)` names, so no PDF fallback geometry was needed for them.

Two smaller quirks, both documented in `output/validation.md`:

- Mornington Peninsula and Borough of Queenscliffe hook around water, so their
  map-frame centroid lands offshore in no face at all. They fall back to the
  largest face.
- The "neighbours never close" premise holds except for an island drawn whole
  inside the frame — French Island closes on the Bass Coast map — which is why
  the frame centroid, not size, is the primary discriminator.

## Results

All checks pass (`python validate_fdp_areas.py`, exit 0):

- Alpine, the nominated ground truth, matches Vicmap at **IoU 0.9968**
  (symmetric difference 15.3 km² on 4,791 km² — edge noise).
- All 59 unsplit areas resolve to a face inside their own council
  (containment 0.966-0.999), so no neighbour was picked by mistake anywhere.
- All 22 sub-areas match the independently polygonized face from their own map
  at **IoU 0.971-0.999**.
- Every split council reassembles into its Vicmap parent exactly (largest
  symmetric difference 4.5e-07 m²).
- The layer is a partition: largest pairwise overlap 2.3e-04 m².
- The union is **226,972 km²**, Victoria minus exactly the 15 former
  Metropolitan Fire District councils and 3 unincorporated areas with no FDP map.

## Worth doing next

The PDF layer name names a real source dataset, `fdp_boundaries20241017_final`.
Requesting it from CFA's spatial team would replace steps 1-4 with authoritative
geometry for all 81 areas *including the splits*, which are the only PDF-derived
part of this layer. The dataset name and date make that a very specific ask.

Related published data: `CFA_DISTRICT` (21), `CFA_REGION` (5) and
`CFA_TFB_DISTRICT` are in Vicmap Admin under an open licence;
`CFA_BRIGADE_RESPONSE_AREA` is brigade level but restricted, requested via
CFA/DTP.

`maps.cfa.vic.gov.au/arcgis/rest/services/GC_VIC/CFA_Datasets/MapServer` exposes
`CFA_Districts` (0) and `LGA` (2) publicly, but cached at 1:1M and so likely
generalised — useful as a cross-check, not as a geometry source.
