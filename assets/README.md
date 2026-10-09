# Shop overlay assets

Downloaded on 2026-10-08 from the upstream projects. No image generation is used.

- `fonts/Montserrat-Variable.ttf`: Montserrat, weight axis set to 700 by Pillow.
  Source: https://github.com/google/fonts/tree/main/ofl/montserrat
  SIL Open Font License 1.1; the complete copyright and license are in `fonts/OFL.txt`.
  Overlay rendering uses this bundled font. GPSR labels use installed Windows
  Arial or Segoe UI in place; Windows fonts are not redistributed.
- `icons/*.svg`: Lucide icons from https://github.com/lucide-icons/lucide/tree/main/icons
  ISC license; upstream's complete license (including the MIT notice for icons
  inherited from Feather) is included in `icons/LICENSE`.
  SVG paths are rendered with Pillow by `scripts/listing_core/line_icons.py`; no Cairo,
  browser renderer or other dependency is required. An absent SVG uses an
  original simple line drawing for offline operation.

Only the downloaded files are used at runtime; scripts do not contact the network.
