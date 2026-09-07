#!/usr/bin/env python3
"""
Build the visual checks over output/fdp_areas.gpkg.

  output/map.html   - all 81 declaration areas on a basemap, split (PDF-derived)
                      areas coloured apart from unsplit (Vicmap) ones, with the
                      Vicmap LGA boundaries as a toggleable overlay. The overlay
                      is the point of the map: where an unsplit area is drawn,
                      its edge should sit exactly on the LGA line, so any
                      daylight between them is a discrepancy worth chasing.
  output/splits.png - the two three-way splits, Yarriambiack and Southern
                      Grampians, against their parent LGA outline. Split cuts
                      are the PDF-derived part of the layer and the most likely
                      place for an error, so they get a static figure at a
                      readable zoom.

Geometry is simplified for the web map only (SIMPLIFY_M); the GeoJSON and GPKG
deliverables keep full Vicmap resolution.

    python visualise_fdp_areas.py
"""

import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from assemble_fdp_areas import OUT_DIR, load_vicmap

SIMPLIFY_M = 120.0  # metres, EPSG:3111 - well under the width of a map pixel at
                    # statewide zoom, and the full-resolution files are untouched
PDF_FILL, VICMAP_FILL = "#e6550d", "#3182bd"
LGA_LINE = "#111111"


def web_map(gdf: gpd.GeoDataFrame, vicmap: gpd.GeoDataFrame) -> Path:
    small = gdf.copy()
    small["geometry"] = small.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
    small = small.to_crs(4326)
    lga = vicmap[["lga_name", "geometry"]].copy()
    lga["geometry"] = lga.geometry.simplify(SIMPLIFY_M, preserve_topology=True)
    lga = lga.to_crs(4326)

    minx, miny, maxx, maxy = small.total_bounds
    m = folium.Map(tiles=None, control_scale=True)
    # OpenStreetMap, not CartoDB: Carto's tiles now require an API key, which
    # would leave the map blank for anyone opening the file.
    folium.TileLayer("OpenStreetMap", name="Basemap", control=False,
                     opacity=0.55).add_to(m)

    def style(feat):
        pdf = feat["properties"]["geometry_source"] == "pdf"
        return {"fillColor": PDF_FILL if pdf else VICMAP_FILL,
                "color": PDF_FILL if pdf else VICMAP_FILL,
                "weight": 1, "fillOpacity": 0.45 if pdf else 0.3}

    folium.GeoJson(
        small,
        name="FDP declaration areas (81)",
        style_function=style,
        highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.7},
        tooltip=folium.GeoJsonTooltip(fields=["area_name"], labels=False,
                                      sticky=True, style="font-weight:600"),
        popup=folium.GeoJsonPopup(
            fields=["area_name", "lga_name", "geometry_source", "source_pdf"],
            aliases=["Declaration area", "Parent council", "Geometry from", "Source map"],
            max_width=380),
    ).add_to(m)

    folium.GeoJson(
        lga,
        name="Vicmap LGA boundaries (overlay)",
        style_function=lambda f: {"color": LGA_LINE, "weight": 1.4,
                                  "fillOpacity": 0, "dashArray": "4,3"},
        tooltip=folium.GeoJsonTooltip(fields=["lga_name"], labels=False),
    ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])

    n_pdf = int((gdf.geometry_source == "pdf").sum())
    legend = f"""
    <div style="position:fixed;bottom:22px;left:12px;z-index:9999;background:#fff;
                border:1px solid #999;border-radius:4px;padding:10px 12px;
                font:12px/1.45 system-ui,sans-serif;max-width:290px;
                box-shadow:0 1px 4px rgba(0,0,0,.25)">
      <div style="font-weight:700;margin-bottom:6px">CFA Fire Danger Period areas</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:{VICMAP_FILL};
           opacity:.6;margin-right:6px"></span>{len(gdf) - n_pdf} unsplit &mdash; Vicmap LGA geometry</div>
      <div><span style="display:inline-block;width:12px;height:12px;background:{PDF_FILL};
           opacity:.7;margin-right:6px"></span>{n_pdf} split &mdash; cut from the PDF maps</div>
      <div style="margin-top:6px"><span style="display:inline-block;width:12px;
           border-top:2px dashed {LGA_LINE};margin-right:6px;vertical-align:middle"></span>
           Vicmap LGA boundary (toggle above)</div>
      <div style="margin-top:8px;color:#555">The split areas carry the PDF-derived
           cuts and are where errors are most likely. Turn the LGA overlay on to
           check every other edge against the authoritative line.</div>
      <div style="margin-top:6px;color:#777">2024/25 season snapshot
           (fdp_boundaries20241017_final). The gazettal, not this map, is the
           legal instrument.</div>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))

    out = OUT_DIR / "map.html"
    m.save(out)
    return out


def split_figure(gdf: gpd.GeoDataFrame, vicmap: gpd.GeoDataFrame) -> Path:
    councils = ["YARRIAMBIACK", "SOUTHERN GRAMPIANS"]
    fig, axes = plt.subplots(1, len(councils), figsize=(13, 8.5))
    for ax, council in zip(axes, councils):
        parts = gdf[gdf.area_name.str.startswith(f"{council} - ")].sort_values("area_name")
        parent = vicmap.loc[vicmap.lga_name == council, "geometry"]
        parts.plot(ax=ax, column="area_name", cmap="Set2", edgecolor="#333",
                   linewidth=0.8, alpha=0.85)
        parent.boundary.plot(ax=ax, color="crimson", linewidth=2.2, zorder=5)
        for _, r in parts.iterrows():
            c = r.geometry.representative_point()
            ax.annotate(r.area_name.split(" - ")[1], (c.x, c.y), ha="center",
                        fontsize=9, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.8))
        ax.set_title(f"{council}\n{len(parts)} declaration areas, "
                     f"{parts.geometry.area.sum()/1e6:,.0f} km²", fontsize=11)
        ax.set_axis_off()
        ax.set_aspect("equal")
    fig.legend(handles=[Line2D([], [], color="crimson", lw=2.2,
                               label="Vicmap LGA boundary (parent council)")],
               loc="lower center", frameon=False, fontsize=10)
    fig.suptitle("PDF-derived splits against their authoritative parent outline",
                 fontsize=13, fontweight="bold")
    fig.text(0.5, 0.045, "The outer edge of every sub-area is Vicmap, so it must sit on the red line; "
                         "only the internal cuts come from the CFA PDF maps.",
             ha="center", fontsize=9, color="#444")
    fig.tight_layout(rect=[0, 0.08, 1, 0.96])
    out = OUT_DIR / "splits.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def main() -> int:
    src = OUT_DIR / "fdp_areas.gpkg"
    if not src.exists():
        print(f"ERROR: {src} not found - run assemble_fdp_areas.py first", file=sys.stderr)
        return 1
    gdf = gpd.read_file(src, layer="fdp_areas")
    vicmap = load_vicmap(Path.home() / ".cache" / "fdp" / "lga.gpkg", refresh=False)

    html = web_map(gdf, vicmap)
    print(f"Wrote {html} ({html.stat().st_size/1e6:.1f} MB, "
          f"{len(gdf)} areas + {len(vicmap)} LGA overlay, simplified {SIMPLIFY_M:g} m)")
    png = split_figure(gdf, vicmap)
    print(f"Wrote {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
