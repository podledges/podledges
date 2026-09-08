# Prism Orbit source assets

Accepted Stage 2 presentation, now rendered by `scripts/waveform.py` through `scripts/prism_orbit.py`. No runtime dependencies beyond Python's standard library; native SVG viewing requires no font service or script.

- `motion.css`: native prism drift, numeral float, palette loops, scan rail, hot sheen, bay satellite/shuttle and reduced-motion rest states.
- `bio.json`: accepted title/bio placeholders and null Spotify/Telegram URLs. No destinations or biography were inferred.
- `avatar.jpg`: original profile avatar supplied with the selected candidate, copied unchanged. Use is limited to this profile; no general redistribution license is asserted.
- `GeistMono-variable.ttf` / `GeistMono-OFL.txt`: original Geist Mono variable font, distributed under the bundled SIL Open Font License. The generated atlas records the source font's SHA-256.
- `glyphs.json`: derived outlines at the exact weights and character range specified by `build_glyphs.py`, with original font provenance. This bounded ASCII atlas covers all current labels, dates, counts and placeholders. Unsupported characters fail explicitly rather than substituting another font.
- `font.py`: pure Python placement of those exact glyphs. No native library needed for scheduled generation or tests.
- `outline_font.py`: preserved original FreeType authoring helper. Requires existing system FreeType **only to rebuild the atlas**. It does not run during ordinary generation.
- `build_glyphs.py`: deterministic atlas rebuild after an authorized font/character change.

```sh
python3 scripts/prism/build_glyphs.py
python3 -m unittest discover -s tests -v
```

Preserve the font and license when redistributing source or derived assets. SVG metadata also carries the font license. No new third-party artwork, biography, social destinations or sound were introduced.

Presentation geometry, independent numeral/chart ownership, scaling and reduced-motion requirements are owned by [Profile asset generation](../../docs/profile-assets.md#accepted-prism-orbit-presentation); its [validation guidance](../../docs/profile-assets.md#validation) covers native browser acceptance.
