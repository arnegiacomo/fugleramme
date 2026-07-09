"""Make the paper background of each von Wright plate transparent, drop the
species-name caption, and keep the illustration (bird, branch, leaves, rock,
water scene) plus the artist signature, with a small buffer of the original
image around the subject.

Pipeline:
  1. Caption crop: the species-name caption sits in the bottom margin, split
     from the illustration by a band of empty paper. Find that gap in the raw
     row-ink profile and discard everything below it (caption + printer
     credit). The signature, which hugs the bird above the gap, is kept.
  2. Subject mask - union of two masks:
       a. Color key: flood-fill the cream paper inward from the borders, but
          only through pixels that are both paper-coloured AND edge-free, so
          the bird's outline stops the fill. Keeps enclosed white areas and
          detached elements (leaves) as islands and clears gaps between them.
       b. birefnet subject matte: a soft, smooth-edged mask that keeps solid
          white/pale birds the color key alone would leak through and shatter.
     birefnet supplies the smooth main edge; the color key adds what birefnet
     misses (leaves, rock, water).
  3. Signature: keep word-sized patches of dark ink above the crop line; drop
     light paper foxing and dust specks.
  4. Buffer: dilate the subject by BUFFER_PX so a ring of the ORIGINAL image
     is kept around it, then crop to that region.

Input:  wikimedia-scrape/originals/<slug>.<ext>
Output: assets/birds/<slug>.png   (resumable; skips existing)
"""
import os, io, time
from pathlib import Path
import numpy as np
import cv2
from PIL import Image
from rembg import remove, new_session

HERE = Path(__file__).resolve().parent                 # wikimedia-scrape/
SRC = HERE / 'originals'                                # downloaded scans (gitignored)
DST = HERE.parent / 'assets' / 'birds'                 # committed transparent PNGs
BUFFER_PX = 50                                          # ring of original image kept around subject


def colorkey_fg(bgr, coltol=55, canny_lo=30, canny_hi=90, dilate=2):
    """Raw foreground mask via border flood-fill with edge barriers.

    Everything that is not paper reachable from the borders: the bird and all
    illustrated elements PLUS every scrap of printed text (signature, caption,
    printer credit). Text is separated later by proximity to the subject.

    ``coltol`` is the paper-colour tolerance; it is widened automatically when
    the sheet is vignetted (border noticeably darker than the centre paper) so
    the fill can still reach the middle of the sheet.
    """
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.int16)
    frame = np.concatenate([rgb[:8].reshape(-1, 3), rgb[-8:].reshape(-1, 3),
                            rgb[:, :8].reshape(-1, 3), rgb[:, -8:].reshape(-1, 3)])
    bg_col = np.median(frame, 0)
    dist = np.sqrt(((rgb - bg_col) ** 2).sum(2))
    # widen tolerance to bridge a vignette: how far the top-centre margin
    # (reliably paper) sits from the darker border colour
    top_centre = np.median(rgb[int(0.03 * h):int(0.08 * h),
                               int(0.35 * w):int(0.65 * w)].reshape(-1, 3), 0)
    vignette = float(np.sqrt(((top_centre - bg_col) ** 2).sum()))
    coltol = max(coltol, vignette + 20)
    paperlike = dist < coltol
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, canny_lo, canny_hi)
    if dilate:
        edges = cv2.dilate(edges, np.ones((dilate, dilate), np.uint8))
    permeable = (paperlike & (edges == 0)).astype(np.uint8)
    n, lab = cv2.connectedComponents(permeable, 8)
    border = set(lab[0]).union(lab[-1]).union(lab[:, 0]).union(lab[:, -1])
    border.discard(0)
    bg = np.isin(lab, list(border))
    return (~bg).astype(np.uint8)


def caption_crop_row(bgr, tau=0.008, min_gap_frac=0.03, tail_frac=0.15,
                     start_frac=0.45):
    """Row just above the species-name caption.

    The caption sits in the bottom margin, separated from the illustration by
    a band of empty paper. Working from the raw row-ink profile (independent
    of the subject mask, which birefnet can bleed past the caption), find the
    highest empty gap in the lower part of the plate below which only short
    printed content remains (caption + printer credit). Crop at the middle of
    that gap. Everything below is discarded; the signature, which hugs the
    bird above the gap, is kept.
    """
    h, w = bgr.shape[:2]
    # measure content by darkness, not distance from the border colour: a
    # vignetted sheet reads as "far from the border" in the centre but is still
    # light, whereas ink (caption, bird) is dark regardless of the vignette.
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    content = (gray < 165).sum(1) / w > tau
    min_gap = int(min_gap_frac * h)
    tail = int(tail_frac * h)
    y = int(start_frac * h)
    while y < h - min_gap:
        if not content[y:y + min_gap].any():            # an empty band
            below = content[y + min_gap:]
            if below.sum() <= tail:                     # only short text remains below
                gap_end = y + min_gap
                while gap_end < h and not content[gap_end]:
                    gap_end += 1
                return (y + gap_end) // 2               # crop in the middle of the gap
            y += min_gap
        else:
            y += 1
    return h


