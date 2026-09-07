for f in files/municipalities/*.pdf; do
  printf '%-56s ' "$(basename "$f")"
  gdalinfo "$f" 2>/dev/null | grep -c 'Coordinate System is' 
done