"""Write out/map.html: an interactive route map built from out/network.json.

The page is self-contained (no map tiles): country outlines come from
data/basemap.geojson and are projected here into SVG paths.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

SCALE = 22.0                              # px per degree latitude
# The map area is fitted to the places in the data (see fit()); these are the defaults
BBOX = (-12.5, 34.0, 35.5, 64.5)          # lon_min, lat_min, lon_max, lat_max
LAT0 = 52.0                               # latitude where east-west distances are true
PAD = (1.5, 1.0, 3.5, 1.0)                # margin in degrees: west, south, east (labels), north
NEAR = 4.0                                # capitals without connections are shown if this close


def fit(places: dict, not_covered: dict, extent=(-32, 25, 50, 72)) -> list[str]:
    """Fit BBOX to all places with data, plus nearby capitals without connections.
    Returns the names left outside the map."""
    global BBOX, LAT0
    lons = [p["lon"] for p in places.values()]
    lats = [p["lat"] for p in places.values()]
    w, s_, e, n = min(lons), min(lats), max(lons), max(lats)
    outside = []
    for name, p in not_covered.items():
        if w - NEAR <= p["lon"] <= e + NEAR and s_ - NEAR <= p["lat"] <= n + NEAR:
            lons.append(p["lon"]); lats.append(p["lat"])
        else:
            outside.append(name)
    BBOX = (max(extent[0], min(lons) - PAD[0]), max(extent[1], min(lats) - PAD[1]),
            min(extent[2], max(lons) + PAD[2]), min(extent[3], max(lats) + PAD[3]))
    LAT0 = (BBOX[1] + BBOX[3]) / 2
    return outside


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


def build(root: Path, net_file: str = "network.json", page_name: str = "index.html", fragment: bool = True):
    """Write the map page for one origin: out/site/<page_name> (and out/map.html for the first origin)."""
    net = json.loads((root / "out" / net_file).read_text())
    base = json.loads((root / "data" / "basemap.geojson").read_text())
    net["off_map"] = fit(net["places"], net["not_covered"], tuple(base.get("extent", (-32, 25, 50, 72))))
    for name, p in {**net["places"], **net["not_covered"]}.items():
        p["x"], p["y"] = project(p["lon"], p["lat"])
    for p in net["not_covered"].values():
        p["missing"] = True
    w, h = size()
    tpl = (root / "src" / "map_template.html").read_text()
    page = (tpl.replace("/*__DATA__*/null", json.dumps(net, ensure_ascii=False, separators=(",", ":")))
               .replace("__BASEMAP__", basemap_paths(base))
               .replace("__W__", str(w)).replace("__H__", str(h))
               .replace("__ORIGIN__", html.escape(net["origin"]))
               .replace("__TITLE__", html.escape(net.get("title") or "Maata pitkin")))
    if fragment:
        (root / "out" / "map.html").write_text(page)      # fragment: paste into a page or publish as is
    site = root / "out" / "site"                             # a complete page for GitHub Pages
    site.mkdir(exist_ok=True)
    (site / page_name).write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'<meta name="description" content="Overland journeys from {html.escape(net["origin"])} to the European capitals by train, ferry and bus.">\n'
        '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
    return site / page_name


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parent.parent))
