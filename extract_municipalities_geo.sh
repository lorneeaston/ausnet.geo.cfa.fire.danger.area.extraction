mkdir -p extracted
for f in files/municipalities_pdf/*.pdf; do
  L=$(ogrinfo "$f" | grep -oP '^\d+: \KLayers_fdp_boundaries\S+' | grep -v Labels)
  out="files/municipalities_geo/$(basename "${f%.pdf}").geojson"
  ogr2ogr -f GeoJSON "$out" -a_srs EPSG:3111 -nln fdp "$f" "$L" || echo "FAILED: $f ($L)"
done