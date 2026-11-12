# Render assets

- `investsync-logo*.png`, `cuhksz-logo*.png`: logos used in the page headers.
- `world-110m.svg`: the world map in the learner's guide (revenue by region). Country shapes from
  **Natural Earth** 1:110m "Admin 0 - Countries" (`ne_110m_admin_0_countries.geojson`,
  https://github.com/nvkelso/natural-earth-vector). Natural Earth is in the **public domain**
  (https://www.naturalearthdata.com/about/terms-of-use/); no permission or attribution is required, and we credit it
  anyway. Projected (Equal Earth) and simplified by `tools/build_world_map.py`; about 130 KB. Hong Kong, Macau and
  Singapore are too small for the 1:110m data and are added as dots.
