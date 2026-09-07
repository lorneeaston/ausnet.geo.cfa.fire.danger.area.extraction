# Validation - CFA Fire Danger Period declaration areas

Layer: `output/fdp_areas.gpkg`, 81 features, EPSG:3111.  
Source dataset: `Layers_fdp_boundaries20241017_final` (Job ID FDP 2024/2025, prepared 20/10/2024) - a season snapshot, not the legal instrument.  
Reference geometry: Vicmap `open-data-platform:lga_polygon`, EPSG:3111.

## 1. Ground truth - PDF extraction against Vicmap

Each area's outline is recovered from its PDF by the same code the splits depend on, then compared with the Vicmap polygon for its council. The output uses Vicmap for unsplit areas, so this measures the *extraction method* rather than the deliverable.

The headline number is **containment** - how much of the recovered face lies inside the Vicmap parent. Picking a neighbour's outline instead of the subject's would drive it to ~0, so it is the test of whether the right path was chosen. IoU is reported alongside, but it is only meaningful where the council is drawn as a single part: an area made of several disjoint pieces (Bass Coast with Phillip Island, Borough of Queenscliffe with Point Lonsdale) polygonizes into one face per piece, and only the largest is taken, so IoU understates the match by construction.

- PASS - Alpine (the handover's nominated ground truth - unsplit, six neighbours on the same map): IoU 0.9968, symmetric difference 15.34 km2 on 4791 km2 - edge noise only
- PASS - every one of the 59 unsplit areas resolved to a face inside its own council: containment 0.9660-0.9994 (median 0.9988) - no neighbour was picked by mistake
- PASS - of those, the 57 whose subject is drawn as one outline match Vicmap at IoU 0.9652-0.9990 (median 0.9972); worst is CASEY

Ten weakest matches:

| area_name                    | pdf_km2    | vicmap_km2 | containment | coverage | IoU    | picked_by |
|------------------------------|------------|------------|-------------|----------|--------|-----------|
| CASEY                        | 410.6559   | 397.0573   | 0.9660      | 0.9991   | 0.9652 | centroid  |
| FRENCH ISLAND                | 175.6984   | 170.7827   | 0.9693      | 0.9972   | 0.9668 | centroid  |
| BOROUGH OF QUEENSCLIFFE      | 5.4768     | 10.4652    | 0.9800      | 0.5129   | 0.5076 | largest   |
| WYNDHAM                      | 541.3966   | 537.5963   | 0.9911      | 0.9981   | 0.9892 | centroid  |
| MOUNT BULLER ALPINE RESORT   | 22.5504    | 22.5108    | 0.9925      | 0.9943   | 0.9869 | centroid  |
| SOUTH GIPPSLAND              | 3,327.0405 | 3,311.2280 | 0.9938      | 0.9985   | 0.9923 | centroid  |
| MORNINGTON PENINSULA         | 728.8790   | 728.3686   | 0.9942      | 0.9949   | 0.9892 | largest   |
| WARRNAMBOOL                  | 120.7195   | 120.5277   | 0.9956      | 0.9972   | 0.9929 | centroid  |
| MOUNT STIRLING ALPINE RESORT | 26.8176    | 26.7900    | 0.9960      | 0.9970   | 0.9931 | centroid  |
| KINGSTON                     | 91.4999    | 91.6415    | 0.9968      | 0.9953   | 0.9921 | centroid  |

`picked_by` records how the subject was told apart from its neighbours. `centroid` means the map frame's centroid fell inside the face - the frame is fitted to the subject, so that identifies it without relying on the area's name or on drawing style. `largest` is the documented fallback for areas hooked around water, where that centroid lands offshore in no face at all (Mornington Peninsula, Borough of Queenscliffe); the largest face is still the subject, and containment above confirms it.

The 2 areas below are drawn as several disjoint outlines and only the largest is kept, so their IoU is low by construction rather than through any error. Both are unsplit, so the deliverable takes the complete Vicmap polygon and nothing is lost:

| area_name               | pdf_km2  | vicmap_km2 | containment | coverage | IoU    |
|-------------------------|----------|------------|-------------|----------|--------|
| BOROUGH OF QUEENSCLIFFE | 5.4768   | 10.4652    | 0.9800      | 0.5129   | 0.5076 |
| BASS COAST              | 766.5113 | 865.9615   | 0.9975      | 0.8829   | 0.8810 |

Note that the premise behind the extraction - a neighbour's outline runs off the map frame and so never closes - holds for every neighbour except an island drawn whole inside the frame (French Island closes on the Bass Coast map). Those extra faces are why the subject is chosen by the frame centroid rather than simply by size wherever a centroid is available.


## 2. Completeness and schema

- PASS - 81 features, 81 source PDFs, 81 expected
- PASS - one feature per source PDF, no duplicates
- PASS - area_name unique
- PASS - schema is ['area_name', 'lga_name', 'is_split', 'source_pdf', 'source_layer', 'geometry_source']
- PASS - CRS is EPSG:3111 with an authority code
- PASS - all geometries valid
- PASS - no empty geometries
- PASS - one source dataset across all PDFs: ['Layers_fdp_boundaries20241017_final']
- PASS - all 81 source maps exported on one date: 20/10/2024 (15:23-15:32, a single export run) - matches the 'Date Prepared' printed on the maps
- PASS - lga_name null for exactly the 5 unincorporated areas: FALLS CREEK ALPINE RESORT, FRENCH ISLAND, MOUNT BULLER ALPINE RESORT, MOUNT HOTHAM ALPINE RESORT, MOUNT STIRLING ALPINE RESORT
- PASS - geometry_source: {'vicmap': 59, 'pdf': 22}
- PASS - is_split agrees with geometry_source on every row

## 3. Split councils reassemble into their Vicmap parent

The outer boundary of each sub-area is Vicmap; only the internal cut comes from the PDF. Reassembly should therefore be exact, and any residue is a gap or overlap introduced by the cut.

- PASS - 10 split councils yielding 22 sub-areas
- PASS - every union reassembles the parent exactly (largest symmetric difference 4.49e-07 m2)

| council            | parts | parts_km2  | vicmap_km2 | symdiff_m2 |
|--------------------|-------|------------|------------|------------|
| HINDMARSH          | 2     | 7,522.7998 | 7,522.7998 | 0.0000     |
| SOUTHERN GRAMPIANS | 3     | 6,653.0960 | 6,653.0960 | 0.0000     |
| INDIGO             | 2     | 2,041.5815 | 2,041.5815 | 0.0000     |
| BULOKE             | 2     | 7,999.8096 | 7,999.8096 | 0.0000     |
| ARARAT             | 2     | 4,208.9299 | 4,208.9299 | 0.0000     |
| PYRENEES           | 2     | 3,434.1029 | 3,434.1029 | 0.0000     |
| HORSHAM            | 2     | 4,262.9095 | 4,262.9095 | 0.0000     |
| WANGARATTA         | 2     | 3,646.4958 | 3,646.4958 | 0.0000     |
| WEST WIMMERA       | 2     | 9,108.7090 | 9,108.7090 | 0.0000     |
| YARRIAMBIACK       | 3     | 7,325.5675 | 7,325.5675 | 0.0000     |

Each sub-area was also compared against the independently polygonized PDF face for its own map - the cut is derived from all of a council's maps together, so this is a genuine cross-check that the right piece got the right name.

- PASS - all 22 sub-areas match their own map's face: IoU 0.9713-0.9990

| area_name                    | IoU    | out_km2    | face_km2   |
|------------------------------|--------|------------|------------|
| SOUTHERN GRAMPIANS - NORTH   | 0.9713 | 268.6293   | 273.1922   |
| WANGARATTA - NORTH WEST      | 0.9945 | 669.5423   | 671.4291   |
| HORSHAM - SOUTH              | 0.9947 | 1,462.9115 | 1,459.6967 |
| INDIGO - SOUTH EAST          | 0.9949 | 1,363.8409 | 1,362.1592 |
| SOUTHERN GRAMPIANS - CENTRAL | 0.9950 | 3,775.4362 | 3,777.1058 |
| SOUTHERN GRAMPIANS - SOUTH   | 0.9952 | 2,609.0304 | 2,607.4620 |
| INDIGO - NORTH WEST          | 0.9955 | 677.7406   | 678.5187   |
| PYRENEES - SOUTH             | 0.9971 | 508.8498   | 508.9674   |
| BULOKE - NORTH               | 0.9981 | 4,623.3795 | 4,622.5547 |
| WANGARATTA - SOUTH EAST      | 0.9983 | 2,976.9536 | 2,976.9681 |
| WEST WIMMERA - SOUTH         | 0.9984 | 2,789.1787 | 2,789.9480 |
| ARARAT - NORTH               | 0.9985 | 1,724.2698 | 1,723.8024 |
| YARRIAMBIACK - SOUTH         | 0.9985 | 1,184.5048 | 1,185.0881 |
| PYRENEES - NORTH             | 0.9985 | 2,925.2531 | 2,925.2345 |
| HORSHAM - NORTH              | 0.9985 | 2,799.9981 | 2,800.6568 |
| YARRIAMBIACK - NORTH         | 0.9986 | 3,795.5389 | 3,794.8493 |
| WEST WIMMERA - NORTH         | 0.9987 | 6,319.5303 | 6,318.7036 |
| ARARAT - SOUTH               | 0.9987 | 2,484.6600 | 2,485.9832 |
| HINDMARSH - NORTH            | 0.9989 | 3,199.9313 | 3,199.3030 |
| BULOKE - SOUTH               | 0.9990 | 3,376.4301 | 3,377.0448 |
| HINDMARSH - SOUTH            | 0.9990 | 4,322.8685 | 4,323.1824 |
| YARRIAMBIACK - CENTRAL       | 0.9990 | 2,345.5238 | 2,345.2154 |


## 4. Overlaps and slivers

- PASS - 193 touching pairs checked; largest pairwise overlap 2.29e-04 m2 (threshold 1000 m2)
- PASS - sum of areas 226972.33 km2 equals the union 226972.33 km2 - the layer is a partition, not a stack

| a               | b                       | overlap_m2 |
|-----------------|-------------------------|------------|
| HUME            | WHITTLESEA              | 0.0002     |
| BULOKE - SOUTH  | YARRIAMBIACK - NORTH    | 0.0000     |
| BULOKE - SOUTH  | YARRIAMBIACK - CENTRAL  | 0.0000     |
| BENALLA         | WANGARATTA - NORTH WEST | 0.0000     |
| HORSHAM - SOUTH | NORTHERN GRAMPIANS      | 0.0000     |


## 5. Statewide coverage

- PASS - 18 Vicmap areas have no FDP map, and they are exactly the 15 former Metropolitan Fire District councils plus 3 unincorporated areas

No FDP declaration area (18): `BAYSIDE`, `BOROONDARA`, `BRIMBANK`, `DAREBIN`, `GABO ISLAND (UNINC)`, `GLEN EIRA`, `HOBSONS BAY`, `LAKE MOUNTAIN ALPINE RESORT (UNINC)`, `MARIBYRNONG`, `MELBOURNE`, `MERRI-BEK`, `MONASH`, `MOONEE VALLEY`, `MOUNT BAW BAW ALPINE RESORT (UNINC)`, `PORT PHILLIP`, `STONNINGTON`, `WHITEHORSE`, `YARRA`

- PASS - the union is Victoria minus those areas (residue 762.6 km2 vs their 762.6 km2, symmetric difference 0.000 km2)

Total declared area: 226,972 km2 of Victoria's 227,735 km2 (99.7%).

---

**All checks passed**.
