"""Artwork sources. Each module describes one Wikimedia Commons work:
its categories, a `plan(info)` that turns file metadata into ordered
`(binomial, title)` pairs, an `ATTRIBUTION` block, and optional `BG` overrides
for the background pipeline.

Register a new source by adding its module here.
"""
from . import vonwright, gould

ALL = {m.NAME: m for m in (vonwright, gould)}
