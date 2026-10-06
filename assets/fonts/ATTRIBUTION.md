# Attribution and licensing

The species names on the page are set in one of seven italics, chosen in the
admin interface. All seven are under the **SIL Open Font License 1.1**; each
family ships with its own `OFL.txt` in this directory, which is the copyright
notice the licence requires be distributed with the font.

The OFL covers the font files only. It is not viral: it places no conditions on
the images the fonts are used to render, so the collage's licensing is
unaffected.

## Families

| Directory | Family | Upstream |
| --- | --- | --- |
| `gentiumbookplus/` | Gentium Book Plus | [SIL International](https://software.sil.org/gentium/) |
| `ebgaramond/` | EB Garamond | [Octavio Pardo / Georg Duffner](https://github.com/octaviopardo/EBGaramond12) |
| `librebaskerville/` | Libre Baskerville | [Impallari Type](https://github.com/impallari/Libre-Baskerville) |
| `playfairdisplay/` | Playfair Display | [Claus Eggers Sørensen](https://github.com/clauseggers/Playfair) |
| `alegreya/` | Alegreya | [Huerta Tipográfica](https://github.com/huertatipografica/Alegreya) |
| `bitter/` | Bitter | [Huerta Tipográfica](https://github.com/solmatas/BitterPro) |

All were taken from the [Google Fonts](https://github.com/google/fonts)
distribution. Only the italic is vendored - a scientific name is set in italic -
and five of the six are variable fonts, instantiated at weight 400 by
`fonts.py`.

## Fallbacks

`noto/` holds the faces for a label line its italic has no glyphs for. All are
from the [Noto](https://notofonts.github.io/) project, under the SIL Open Font
License 1.1. `noto/OFL.txt` carries each upstream's licence, under the files it
covers.

| File | Family | Upstream |
| --- | --- | --- |
| `NotoSansCJKsc-Regular.otf` | Noto Sans CJK SC, subset | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) |
| `NotoSerifThai-Regular.ttf` | Noto Serif Thai | [notofonts/thai](https://github.com/notofonts/thai) |
| `NotoNaskhArabic-Regular.ttf` | Noto Naskh Arabic | [notofonts/arabic](https://github.com/notofonts/arabic) |
| `NotoSansHebrew-Regular.ttf` | Noto Sans Hebrew | [notofonts/hebrew](https://github.com/notofonts/hebrew) |
| `NotoSerifMalayalam-Regular.ttf` | Noto Serif Malayalam | [notofonts/malayalam](https://github.com/notofonts/malayalam) |

`tools/vendor_fonts.py` fetches them from a pinned commit. Noto Sans CJK is
modified: it is subset to the characters in BirdNET v2.4's Chinese, Japanese and
Korean labels, the dates the frame writes in those languages, and printable
ASCII. The others are unmodified.
