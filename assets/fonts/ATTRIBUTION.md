# Attribution and licensing

The species labels on the collage are set in one of six italics, chosen in the
admin interface. All six are under the **SIL Open Font License 1.1**; each
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
