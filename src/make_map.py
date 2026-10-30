"""Write out/map.html: an interactive route map built from out/network.json.

The page is self-contained (no map tiles): country outlines come from
data/basemap.geojson and are projected here into SVG paths.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

LAT0 = 52.0
BBOX = (-12.5, 34.0, 35.5, 64.5)          # lon_min, lat_min, lon_max, lat_max
SCALE = 22.0                              # px per degree latitude


def project(lon: float, lat: float) -> tuple[float, float]:
    x = (lon - BBOX[0]) * math.cos(math.radians(LAT0)) * SCALE
    y = (BBOX[3] - lat) * SCALE
    return round(x, 1), round(y, 1)


def size() -> tuple[float, float]:
    return project(BBOX[2], BBOX[1])


def ring_path(ring) -> str:
    pts = [project(lon, lat) for lon, lat in ring]
    return "M" + "L".join(f"{x},{y}" for x, y in pts) + "Z"


def basemap_paths(geojson: dict) -> str:
    out = []
    for f in geojson["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"] if g["type"] == "MultiPolygon" else []
        d = "".join(ring_path(r) for poly in polys for r in poly)
        if d:
            out.append(f'<path d="{d}"/>')
    return "".join(out)


def build(root: Path):
    net = json.loads((root / "out" / "network.json").read_text())
    base = json.loads((root / "data" / "basemap.geojson").read_text())
    for name, p in {**net["places"], **net["not_covered"]}.items():
        p["x"], p["y"] = project(p["lon"], p["lat"])
    for p in net["not_covered"].values():
        p["missing"] = True
    w, h = size()
    tpl = (root / "src" / "map_template.html").read_text()
    page = (tpl.replace("/*__DATA__*/null", json.dumps(net, ensure_ascii=False, separators=(",", ":")))
               .replace("__BASEMAP__", basemap_paths(base))
               .replace("__W__", str(w)).replace("__H__", str(h)))
    (root / "out" / "map.html").write_text(page)
    return root / "out" / "map.html"


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parent.parent))