def keyout(path, session, subj_frac=0.00035, sig_min_frac=0.00005,
           buffer_px=BUFFER_PX):
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    h, w = bgr.shape[:2]
    ck = colorkey_fg(bgr)                                # bird + illustration + all text
    out = remove(open(path, 'rb').read(), session=session, post_process_mask=True)
    ba = np.array(Image.open(io.BytesIO(out)).convert('RGBA'))[..., 3].astype(np.float32)
    ba = cv2.GaussianBlur(ba, (0, 0), 1.0)              # smooth birefnet's own staircase
    add = ((ck > 0) & (ba < 30)).astype(np.uint8) * 255  # regions only the color key found
    add = cv2.medianBlur(add, 5)                         # de-jag the color-key boundary
    add = cv2.GaussianBlur(add.astype(np.float32), (0, 0), 1.6)
    alpha = np.maximum(ba, add)

    # crop off the species-name caption first (everything below the gap)
    crop_y = caption_crop_row(bgr)

    hard = (alpha > 30).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(hard, 8)
    subj_thr = subj_frac * h * w
    sig_min = sig_min_frac * h * w
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 1]
    bird = ba > 30
    # large components = the subject (bird + connected branch / leaves / rock).
    # Drop large blobs of trapped paper the border fill couldn't reach: pale,
    # low-saturation regions that don't overlap the birefnet bird matte (real
    # illustration is either part of the bird or coloured, e.g. leaves/rock).
    core = np.zeros((h, w), np.uint8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < subj_thr:
            continue
        comp = lab == i
        overlaps_bird = (comp & bird).sum() >= 0.01 * st[i, cv2.CC_STAT_AREA]
        coloured = sat[comp].mean() > 30
        if overlaps_bird or coloured:
            core[comp] = 1
    # erase trapped paper the border fill missed (or that fused to the bird):
    # pale, low-saturation pixels that birefnet does not call bird. The bird's
    # own white/grey areas are protected because birefnet covers them.
    pale = (gray > 200) & (sat < 30) & (~bird)
    core[pale] = 0
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

    # above the crop line the only wanted mark left is the artist signature:
    # a word-sized patch of dark ink. Keep those, drop light paper foxing and
    # dust specks.
    subject = core.copy()
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        if not (sig_min <= area < subj_thr):
            continue
        if st[i, cv2.CC_STAT_TOP] >= crop_y:            # below caption crop
            continue
        comp = (lab == i)
        if gray[comp].mean() < 215:                     # dark ink -> signature
            subject[comp] = 1
    subject[crop_y:] = 0

    # keep a ring of the original image around subject + signature, then buffer
    if buffer_px:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * buffer_px + 1, 2 * buffer_px + 1))
        buf = cv2.dilate(subject, k)
        alpha_out = cv2.GaussianBlur((buf * 255).astype(np.float32), (0, 0), 1.5)
    else:
        alpha_out = np.where(subject > 0, alpha, 0)
    alpha_out[crop_y:] = 0                               # nothing below the crop line
    alpha_out = np.clip(alpha_out, 0, 255).astype(np.uint8)
    out = np.dstack([cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), alpha_out])
    img = Image.fromarray(out, 'RGBA')
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def main():
    DST.mkdir(parents=True, exist_ok=True)
    files = sorted(f for f in os.listdir(SRC)
                   if f.lower().endswith(('.jpg', '.jpeg', '.png')))
    session = new_session('birefnet-general')           # downloads the model on first run
    done = skip = err = 0
    t0 = time.time()
    for i, f in enumerate(files, 1):
        dst = DST / (os.path.splitext(f)[0] + '.png')
        if dst.exists() and dst.stat().st_size > 1000:
            skip += 1; continue
        try:
            keyout(SRC / f, session).save(dst)
            done += 1
        except Exception as e:
            err += 1; print('ERR', f, str(e)[:60], flush=True)
        if (done + skip) % 25 == 0:
            print(f'{i}/{len(files)} done={done} skip={skip} err={err} '
                  f'{time.time() - t0:.0f}s', flush=True)
    print(f'FINISHED done={done} skip={skip} err={err} '
          f'out={len(list(DST.glob("*.png")))}', flush=True)


if __name__ == '__main__':
    main()
