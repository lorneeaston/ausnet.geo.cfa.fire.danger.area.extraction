#!/usr/bin/env python3
"""
Assemble the 81 CFA Fire Danger Period declaration areas into one polygon layer.

Inputs are the per-area GeoPDFs in files/municipalities_pdf/ and the vector
extracts in files/municipalities_geo/ produced by extract_municipalities_geo.sh,
plus Vicmap's lga_polygon pulled from the Victorian open data WFS.

Each source map draws its subject area *and* its neighbours in one unstructured
PDF layer with no attributes. Two facts make the subject recoverable:

  * only the subject area's outline closes into a polygon - neighbours are drawn
    as open paths that run off the map frame, so polygonizing the layer's
    linework yields the subject as the one large face;
  * the map frame (GeoPDF NEATLINE) is fitted to the subject, so its centroid
    falls inside that face. That is the discriminator, and it does not depend on
    the area's name or on drawing style.

    Note: the OGR_STYLE brush-vs-pen split suggested by earlier notes does NOT
    hold - every feature in these layers is PEN(c:#E64C00), stroke only.

Geometry then comes from the best available source:

  * 59 unsplit areas - the declaration area is the LGA, so the Vicmap polygon is
    used verbatim (authoritative, 1:25,000). geometry_source='vicmap'.
  * 22 areas from 10 councils split into sub-areas - the Vicmap parent supplies
    the outer boundary and only the internal dividing line comes from the PDF.
    That line is drawn dashed, so the dashes are extended to bridge their gaps
    before cutting. geometry_source='pdf'.

    pip install -r requirements.txt
    python assemble_fdp_areas.py
    python assemble_fdp_areas.py --refresh-vicmap

Geometry is a 2024/25-season snapshot. The legal instrument is the gazettal, not
these maps: https://www.cfa.vic.gov.au/warnings-restrictions/fire-danger-period/gazetted-details
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString
from shapely.ops import linemerge, polygonize, unary_union

REPO = Path(__file__).resolve().parent
PDF_DIR = REPO / "files" / "municipalities_pdf"
GEO_DIR = REPO / "files" / "municipalities_geo"
OUT_DIR = REPO / "output"
FACES_GPKG = REPO / "files" / "pdf_faces.gpkg"

WFS = "WFS:https://opendata.maps.vic.gov.au/geoserver/wfs"
WFS_LAYER = "open-data-platform:lga_polygon"

PREFIX = "LOCAL_MUNICIPALITY_RESTRICTION_MAP_"
EXPECTED_COUNT = 81  # 64 councils + 5 unincorporated + 12 extra rows from splits

# Slugs whose CFA wording differs from the Vicmap lga_name. Everything else
# resolves by longest-prefix match against the Vicmap names, so re-splits between
# seasons need no code change.
SPECIAL = {
    "BOROUGH_OF_QUEENSCLIFFE": "QUEENSCLIFFE",
    "FRENCH_ISLAND": "FRENCH-ELIZABETH-SANDSTONE ISLANDS (UNINC)",
    "FALLS_CREEK_ALPINE_RESORT": "FALLS CREEK ALPINE RESORT (UNINC)",
    "MOUNT_BULLER_ALPINE_RESORT": "MOUNT BULLER ALPINE RESORT (UNINC)",
    "MOUNT_HOTHAM_ALPINE_RESORT": "MOUNT HOTHAM ALPINE RESORT (UNINC)",
    "MOUNT_STIRLING_ALPINE_RESORT": "MOUNT STIRLING ALPINE RESORT (UNINC)",
}
# Unincorporated: no parent council, so lga_name stays null.
UNINCORPORATED = {v for k, v in SPECIAL.items() if v.endswith("(UNINC)")}

# The 15 LGAs wholly inside the former Metropolitan Fire District, where FDP
# restrictions do not apply. Only ever used to *check* the derived result.
EXPECTED_NO_FDP = {
    "MELBOURNE", "PORT PHILLIP", "YARRA", "STONNINGTON", "BOROONDARA", "GLEN EIRA",
    "BAYSIDE", "BRIMBANK", "DAREBIN", "HOBSONS BAY", "MARIBYRNONG", "MONASH",
    "MOONEE VALLEY", "MERRI-BEK", "WHITEHORSE",
}
# Unincorporated Vicmap areas with no CFA FDP map of their own.
EXPECTED_NO_FDP_UNINC = {
    "GABO ISLAND (UNINC)", "LAKE MOUNTAIN ALPINE RESORT (UNINC)",
    "MOUNT BAW BAW ALPINE RESORT (UNINC)",
}

# Cutting parameters, in metres. A dividing line is the PDF linework further than
# BOUNDARY_TOL from the Vicmap parent boundary; DASH_EXTEND bridges the gaps in
# the dashed rendering and carries the ends through the boundary.
BOUNDARY_TOL = 400.0
DASH_EXTEND = 3000.0
MIN_DASH = 200.0


class Failure(Exception):
    """An area could not be extracted. Never swallowed - a missing area is worse
    than a crash."""


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise Failure(f"{cmd[0]} failed: {p.stderr.strip()[:400]}")
    return p.stdout


def pdf_metadata(pdf: Path) -> dict:
    """NEATLINE polygon, PDF layer name and creation date for one source map."""
    info = run(["gdalinfo", str(pdf)])
    m = re.search(r"NEATLINE=(POLYGON.*)", info)
    if not m:
        raise Failure(f"{pdf.name}: no NEATLINE - the PDF is not georeferenced")
    layers = run(["ogrinfo", str(pdf)])
    names = re.findall(r"^\d+: (Layers_fdp_boundaries\S+)$", layers, re.M)
    names = [n for n in names if "Labels" not in n]
    if len(names) != 1:
        raise Failure(f"{pdf.name}: expected one boundary layer, found {names}")
    return {
        "neatline": wkt.loads(m.group(1)),
        "source_layer": names[0],
        "created": (re.search(r"CREATION_DATE=(\S+)", info) or [None, None])[1],
    }


def subject_face(slug: str, meta: dict) -> tuple[object, str]:
    """The subject area's polygon, recovered from the map's linework.

    Polygonizing closes the subject's outline; the neighbours stay open. The
    neatline centroid then picks the subject out of whatever faces result.

    Two areas are hooked around water (Mornington Peninsula, Borough of
    Queenscliffe) so their map-frame centroid lands offshore, in no face at all.
    They fall back to the largest face, which is still the subject - neighbours
    only ever close into small fragments. Returns (face, how it was picked).
    """
    src = GEO_DIR / f"{PREFIX}{slug}.geojson"
    if not src.exists():
        raise Failure(f"{slug}: missing extract {src} - run extract_municipalities_geo.sh")
    g = gpd.read_file(src)
    if g.empty:
        raise Failure(f"{slug}: extract has no features")
    faces = list(polygonize(unary_union(list(g.geometry))))
    if not faces:
        raise Failure(
            f"{slug}: the linework closed into no polygon at all - inspect the "
            "PDF layer by hand."
        )
    centre = meta["neatline"].centroid
    hit = [f for f in faces if f.contains(centre)]
    if hit:
        return max(hit, key=lambda f: f.area), "centroid"
    return max(faces, key=lambda f: f.area), "largest"


def resolve_parent(slug: str, vic_names: list[str]) -> tuple[str, str]:
    """(vicmap name, sub-area suffix) for a slug, by longest-prefix match."""
    if slug in SPECIAL:
        return SPECIAL[slug], ""
    words = slug.split("_")
    for n in range(len(words), 0, -1):
        cand = " ".join(words[:n])
        if cand in vic_names:
            return cand, " ".join(words[n:])
    raise Failure(f"{slug}: no Vicmap LGA matches this area name")


def extend_line(ls: LineString, d: float) -> LineString:
    """Extend both ends of a line by d metres along its terminal directions."""
    c = list(ls.coords)

    def beyond(a, b):
        n = np.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return (b[0] + (b[0] - a[0]) / n * d, b[1] + (b[1] - a[1]) / n * d)

    return LineString([beyond(c[1], c[0])] + c + [beyond(c[-2], c[-1])])


def split_parent(parent, faces: dict):
    """Cut the Vicmap parent polygon along the PDF-derived dividing lines.

    faces maps area_name -> the PDF subject face for that sub-area. The outer
    boundary stays Vicmap; only the internal cut is PDF-derived. Returns
    area_name -> geometry, tiling the parent exactly.
    """
    interior = unary_union([f.boundary for f in faces.values()]).difference(
        parent.boundary.buffer(BOUNDARY_TOL)
    )
    merged = linemerge(interior)
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    dashes = [
        p for p in parts
        if p.length > MIN_DASH and parent.contains(p.interpolate(0.5, normalized=True))
    ]
    if not dashes:
        raise Failure(
            f"no interior dividing line found for {sorted(faces)} - the split "
            "cannot be derived from the PDFs"
        )

    noded = unary_union([parent.boundary] + [extend_line(p, DASH_EXTEND) for p in dashes])
    pieces = [f for f in polygonize(noded) if parent.contains(f.representative_point())]

    # Extending the dashes can throw off spurious slivers; assign every piece to
    # the sub-area whose PDF face it sits in, then dissolve.
    buckets = {name: [] for name in faces}
    for piece in pieces:
        best = max(faces, key=lambda n: piece.intersection(faces[n]).area)
        buckets[best].append(piece)

    out = {}
    for name, ps in buckets.items():
        if not ps:
            raise Failure(f"{name}: the cut produced no area for this sub-area")
        out[name] = unary_union(ps).buffer(0)
    return out


def load_vicmap(cache: Path, refresh: bool) -> gpd.GeoDataFrame:
    if refresh or not cache.exists():
        print(f"Fetching {WFS_LAYER} from the Victorian open data WFS ...")
        cache.parent.mkdir(parents=True, exist_ok=True)
        run(["ogr2ogr", "-f", "GPKG", str(cache), "-t_srs", "EPSG:3111",
             "-nln", "lga", "-nlt", "MULTIPOLYGON", WFS, WFS_LAYER])
    g = gpd.read_file(cache, layer="lga")
    if g.crs is None or g.crs.to_epsg() != 3111:
        raise Failure(f"Vicmap cache is in {g.crs}, expected EPSG:3111")
    return g


def build(vicmap: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    pdfs = sorted(PDF_DIR.glob(f"{PREFIX}*.pdf"))
    if not pdfs:
        raise Failure(f"no source PDFs in {PDF_DIR} - run download_municipalities.py")
    slugs = [p.stem[len(PREFIX):] for p in pdfs]
    print(f"{len(slugs)} declaration areas found in {PDF_DIR}/")
    if len(slugs) != EXPECTED_COUNT:
        print(f"  note: expected {EXPECTED_COUNT}; CFA may have re-split areas.",
              file=sys.stderr)

    vic_names = list(vicmap.lga_name.dropna())
    vic_geom = dict(zip(vicmap.lga_name, vicmap.geometry))

    rows, failures = [], []
    for slug in slugs:
        try:
            meta = pdf_metadata(PDF_DIR / f"{PREFIX}{slug}.pdf")
            parent, suffix = resolve_parent(slug, vic_names)
            face, how = subject_face(slug, meta)
            rows.append({
                "slug": slug,
                "area_name": f"{parent} - {suffix}" if suffix else slug.replace("_", " "),
                "vicmap_name": parent,
                "suffix": suffix,
                "source_pdf": f"{PREFIX}{slug}.pdf",
                "source_layer": meta["source_layer"],
                "created": meta["created"],
                "pdf_face": face,
                "face_picked_by": how,
            })
        except Failure as exc:
            failures.append(f"{slug}: {exc}")
            print(f"  [FAIL] {slug}: {exc}", file=sys.stderr)
    if failures:
        raise Failure(f"{len(failures)} area(s) could not be extracted:\n  "
                      + "\n  ".join(failures))

    df = pd.DataFrame(rows)
    counts = df.vicmap_name.value_counts()
    df["is_split"] = df.vicmap_name.map(counts) > 1
    print(f"  {(~df.is_split).sum()} unsplit (Vicmap geometry), "
          f"{df.is_split.sum()} split across {counts[counts > 1].size} councils (PDF cut)")

    geoms, sources = {}, {}
    for _, r in df[~df.is_split].iterrows():
        geoms[r.slug] = vic_geom[r.vicmap_name]
        sources[r.slug] = "vicmap"

    for council, grp in df[df.is_split].groupby("vicmap_name"):
        parts = split_parent(vic_geom[council],
                             {r.slug: r.pdf_face for _, r in grp.iterrows()})
        for slug, geom in parts.items():
            geoms[slug] = geom
            sources[slug] = "pdf"
        print(f"    {council}: cut into {len(parts)} "
              f"({', '.join(f'{a/1e6:.0f} km2' for a in (g.area for g in parts.values()))})")

    df["geometry"] = df.slug.map(geoms)
    df["geometry_source"] = df.slug.map(sources)
    df["lga_name"] = df.vicmap_name.where(~df.vicmap_name.isin(UNINCORPORATED))
    # CFA's wording for the areas whose slug is not the council name.
    df.loc[df.slug == "BOROUGH_OF_QUEENSCLIFFE", "area_name"] = "BOROUGH OF QUEENSCLIFFE"
    df.loc[df.slug == "FRENCH_ISLAND", "area_name"] = "FRENCH ISLAND"

    gdf = gpd.GeoDataFrame(
        df[["area_name", "lga_name", "is_split", "source_pdf", "source_layer",
            "geometry_source", "geometry"]],
        geometry="geometry", crs="EPSG:3111",
    ).sort_values("area_name").reset_index(drop=True)
    return gdf, df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh-vicmap", action="store_true",
                    help="re-download lga_polygon instead of using the cache")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "fdp" / "lga.gpkg",
                    help="Vicmap cache (kept off /mnt: WSL SQLite locking is unreliable)")
    args = ap.parse_args()

    vicmap = load_vicmap(args.cache, args.refresh_vicmap)
    print(f"Vicmap: {len(vicmap)} areas in {vicmap.crs.to_string()}")

    gdf, detail = build(vicmap)
    OUT_DIR.mkdir(exist_ok=True)

    # GPKG is SQLite; writing it directly onto /mnt under WSL fails
    # intermittently with "unable to open database file". Build it in $HOME and
    # copy the finished file across.
    with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
        staged = Path(tmp) / "fdp_areas.gpkg"
        gdf.to_file(staged, layer="fdp_areas", driver="GPKG")
        shutil.copy(staged, OUT_DIR / "fdp_areas.gpkg")
    gdf.to_crs(4326).to_file(OUT_DIR / "fdp_areas.geojson", driver="GeoJSON")

    # Keep the per-area PDF faces for the validation step. An intermediate, not
    # a deliverable, so it lives under files/ rather than output/.
    faces = gpd.GeoDataFrame(
        detail[["area_name", "vicmap_name", "is_split", "face_picked_by",
                "created"]].copy(),
        geometry=list(detail.pdf_face), crs="EPSG:3111",
    )
    with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
        staged = Path(tmp) / "pdf_faces.gpkg"
        faces.to_file(staged, layer="pdf_faces", driver="GPKG")
        shutil.copy(staged, FACES_GPKG)

    print(f"\nWrote {len(gdf)} features to {OUT_DIR}/fdp_areas.gpkg (EPSG:3111) "
          f"and fdp_areas.geojson (EPSG:4326)")
    print(f"Source dataset: {sorted(set(detail.source_layer))}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Failure as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
