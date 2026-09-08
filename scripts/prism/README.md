# Prism Orbit source assets

Accepted Stage 2 presentation, now rendered by `scripts/waveform.py` through `scripts/prism_orbit.py`. No runtime dependencies beyond Python's standard library; native SVG viewing requires no font service or script.

- `motion.css`: native prism drift, numeral float, palette loops, scan rail, hot sheen, bay satellite/shuttle and reduced-motion rest states.
- `bio.json`: accepted title/bio placeholders and null Spotify/Telegram URLs. No destinations or biography were inferred.
- `avatar.jpg`: original profile avatar supplied with the selected candidate, copied unchanged. Use is limited to this profile; no general redistribution license is asserted.
- `GeistMono-variable.ttf` / `GeistMono-OFL.txt`: original Geist Mono variable font, distributed under the bundled SIL Open Font License. SHA-256 `d00e590b8eb3a59acc329b2d044fd143ae935090b7da33199ebee27cc7de8196`.
- `glyphs.json`: derived outlines at exact weights 420/500/555/676, with original font provenance. This bounded ASCII atlas covers all current labels, dates, counts and placeholders. Unsupported characters fail explicitly rather than substituting another font.
- `font.py`: pure Python placement of those exact glyphs. No native library needed for scheduled generation or tests.
- `outline_font.py`: preserved original FreeType authoring helper. Requires existing system FreeType **only to rebuild the atlas**. It does not run during ordinary generation.
- `build_glyphs.py`: deterministic atlas rebuild after an authorized font/character change.

```sh
python3 scripts/prism/build_glyphs.py
python3 -m unittest discover -s tests -v
```

Preserve the font and license when redistributing source or derived assets. SVG metadata also carries the font license. No new third-party artwork, biography, social destinations or sound were introduced.

Keep 588-height / 62:38 slot geometry and separate number/chart ownership. The chart is linear from zero; peaks above 75 scale the entire chart together, keeping flames/counts clear without clipping. No synthetic minimum bar height or unbounded overflow.

Native reduced-motion proof must use the actual media preference and delayed image frames/screenshots. Hiding an SMIL node alone is not proof; the moving shard's painted parent is hidden and a separate identical shard remains visible at rest. The retained Hub/waveform are outside the new pair's reduced-motion claim.
