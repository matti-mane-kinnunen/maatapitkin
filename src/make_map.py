"""Write out/map.html: an interactive route map built from out/network.json.

The page is self-contained (no map tiles): country outlines come from
data/basemap.geojson and are projected here into SVG paths.
"""
from __future__ import annotations

import html
import re

import i18n
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
    lang = net.get("lang") or "en"
    tx = i18n.texts(lang)                                     # page texts in the map's language (IDEA-13)
    net["i18n"] = tx
    tpl = (root / "src" / "map_template.html").read_text()
    tpl = tpl.replace("__GUIDE__", i18n.guide(lang))
    # {{key}} markers: texts may contain simple HTML; {origin} becomes __ORIGIN__, filled in below
    tpl = re.sub(r"\{\{(\w+)\}\}", lambda m: i18n.t(tx, m.group(1), origin="__ORIGIN__", origin_from="__ORIGIN_FROM__"), tpl)
    page = (tpl.replace("/*__DATA__*/null", json.dumps(net, ensure_ascii=False, separators=(",", ":")))
               .replace("__BASEMAP__", basemap_paths(base))
               .replace("__W__", str(w)).replace("__H__", str(h))
               .replace("__ORIGIN_FROM__", html.escape(net.get("origin_from") or (net.get("display") or {}).get(net["origin"], net["origin"])))
               .replace("__ORIGIN__", html.escape((net.get("display") or {}).get(net["origin"], net["origin"])))
               .replace("__TITLE__", html.escape(net.get("title") or "Maata pitkin"))
               .replace("__DRAFT__", i18n.t(tx, "draft_note") if net.get("draft") else ""))
    if fragment:
        (root / "out" / "map.html").write_text(page)      # fragment: paste into a page or publish as is
    site = root / "out" / "site"                             # a complete page for GitHub Pages
    site.mkdir(exist_ok=True)
    static = root / "static"                                 # preview pictures etc., copied as they are
    if static.is_dir():
        for f in static.iterdir():
            if f.is_file():
                (site / f.name).write_bytes(f.read_bytes())
    (site / page_name).write_text(
        f'<!doctype html>\n<html lang="{page_lang(lang)}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + head_tags(net, page_name, site, tx) +
        '</head>\n<body>\n' + re.sub(r"<title>.*?</title>\n?", "", page, count=1) + '\n</body>\n</html>\n')
    return site / page_name


def page_lang(lang: str) -> str:
    """The <html lang> of a page: its language once that language has texts, else English."""
    return lang if lang == "en" or (i18n.ROOT / "data" / "i18n" / f"{lang}.yaml").exists() else "en"


def head_tags(net: dict, page_name: str, site: Path, tx: dict | None = None) -> str:
    """<title>, description and the Open Graph tags Facebook, LinkedIn, WhatsApp etc. use for
    link previews (IDEA-11). The picture is static/preview-<origin>.png, made by hand when the
    network changes a lot; without it the preview simply has no picture."""
    origin = (net.get("display") or {}).get(net["origin"], net["origin"])   # in the map's language (D-50)
    title = net.get("title") or "Maata pitkin"
    first = (net.get("dates") or [None])[0]
    v = (net.get("variants") or {}).get(first) or {}
    routes = (v.get("yes") or {}).get("routes") or net.get("routes") or []
    n = len({r["capital"] for r in routes if r.get("is_capital", True)})
    tx = tx or i18n.texts(net.get("lang") or "en")
    origin_from = net.get("origin_from") or origin
    og_title = i18n.t(tx, "og_title", title=title, origin=origin, origin_from=origin_from, n=n)
    desc = i18n.t(tx, "og_desc", origin=origin, origin_from=origin_from, n=n)
    e = lambda x: html.escape(x, quote=True)
    tags = [f'<title>{e(og_title)}</title>', f'<meta name="description" content="{e(desc)}">',
            '<meta property="og:type" content="website">', f'<meta property="og:title" content="{e(og_title)}">',
            f'<meta property="og:description" content="{e(desc)}">', '<meta name="twitter:card" content="summary_large_image">']
    base = (net.get("site_url") or "").rstrip("/") + "/"
    if base != "/":
        url = base if page_name == "index.html" else base + page_name
        tags.append(f'<meta property="og:url" content="{e(url)}">')
        tags.append(f'<link rel="canonical" href="{e(url)}">')
        pic = f"preview-{re.sub(r'[^a-z0-9]+', '-', net['origin'].lower()).strip('-')}.png"
        if (site / pic).exists():
            tags += [f'<meta property="og:image" content="{e(base + pic)}">',
                     '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
                     f'<meta property="og:image:alt" content="{e(i18n.t(tx, "og_alt", origin=origin, origin_from=origin_from))}">']
    return "\n".join(tags) + "\n"


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parent.parent))
