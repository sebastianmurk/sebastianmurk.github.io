# Vendored map libraries

The Academic travels page uses locally hosted copies of:

- [Leaflet 1.9.4](https://github.com/Leaflet/Leaflet), licensed under the
  BSD 2-Clause licence. See `leaflet/LICENSE`.
- [Leaflet.markercluster 1.5.3](https://github.com/Leaflet/Leaflet.markercluster),
  licensed under the MIT licence. See `leaflet-markercluster/MIT-LICENCE.txt`.

Only the distribution files required by the page are included. The map uses
custom `divIcon` markers, so Leaflet's default marker images and
`MarkerCluster.Default.css` are not required.

The page also loads pinned releases of MapTiler SDK JS 3.9.0 and the
Leaflet–MapTiler SDK integration 4.1.1 from MapTiler's CDN. These provide the
English-language Streets and Satellite Hybrid backgrounds. The protected
browser API key is configured in `travels/index.qmd`.
