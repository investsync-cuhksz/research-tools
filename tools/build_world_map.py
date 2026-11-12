"""Build investsync/render/assets/world-110m.svg, the world map the learner's guide colours by revenue share.

Source: Natural Earth 1:110m "Admin 0 - Countries" (ne_110m_admin_0_countries.geojson,
https://github.com/nvkelso/natural-earth-vector). Natural Earth is in the PUBLIC DOMAIN
(https://www.naturalearthdata.com/about/terms-of-use/): no permission or attribution needed; we credit it anyway.

The script projects the shapes with the Equal Earth projection (areas stay true, so a big share does not look bigger
than it is), drops Antarctica, rounds to 0.1 units and writes one <path id="ISO3"> per country with its continent
and UN subregion as data-* attributes (used to map names such as "Europe" or "Asia Pacific"). Places too small
for the 1:110m map (Hong Kong, Macau, Singapore) are added as small circles. Run once by hand:

    python -I tools/build_world_map.py <path/to/ne_110m_admin_0_countries.geojson>
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "investsync" / "render" / "assets" / "world-110m.svg"
WIDTH = 1000.0
# (ISO3, name, lon, lat, continent, subregion): too small to appear at 1:110m
SMALL = [("HKG", "Hong Kong", 114.17, 22.32, "Asia", "Eastern Asia"),
         ("MAC", "Macau", 113.55, 22.17, "Asia", "Eastern Asia"),
         ("SGP", "Singapore", 103.82, 1.35, "Asia", "South-Eastern Asia")]

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3) / 2


def equal_earth(lon: float, lat: float) -> tuple[float, float]:
    lam, phi = math.radians(lon), math.radians(lat)
    th = math.asin(M * math.sin(phi))
    t2 = th * th
    t6 = t2 ** 3
    x = 2 * math.sqrt(3) * lam * math.cos(th) / (3 * (9 * A4 * t6 * t2 + 7 * A3 * t6 + 3 * A2 * t2 + A1))
    y = th * (A4 * t6 * t2 + A3 * t6 + A2 * t2 + A1)
    return x, y


def main(src: str) -> None:
    gj = json.loads(Path(src).read_text(encoding="utf-8"))
    xmax = equal_earth(180, 0)[0]
    scale = WIDTH / (2 * xmax)
    feats = []
    for f in gj["features"]:
        pr = f["properties"]
        if pr["CONTINENT"] in ("Antarctica", "Seven seas (open ocean)"):
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        feats.append((pr["ADM0_A3"], pr["NAME"], pr["CONTINENT"], pr["SUBREGION"], polys))
    pts = lambda lon, lat: ((equal_earth(lon, lat)[0] + xmax) * scale, -equal_earth(lon, lat)[1] * scale)
    ys = [pts(lon, lat)[1] for *_, polys in feats for poly in polys for ring in poly for lon, lat in ring]
    top, bottom = min(ys) - 4, max(ys) + 4
    height = bottom - top
    out = []
    for iso, name, cont, sub, polys in feats:
        d = []
        for poly in polys:
            for ring in poly:
                prev, seg = None, []
                for lon, lat in ring:
                    x, y = pts(lon, lat)
                    p = (round(x, 1), round(y - top, 1))
                    if p != prev:
                        seg.append(p)
                    prev = p
                if len(seg) >= 3:
                    d.append("M" + "L".join(f"{x:g},{y:g}" for x, y in seg) + "Z")
        out.append(f'<path id="{iso}" data-name="{name}" data-continent="{cont}" data-subregion="{sub}" d="{"".join(d)}"/>')
    for iso, name, lon, lat, cont, sub in SMALL:
        x, y = pts(lon, lat)
        out.append(f'<circle id="{iso}" data-name="{name}" data-continent="{cont}" data-subregion="{sub}" '
                   f'cx="{x:.1f}" cy="{y - top:.1f}" r="4.5"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH:g} {height:.1f}">\n'
           '<!-- World map, Equal Earth projection. Shapes: Natural Earth 1:110m Admin 0 - Countries, public domain '
           '(naturalearthdata.com). Built by tools/build_world_map.py. -->\n'
           '<g fill="#DCE1EA" stroke="#FFFFFF" stroke-width="0.6" stroke-linejoin="round" fill-rule="evenodd">\n'
           + "\n".join(out) + "\n</g>\n</svg>\n")
    OUT.write_text(svg, encoding="utf-8")
    print(f"wrote {OUT} ({len(svg) / 1024:.0f} KB, {len(out)} shapes)")


if __name__ == "__main__":
    main(sys.argv[1])
