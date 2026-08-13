# CHANGELOG

<!-- version list -->

## v0.12.4 (2026-08-13)

### Bug Fixes

- Prune stale tags through _run, not subprocess
  ([`be966fc`](https://github.com/arnegiacomo/fugleramme/commit/be966fcfb0a0a993b52fb9d5adafce6b50a8b47a))

- Shallow-clone the repo on the Pi
  ([`4f77e9a`](https://github.com/arnegiacomo/fugleramme/commit/4f77e9ac0027f2955b7ea2f8896456a3eb3edc7e))

### Chores

- #24 add loc docs, fix broken link
  ([`310e1bf`](https://github.com/arnegiacomo/fugleramme/commit/310e1bfab26e89b5fbb7ecc42f1b8a10458956f3))

- Add "get in touch" - plz buy comment
  ([`6484c09`](https://github.com/arnegiacomo/fugleramme/commit/6484c09cd6b3b3414e56dc0766e4cf71d82580ac))

- Restore bird plates after history rewrite
  ([`66824dc`](https://github.com/arnegiacomo/fugleramme/commit/66824dcea59dd1a71cc64eccce3d69db614603af))

### Documentation

- #24 add notes on birdnet config
  ([`94c6ccb`](https://github.com/arnegiacomo/fugleramme/commit/94c6ccb553521e32570f6132aa5fe632c8e3ccf2))

- Fix broken paths
  ([`70b10b0`](https://github.com/arnegiacomo/fugleramme/commit/70b10b026b5196a74bfba7fe45e992d0489e5f87))

- Note BirdNET-Go licensing
  ([`694338f`](https://github.com/arnegiacomo/fugleramme/commit/694338ffe280f8eb96ff74205959a1e018a1e1c6))

### Performance Improvements

- Crop and resample bird plates to 1200px
  ([`ebb8392`](https://github.com/arnegiacomo/fugleramme/commit/ebb8392fb298883246d8105dfc8c201dba52549a))


## v0.12.3 (2026-08-11)

### Bug Fixes

- #25 add margin to account for passepartout
  ([`e63d62b`](https://github.com/arnegiacomo/fugleramme/commit/e63d62bd49674891ba718d5da657db8019c08a98))

### Documentation

- #24 update hardware docs
  ([`02cb785`](https://github.com/arnegiacomo/fugleramme/commit/02cb7850ce8750aa3e3c37010926a426d4d82bab))


## v0.12.2 (2026-08-10)

### Bug Fixes

- #2 spinner for the check, bar for the install
  ([`e4329cb`](https://github.com/arnegiacomo/fugleramme/commit/e4329cbee25a95068d20985fd05e963e82972098))


## v0.12.1 (2026-08-10)

### Bug Fixes

- #2 line up the update row, and say when a new version landed
  ([`7487597`](https://github.com/arnegiacomo/fugleramme/commit/74875977ecead80e88ef219df2c15d572252cf1d))


## v0.12.0 (2026-08-10)

### Features

- #2 show update progress, and let a slow download finish
  ([`8acee13`](https://github.com/arnegiacomo/fugleramme/commit/8acee135aa856e58531ba1195a4ed42d34345f95))


## v0.11.0 (2026-08-09)

### Documentation

- #17 say what the bird cap is actually for
  ([`7476383`](https://github.com/arnegiacomo/fugleramme/commit/7476383628fbbf5006583ebc064958d6cd511842))

- #17 update documentation
  ([`bfed17e`](https://github.com/arnegiacomo/fugleramme/commit/bfed17e4212ee2109f6183871ac6f2a5718cfa52))

### Features

- #17 all-time lookback, so the collage keeps growing
  ([`b12deae`](https://github.com/arnegiacomo/fugleramme/commit/b12deae43b179851751cd38c16370ff59e87f384))

- #17 Cormorant Garamond for the plate pages
  ([`5be7402`](https://github.com/arnegiacomo/fugleramme/commit/5be74023621e49591ce2608921d2542f341b2ca2))

- #17 display modes, walked by button A
  ([`45544f6`](https://github.com/arnegiacomo/fugleramme/commit/45544f691dc2421bd87453342dcaab7ca60c8127))

- #17 rotate the bird of the day's plate each lap
  ([`3e20417`](https://github.com/arnegiacomo/fugleramme/commit/3e2041729e3ba7d39390f0f6c3c075f15990ff21))


## v0.10.0 (2026-08-08)

### Chores

- "humanize" docs
  ([`62fd9b9`](https://github.com/arnegiacomo/fugleramme/commit/62fd9b96f731824c3d8fbde574c281b51a8e184a))

### Documentation

- Condense CLAUDE.md, bullets over prose
  ([`2c02ea9`](https://github.com/arnegiacomo/fugleramme/commit/2c02ea935f65a59d09eb67fed5682783bfe761bd))

- Render GitHub callouts as admonitions
  ([`ab2cf6e`](https://github.com/arnegiacomo/fugleramme/commit/ab2cf6ec9569de3266acb13a5075207e01a54b61))

### Features

- Curl-able install.sh, setup.sh becomes run.sh
  ([`6aabd97`](https://github.com/arnegiacomo/fugleramme/commit/6aabd972af87fd2c3087e31652d3c0ff880614ee))


## v0.9.0 (2026-08-03)

### Bug Fixes

- #13 hold one perch per day, shared by panel and kiosk
  ([`1637b56`](https://github.com/arnegiacomo/fugleramme/commit/1637b5601a5d0806e1a606f427b02dcafdd87702))

### Chores

- #13 untrack the workstation-only artwork pipeline
  ([`aa78507`](https://github.com/arnegiacomo/fugleramme/commit/aa78507b314c18bfeadd05f9cf295fc81b524548))

### Features

- #13 curate one artwork style, held per species while a bird is in the window
  ([`98fc248`](https://github.com/arnegiacomo/fugleramme/commit/98fc248f42f75b2a3567d6a3d610940983e72e0b))


## v0.8.0 (2026-08-02)

### Features

- #16 bind the panel buttons to presentation settings
  ([`a5dda4c`](https://github.com/arnegiacomo/fugleramme/commit/a5dda4c4e2deca19ddb41c38f228e27597351d7e))


## v0.7.0 (2026-08-02)

### Features

- #5 species names in the reader's language, from BirdNET-Go
  ([`37ec1bf`](https://github.com/arnegiacomo/fugleramme/commit/37ec1bf77bcafe57077310d76b764833d6599833))


## v0.6.0 (2026-08-02)

### Features

- #2 preview unsaved settings and guard against losing them
  ([`52071a1`](https://github.com/arnegiacomo/fugleramme/commit/52071a12d17ccf284e2a5399064627198962bea6))


## v0.5.0 (2026-08-02)

### Bug Fixes

- #2 force the update checkout so a re-locked uv.lock cannot block it
  ([`ef0d512`](https://github.com/arnegiacomo/fugleramme/commit/ef0d51233bd85c2ec2dfac3a58184b219796a514))

### Chores

- Re-lock uv.lock in the release commit
  ([`c12f717`](https://github.com/arnegiacomo/fugleramme/commit/c12f7173c20a3f29e5a523e7d360d5932f39d28a))

### Features

- #2 show install progress and reload the admin page when the update lands
  ([`91a25c8`](https://github.com/arnegiacomo/fugleramme/commit/91a25c8bc2620e96873bf58aa27ee1fc7b6d9353))


## v0.4.0 (2026-08-02)

### Chores

- Sync uv.lock to v0.3.0
  ([`6617458`](https://github.com/arnegiacomo/fugleramme/commit/6617458005e0845a097f088746b106c9fcc2964d))

### Documentation

- Reword the hardware parts table header
  ([`140481d`](https://github.com/arnegiacomo/fugleramme/commit/140481dbe2f5a7c7fa81a1c43dfaafe7657c1c52))

### Features

- #5 render species names on the collage
  ([`1b60393`](https://github.com/arnegiacomo/fugleramme/commit/1b603930fee342f95ef498a2fd1fdf300aaf33db))


## v0.3.0 (2026-08-02)

### Features

- #15 pin analysis defaults in the detector config template
  ([`90dbe6d`](https://github.com/arnegiacomo/fugleramme/commit/90dbe6d43c9db97db34473316bc0ebdaf2d6a715))


## v0.2.0 (2026-08-02)

### Features

- #2 check for and install tagged releases from the admin page
  ([`80be018`](https://github.com/arnegiacomo/fugleramme/commit/80be0189ab198b55609f3672b5bb85eeeb5f3fc6))


## v0.1.1 (2026-08-02)

### Bug Fixes

- #2 probe the internet on first load and show the mDNS hostname
  ([`e2d525a`](https://github.com/arnegiacomo/fugleramme/commit/e2d525a911fa7a20710d13eaf6ffb98793633da4))


## v0.1.0 (2026-08-02)

- Initial Release
