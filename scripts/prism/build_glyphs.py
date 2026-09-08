"""Rebuild exact design-weight outlines; authoring only, requires FreeType."""
import hashlib
import json
from pathlib import Path

from outline_font import Font


def main():
    here = Path(__file__).resolve().parent
    font_file = here / 'GeistMono-variable.ttf'
    font = Font(font_file)
    characters = ''.join(chr(n) for n in range(32, 127))
    data = {
        'font': 'Geist Mono',
        'font_sha256': hashlib.sha256(font_file.read_bytes()).hexdigest(),
        'units_per_em': font.em,
        'weights': {str(weight): {char: font.glyph(char, weight) for char in characters}
                    for weight in (420, 500, 555, 676)},
    }
    (here / 'glyphs.json').write_text(json.dumps(data, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
