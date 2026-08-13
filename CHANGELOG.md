# CHANGELOG

<!-- version list -->

## v0.12.4 (2026-08-13)

### Bug Fixes

- Prune stale tags through _run, not subprocess
  ([`9886722`](https://github.com/arnegiacomo/fugleramme/commit/98867225c996005b06830e8859f56e833ed04578))

- Shallow-clone the repo on the Pi
  ([`4bb9e52`](https://github.com/arnegiacomo/fugleramme/commit/4bb9e5246adda06f37d52fe97a4ae2fc7f31c088))

### Chores

- #24 add loc docs, fix broken link
  ([`d8f4eeb`](https://github.com/arnegiacomo/fugleramme/commit/d8f4eeba72a352126373600a1cac69e5fa572e6e))

- Add "get in touch" - plz buy comment
  ([`890f431`](https://github.com/arnegiacomo/fugleramme/commit/890f43120bace4a64f665036ef499379250924f2))

- Restore bird plates after history rewrite
  ([`59760f7`](https://github.com/arnegiacomo/fugleramme/commit/59760f7e7394d8210ec96600841aaa384b2c75f9))

### Documentation

- #24 add notes on birdnet config
  ([`94fe609`](https://github.com/arnegiacomo/fugleramme/commit/94fe609c687a61c13ccb4789edf9b62e3dd9fce8))

- Fix broken paths
  ([`40716c9`](https://github.com/arnegiacomo/fugleramme/commit/40716c904d5a1cecf2e52297e3ebe78430b83d8d))

- Note BirdNET-Go licensing
  ([`36b82f5`](https://github.com/arnegiacomo/fugleramme/commit/36b82f57e457e59f5ae9ab7e8329811c989f773b))

### Performance Improvements

- Crop and resample bird plates to 1200px
  ([`376318c`](https://github.com/arnegiacomo/fugleramme/commit/376318c388aa2f357a7f82adcfeea2a5dd09e61a))


## v0.12.3 (2026-08-11)

### Bug Fixes

- #25 add margin to account for passepartout
  ([`7628249`](https://github.com/arnegiacomo/fugleramme/commit/7628249059b34958a5f1fd517dadf3e04f534edd))

### Documentation

- #24 update hardware docs
  ([`e496b5b`](https://github.com/arnegiacomo/fugleramme/commit/e496b5bc740e3997535bb2b34b9003e8f58f98a3))


## v0.12.2 (2026-08-10)

### Bug Fixes

- #2 spinner for the check, bar for the install
  ([`dc5a38d`](https://github.com/arnegiacomo/fugleramme/commit/dc5a38db4f0e2cc00763553c2e2bf0e95e497337))


## v0.12.1 (2026-08-10)

### Bug Fixes

- #2 line up the update row, and say when a new version landed
  ([`ec93109`](https://github.com/arnegiacomo/fugleramme/commit/ec931097b631839605faf6f04d448deb8db0eab4))


## v0.12.0 (2026-08-10)

### Features

- #2 show update progress, and let a slow download finish
  ([`0a392e0`](https://github.com/arnegiacomo/fugleramme/commit/0a392e094eebff61050343a88dc65d598be43433))


## v0.11.0 (2026-08-09)

### Documentation

- #17 say what the bird cap is actually for
  ([`c5dc21c`](https://github.com/arnegiacomo/fugleramme/commit/c5dc21c72708cf8c40481042f6b9f4ee8351dcbb))

- #17 update documentation
  ([`cd77518`](https://github.com/arnegiacomo/fugleramme/commit/cd77518473714549aa676d889f9d01cf34700ff8))

### Features

- #17 all-time lookback, so the collage keeps growing
  ([`9ec57db`](https://github.com/arnegiacomo/fugleramme/commit/9ec57db6695bbfdf366fef3798e85027fc40b496))

- #17 Cormorant Garamond for the plate pages
  ([`0c436cb`](https://github.com/arnegiacomo/fugleramme/commit/0c436cbcad541de48a72862894d909d910e9ac94))

- #17 display modes, walked by button A
  ([`ad390d7`](https://github.com/arnegiacomo/fugleramme/commit/ad390d71ea247b4deb40871424210b5007ce4b99))

- #17 rotate the bird of the day's plate each lap
  ([`9dbff9c`](https://github.com/arnegiacomo/fugleramme/commit/9dbff9c214c0c72b274316c97c46fbc482ba8193))


## v0.10.0 (2026-08-08)

### Chores

- "humanize" docs
  ([`3fd728e`](https://github.com/arnegiacomo/fugleramme/commit/3fd728e2e454de83a4bdd03300a1c5e3181bc5d3))

### Documentation

- Condense CLAUDE.md, bullets over prose
  ([`e1860fe`](https://github.com/arnegiacomo/fugleramme/commit/e1860fe1689109f4dc188636ff6cd32e6957bc56))

- Render GitHub callouts as admonitions
  ([`2596544`](https://github.com/arnegiacomo/fugleramme/commit/2596544782ec5077db0849a9ccbe71c9c0657dbb))

### Features

- Curl-able install.sh, setup.sh becomes run.sh
  ([`11e4107`](https://github.com/arnegiacomo/fugleramme/commit/11e4107bbd85dc82dda5f97b30a0456fd70d06ec))


## v0.9.0 (2026-08-03)

### Bug Fixes

- #13 hold one perch per day, shared by panel and kiosk
  ([`6504552`](https://github.com/arnegiacomo/fugleramme/commit/6504552899a2ba1100259bbdce5d2de642758299))

### Chores

- #13 untrack the workstation-only artwork pipeline
  ([`8b90eb2`](https://github.com/arnegiacomo/fugleramme/commit/8b90eb29d6de93db7fa6aeaa5b3b180d01d9da26))

### Features

- #13 curate one artwork style, held per species while a bird is in the window
  ([`7568b80`](https://github.com/arnegiacomo/fugleramme/commit/7568b80e8f4488b495dce1c06046a5b4e7bd5019))


## v0.8.0 (2026-08-02)

### Features

- #16 bind the panel buttons to presentation settings
  ([`2a2207c`](https://github.com/arnegiacomo/fugleramme/commit/2a2207ce3d4323e5e11d04fd936ee1a1dfefc4a8))


## v0.7.0 (2026-08-02)

### Features

- #5 species names in the reader's language, from BirdNET-Go
  ([`47cb3d2`](https://github.com/arnegiacomo/fugleramme/commit/47cb3d2740417f88f5f6c254125ba54ccb8a42b4))


## v0.6.0 (2026-08-02)

### Features

- #2 preview unsaved settings and guard against losing them
  ([`e957d8b`](https://github.com/arnegiacomo/fugleramme/commit/e957d8bdd1c494792b89fbaffd7174d5cf1efa58))


## v0.5.0 (2026-08-02)

### Bug Fixes

- #2 force the update checkout so a re-locked uv.lock cannot block it
  ([`e0b6949`](https://github.com/arnegiacomo/fugleramme/commit/e0b6949ab94168ee3cb69b7e74c2c64420bae7a6))

### Chores

- Re-lock uv.lock in the release commit
  ([`0b38b4e`](https://github.com/arnegiacomo/fugleramme/commit/0b38b4e5638796f05d4f8f1a7215f2aab0f108ea))

### Features

- #2 show install progress and reload the admin page when the update lands
  ([`e0caba8`](https://github.com/arnegiacomo/fugleramme/commit/e0caba8e493e7ca29713f592c71e834a821dc40c))


## v0.4.0 (2026-08-02)

### Chores

- Sync uv.lock to v0.3.0
  ([`7a2f87d`](https://github.com/arnegiacomo/fugleramme/commit/7a2f87ddb5fd686c780d2611839c10c6eb1fddd4))

### Documentation

- Reword the hardware parts table header
  ([`03d5ea1`](https://github.com/arnegiacomo/fugleramme/commit/03d5ea1c9f342ccdfb5237c18f30b473248ec0c5))

### Features

- #5 render species names on the collage
  ([`48e597e`](https://github.com/arnegiacomo/fugleramme/commit/48e597e1439fe3787359504a159c591ef6cb7054))


## v0.3.0 (2026-08-02)

### Features

- #15 pin analysis defaults in the detector config template
  ([`eac6c42`](https://github.com/arnegiacomo/fugleramme/commit/eac6c42e1cc5818f0b217076090e0013f85e3742))


## v0.2.0 (2026-08-02)

### Features

- #2 check for and install tagged releases from the admin page
  ([`9b08ea0`](https://github.com/arnegiacomo/fugleramme/commit/9b08ea093caa373cbc600b91e5753781d86ac94a))


## v0.1.1 (2026-08-02)

### Bug Fixes

- #2 probe the internet on first load and show the mDNS hostname
  ([`6cc088a`](https://github.com/arnegiacomo/fugleramme/commit/6cc088a63ac52a8ebe7a01fd85b1e708b6b67fed))


## v0.1.0 (2026-08-02)

- Initial Release
