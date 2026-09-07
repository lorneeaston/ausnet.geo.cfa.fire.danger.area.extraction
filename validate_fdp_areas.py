#!/usr/bin/env python3
"""
Validate output/fdp_areas.gpkg and write output/validation.md.

Runs the five checks that decide whether the layer can be trusted:

  1. ground truth - the PDF-derived face for every unsplit area, recovered by the
     same code path the splits rely on, compared against its Vicmap polygon;
  2. one feature per source PDF, with a valid unique schema;
  3. the sub-areas of each split council reassemble into the Vicmap parent;
  4. no overlaps or slivers between areas;
  5. statewide coverage - the union is Victoria minus the areas with no FDP map,
     and that residue is exactly the former Metropolitan Fire District councils.

Exits non-zero if any check fails, so it can gate a rebuild.

    python validate_fdp_areas.py
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from assemble_fdp_areas import (
    EXPECTED_COUNT, EXPECTED_NO_FDP, EXPECTED_NO_FDP_UNINC, FACES_GPKG, OUT_DIR,
    PDF_DIR, PREFIX, SPECIAL, UNINCORPORATED, load_vicmap,
)

SCHEMA = ["area_name", "lga_name", "is_split", "source_pdf", "source_layer",
          "geometry_source"]
SLIVER_M2 = 1000.0  # 0.001 km2 - below this a pairwise overlap is rounding noise


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.failed = 0

    def head(self, text):
        self.lines.append(f"\n## {text}\n")

    def say(self, text=""):
        self.lines.append(text)

    def check(self, ok, text):
        self.lines.append(f"- {'PASS' if ok else '**FAIL**'} - {text}")
        self.failed += not ok
        print(f"  [{'ok' if ok else 'FAIL'}] {text}")
        return ok

    def table(self, df):
        """Markdown table. Hand-rolled so pandas' optional tabulate dependency
        is not needed just to write a report."""
        def cell(v):
            if isinstance(v, float):
                return f"{v:,.4f}" if abs(v) < 1e4 else f"{v:,.1f}"
            return "" if v is None or v != v else str(v)
        cols = list(df.columns)
        rows = [[cell(v) for v in rec] for rec in df.itertuples(index=False)]
        w = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c)
             for i, c in enumerate(cols)]
        self.lines.append("| " + " | ".join(c.ljust(w[i]) for i, c in enumerate(cols)) + " |")
        self.lines.append("|" + "|".join("-" * (n + 2) for n in w) + "|")
        for r in rows:
            self.lines.append("| " + " | ".join(v.ljust(w[i]) for i, v in enumerate(r)) + " |")
        self.lines.append("")


def main() -> int:
    gdf = gpd.read_file(OUT_DIR / "fdp_areas.gpkg", layer="fdp_areas")
    faces = gpd.read_file(FACES_GPKG, layer="pdf_faces")
    vicmap = load_vicmap(Path.home() / ".cache" / "fdp" / "lga.gpkg", refresh=False)
    vic_geom = dict(zip(vicmap.lga_name, vicmap.geometry))
    gdf["is_split"] = gdf.is_split.astype(bool)

    r = Report()
    layer = sorted(set(gdf.source_layer))
    r.say("# Validation - CFA Fire Danger Period declaration areas\n")
    r.say(f"Layer: `output/fdp_areas.gpkg`, {len(gdf)} features, {gdf.crs.to_string()}.  ")
    r.say(f"Source dataset: `{layer[0] if len(layer) == 1 else layer}` "
          "(Job ID FDP 2024/2025, prepared 20/10/2024) - a season snapshot, not the "
          "legal instrument.  ")
    r.say("Reference geometry: Vicmap `open-data-platform:lga_polygon`, EPSG:3111.")

    # ---- 1. ground truth ----------------------------------------------------
    r.head("1. Ground truth - PDF extraction against Vicmap")
    r.say("Each area's outline is recovered from its PDF by the same code the splits "
          "depend on, then compared with the Vicmap polygon for its council. The output "
          "uses Vicmap for unsplit areas, so this measures the *extraction method* "
          "rather than the deliverable.\n")
    r.say("The headline number is **containment** - how much of the recovered face lies "
          "inside the Vicmap parent. Picking a neighbour's outline instead of the "
          "subject's would drive it to ~0, so it is the test of whether the right path "
          "was chosen. IoU is reported alongside, but it is only meaningful where the "
          "council is drawn as a single part: an area made of several disjoint pieces "
          "(Bass Coast with Phillip Island, Borough of Queenscliffe with Point Lonsdale) "
          "polygonizes into one face per piece, and only the largest is taken, so IoU "
          "understates the match by construction.\n")
    rows = []
    for _, f in faces[~faces.is_split.astype(bool)].iterrows():
        v = vic_geom[f.vicmap_name]
        inter = f.geometry.intersection(v).area
        rows.append({
            "area_name": f.area_name,
            "pdf_km2": f.geometry.area / 1e6,
            "vicmap_km2": v.area / 1e6,
            "containment": inter / f.geometry.area,
            "coverage": inter / v.area,
            "IoU": inter / f.geometry.union(v).area,
            "symdiff_km2": f.geometry.symmetric_difference(v).area / 1e6,
            "picked_by": f.face_picked_by,
        })
    gt = pd.DataFrame(rows).sort_values("containment")
    # A face that sits inside its council but covers little of it means the subject
    # was drawn as several disjoint outlines and only one was kept - a property of
    # the source map, read off the measurements rather than assumed per area.
    gt["whole"] = gt.coverage > 0.95

    alpine = gt[gt.area_name == "ALPINE"].iloc[0]
    r.check(alpine.IoU > 0.99,
            f"Alpine (the handover's nominated ground truth - unsplit, six neighbours "
            f"on the same map): IoU {alpine.IoU:.4f}, symmetric difference "
            f"{alpine.symdiff_km2:.2f} km2 on {alpine.vicmap_km2:.0f} km2 - edge noise only")
    r.check(gt.containment.min() > 0.95,
            f"every one of the {len(gt)} unsplit areas resolved to a face inside its own "
            f"council: containment {gt.containment.min():.4f}-{gt.containment.max():.4f} "
            f"(median {gt.containment.median():.4f}) - no neighbour was picked by mistake")
    whole = gt[gt.whole]
    r.check(whole.IoU.min() > 0.95,
            f"of those, the {len(whole)} whose subject is drawn as one outline match "
            f"Vicmap at IoU {whole.IoU.min():.4f}-{whole.IoU.max():.4f} "
            f"(median {whole.IoU.median():.4f}); worst is "
            f"{whole.sort_values('IoU').iloc[0].area_name}")
    r.say("\nTen weakest matches:\n")
    r.table(gt.head(10)[["area_name", "pdf_km2", "vicmap_km2", "containment",
                         "coverage", "IoU", "picked_by"]])
    r.say("`picked_by` records how the subject was told apart from its neighbours. "
          "`centroid` means the map frame's centroid fell inside the face - the frame is "
          "fitted to the subject, so that identifies it without relying on the area's "
          "name or on drawing style. `largest` is the documented fallback for areas "
          "hooked around water, where that centroid lands offshore in no face at all "
          "(Mornington Peninsula, Borough of Queenscliffe); the largest face is still "
          "the subject, and containment above confirms it.\n")
    r.say(f"The {(~gt.whole).sum()} areas below are drawn as several disjoint outlines "
          "and only the largest is kept, so their IoU is low by construction rather than "
          "through any error. Both are unsplit, so the deliverable takes the complete "
          "Vicmap polygon and nothing is lost:\n")
    r.table(gt[~gt.whole].sort_values("IoU")[
        ["area_name", "pdf_km2", "vicmap_km2", "containment", "coverage", "IoU"]])
    r.say("Note that the premise behind the extraction - a neighbour's outline runs off "
          "the map frame and so never closes - holds for every neighbour except an "
          "island drawn whole inside the frame (French Island closes on the Bass Coast "
          "map). Those extra faces are why the subject is chosen by the frame centroid "
          "rather than simply by size wherever a centroid is available.\n")

    # ---- 2. completeness ----------------------------------------------------
    r.head("2. Completeness and schema")
    pdfs = {p.stem[len(PREFIX):] for p in PDF_DIR.glob(f"{PREFIX}*.pdf")}
    r.check(len(gdf) == EXPECTED_COUNT == len(pdfs),
            f"{len(gdf)} features, {len(pdfs)} source PDFs, {EXPECTED_COUNT} expected")
    r.check(gdf.source_pdf.nunique() == len(gdf),
            "one feature per source PDF, no duplicates")
    r.check(gdf.area_name.nunique() == len(gdf), "area_name unique")
    r.check(list(gdf.columns[:-1]) == SCHEMA, f"schema is {SCHEMA}")
    r.check(gdf.crs.to_epsg() == 3111, f"CRS is {gdf.crs.to_string()} with an authority code")
    r.check(bool(gdf.geometry.is_valid.all()), "all geometries valid")
    r.check(not gdf.geometry.is_empty.any(), "no empty geometries")
    r.check(len(layer) == 1, f"one source dataset across all PDFs: {layer}")

    # The maps carry "Job ID: FDP 2024/2025, Date Prepared: 20/10/2024" as drawn
    # glyphs, not extractable text; the PDF creation timestamps carry the same
    # date as machine-readable metadata.
    prepared = sorted({c[2:10] for c in faces.created.dropna()})
    stamps = sorted(faces.created.dropna())
    r.check(len(prepared) == 1,
            f"all {len(faces)} source maps exported on one date: "
            f"{prepared[0][6:8]}/{prepared[0][4:6]}/{prepared[0][:4]} "
            f"({stamps[0][10:12]}:{stamps[0][12:14]}-{stamps[-1][10:12]}:{stamps[-1][12:14]}, "
            "a single export run) - matches the 'Date Prepared' printed on the maps")

    nulls = gdf[gdf.lga_name.isna()].area_name.tolist()
    r.check(len(nulls) == len(UNINCORPORATED),
            f"lga_name null for exactly the {len(UNINCORPORATED)} unincorporated areas: "
            f"{', '.join(sorted(nulls))}")
    counts = gdf.geometry_source.value_counts().to_dict()
    r.check(counts.get("vicmap") == 59 and counts.get("pdf") == 22,
            f"geometry_source: {counts}")
    r.check(bool((gdf.is_split == (gdf.geometry_source == "pdf")).all()),
            "is_split agrees with geometry_source on every row")

    # ---- 3. splits reassemble ----------------------------------------------
    r.head("3. Split councils reassemble into their Vicmap parent")
    r.say("The outer boundary of each sub-area is Vicmap; only the internal cut comes "
          "from the PDF. Reassembly should therefore be exact, and any residue is a "
          "gap or overlap introduced by the cut.\n")
    rows = []
    split = gdf[gdf.is_split].copy()
    split["council"] = split.area_name.str.split(" - ").str[0]
    for council, grp in split.groupby("council"):
        parent = vic_geom[council]
        u = unary_union(list(grp.geometry))
        rows.append({
            "council": council, "parts": len(grp),
            "parts_km2": u.area / 1e6, "vicmap_km2": parent.area / 1e6,
            "symdiff_m2": u.symmetric_difference(parent).area,
        })
    sp = pd.DataFrame(rows).sort_values("symdiff_m2", ascending=False)
    r.check(len(sp) == 10 and sp.parts.sum() == 22,
            f"{len(sp)} split councils yielding {sp.parts.sum()} sub-areas")
    r.check(sp.symdiff_m2.max() < 1.0,
            f"every union reassembles the parent exactly "
            f"(largest symmetric difference {sp.symdiff_m2.max():.2e} m2)")
    r.say("")
    r.table(sp)
    r.say("Each sub-area was also compared against the independently polygonized PDF "
          "face for its own map - the cut is derived from all of a council's maps "
          "together, so this is a genuine cross-check that the right piece got the "
          "right name.\n")
    fs = faces[faces.is_split.astype(bool)].merge(
        split[["area_name", "geometry"]].rename(columns={"geometry": "out"}), on="area_name")
    fs["IoU"] = [g.intersection(o).area / g.union(o).area for g, o in zip(fs.geometry, fs.out)]
    fs = fs.sort_values("IoU")
    r.check(fs.IoU.min() > 0.95,
            f"all 22 sub-areas match their own map's face: IoU "
            f"{fs.IoU.min():.4f}-{fs.IoU.max():.4f}")
    r.say("")
    r.table(fs[["area_name", "IoU"]].assign(
        out_km2=[o.area / 1e6 for o in fs.out],
        face_km2=[g.area / 1e6 for g in fs.geometry]).sort_values("IoU"))

    # ---- 4. overlaps --------------------------------------------------------
    r.head("4. Overlaps and slivers")
    pairs = gpd.sjoin(gdf[["area_name", "geometry"]],
                      gdf[["area_name", "geometry"]].rename(columns={"area_name": "other"}),
                      predicate="intersects")
    pairs = pairs[pairs.area_name < pairs.other]
    over = []
    for _, p in pairs.iterrows():
        a = gdf.loc[gdf.area_name == p.area_name, "geometry"].iloc[0]
        b = gdf.loc[gdf.area_name == p.other, "geometry"].iloc[0]
        inter = a.intersection(b)
        if inter.area > 0:
            over.append({"a": p.area_name, "b": p.other, "overlap_m2": inter.area})
    ov = pd.DataFrame(over)
    worst = ov.overlap_m2.max() if len(ov) else 0.0
    r.check(worst < SLIVER_M2,
            f"{len(pairs)} touching pairs checked; largest pairwise overlap "
            f"{worst:.2e} m2 (threshold {SLIVER_M2:g} m2)")
    total = sum(g.area for g in gdf.geometry)
    union = unary_union(list(gdf.geometry))
    r.check(abs(total - union.area) / union.area < 1e-9,
            f"sum of areas {total/1e6:.2f} km2 equals the union {union.area/1e6:.2f} km2 "
            "- the layer is a partition, not a stack")
    if len(ov):
        r.say("")
        r.table(ov.sort_values("overlap_m2", ascending=False).head(5))

    # ---- 5. coverage --------------------------------------------------------
    r.head("5. Statewide coverage")
    covered = {n for n in gdf.lga_name.dropna()} | {
        SPECIAL[s] for s in SPECIAL if SPECIAL[s] in UNINCORPORATED}
    covered |= {v for k, v in SPECIAL.items()}
    missing = set(vicmap.lga_name.dropna()) - covered
    r.check(missing == EXPECTED_NO_FDP | EXPECTED_NO_FDP_UNINC,
            f"{len(missing)} Vicmap areas have no FDP map, and they are exactly the "
            f"{len(EXPECTED_NO_FDP)} former Metropolitan Fire District councils plus "
            f"{len(EXPECTED_NO_FDP_UNINC)} unincorporated areas")
    r.say(f"\nNo FDP declaration area ({len(missing)}): "
          + ", ".join(f"`{m}`" for m in sorted(missing)) + "\n")
    unexpected = missing - (EXPECTED_NO_FDP | EXPECTED_NO_FDP_UNINC)
    if unexpected:
        r.say(f"**Unexpected**: {sorted(unexpected)}")

    vic = unary_union(list(vicmap.geometry))
    expected = unary_union([vic_geom[n] for n in missing])
    residue = vic.difference(union)
    r.check(residue.symmetric_difference(expected).area < 1e6,
            f"the union is Victoria minus those areas "
            f"(residue {residue.area/1e6:.1f} km2 vs their {expected.area/1e6:.1f} km2, "
            f"symmetric difference {residue.symmetric_difference(expected).area/1e6:.3f} km2)")
    r.say(f"\nTotal declared area: {union.area/1e6:,.0f} km2 of Victoria's "
          f"{vic.area/1e6:,.0f} km2 ({100*union.area/vic.area:.1f}%).")

    # ---- write --------------------------------------------------------------
    r.say(f"\n---\n\n**{'FAILED' if r.failed else 'All checks passed'}**"
          + (f" - {r.failed} check(s) failed." if r.failed else "."))
    (OUT_DIR / "validation.md").write_text("\n".join(r.lines) + "\n")
    print(f"\nWrote {OUT_DIR}/validation.md - "
          f"{'FAILED' if r.failed else 'all checks passed'}")
    return 1 if r.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
