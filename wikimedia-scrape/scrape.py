"""Download every image in the Wikimedia Commons category
"Svenska fåglar (von Wright)" and name each file after the bird's Latin
binomial (genus species), e.g. `cuculus-canorus.jpg`.

The category holds two kinds of files:
  * "Bird illustration from Svenska Fåglar ... rawpixel ..." plates, whose
    species is taken from the API image description (in parentheses, or the
    leading text when there is no common name).
  * Other files whose species is already in the Commons filename.

Both are normalised to `genus-species`. Repeated species get a numeric
suffix (`-2`, `-3`, ...) in a single shared namespace, illustration plates
first (by plate number) then the others (alphabetically).

Output: wikimedia-scrape/originals/<slug>.<ext>
"""
import json, re, html, os, time, urllib.request, urllib.parse
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
CATEGORY = "Category:Svenska fåglar (von Wright)"
UA = "SvenskaFaglarScrape/1.0 (arnegiacomo@gmail.com) educational"
OUT = str(Path(__file__).resolve().parent / "originals")

# --- Latin-name parsing for the "Bird illustration ..." plates -------------

# Heads (text before "illustrated by") that the generic parser gets wrong,
# mapped straight to their final binomial. Includes hybrids and plates where
# the Latin name sits outside the parentheses.
EXCEPTIONS = {
    'Strix aluco (Tawny owl)': 'strix aluco',
    'Sylvia curruca (Lesser whitethroat)': 'sylvia curruca',
    'Tringa Alpina (Dunlin)': 'tringa alpina',
    'Aegithalus caudatus (Long-tailed tit)': 'aegithalus caudatus',
    'Common Sandpiper Tringoides hypoleucus (now Actitis hypoleucos )': 'actitis hypoleucos',
    'Willow ptarmigan': 'lagopus lagopus',
    'Eider (CORACIAS SOMATERIA MOLLISSIMA)': 'somateria mollissima',
    'Hybrid between Black grouse and Willow ptarmigan (Lyrurus tetrix ♂ x lagopus lagopus ♀)': 'lyrurus tetrix x lagopus lagopus',
    'Hybrid between Black grouse and Willow ptarmigan (Yrurus tetrix x lagopus lagopus)': 'lyrurus tetrix x lagopus lagopus',
    'Hybrid between Western capercaillie and Willow ptarmigan (Tetrao urogallus x lagopus lagopus)': 'tetrao urogallus x lagopus lagopus',
    'Hybrid between black grouse and western capercaillie (Lyrurus tetrix ♂ x Tetrao urogallus ♀)': 'lyrurus tetrix x tetrao urogallus',
    'Hybrid between common house-martin and barn swallow (Chelidon rustica L.xHirundo urbica)': 'chelidon rustica x hirundo urbica',
    'lyrurus tetrix tetrastes bonasia': 'lyrurus tetrix x tetrastes bonasia',
}

# Source-typo fixes so the same species collapses to one slug.
TYPO = {
    'numenius arquatusf': 'numenius arquata',
    'pavoncella pugnaxr': 'pavoncella pugnax',
    'larus canu': 'larus canus',
    'lagopus lagoups': 'lagopus lagopus',
    'picoides tridactylu': 'picoides tridactylus',
    'turdus usicus': 'turdus musicus',
    'odiceps grisegena': 'podiceps grisegena',
    'emberiza carlandra': 'emberiza calandra',
    'nyroca fuligule': 'nyroca fuligula',
    'hypolais hipolais': 'hippolais hippolais',
}

JUNK = {'now', 'bird', 'owl', 'l', 'lin', 'male', 'female', 'and', 'young'}
_TAG = re.compile('<[^>]+>')


def get_head(desc):
    """Description text up to (but not including) 'illustrated ...'."""
    txt = html.unescape(_TAG.sub(' ', desc))
    txt = re.sub(r'\s+', ' ', txt).strip()
    return re.split(r'illustrated', txt, flags=re.I)[0].strip()


def to_binomial(cand):
    cand = re.sub(r'[\(\[][^\)\]]*[\)\]]', ' ', cand)   # drop subgenus groups
    cand = cand.replace('.', ' ')
    toks = [t for t in re.findall(r'[A-Za-z]+', cand) if t.lower() not in JUNK]
    if len(toks) < 2:
        return None
    g, s = toks[0].lower(), toks[1].lower()
    if len(g) < 3 or len(s) < 3:
        return None
    return f'{g} {s}'


def parse_illustration(head):
    if head in EXCEPTIONS:
        return EXCEPTIONS[head]
    h = re.sub(r'[0-9]*\s*[♀♂]', '', head)                       # strip sex markers
    m = re.search(r'\(([^()]*(?:\([^()]*\)[^()]*)*)\)', h)        # first (nested) paren
    binom = to_binomial(m.group(1)) if m else None
    if binom is None:
        binom = to_binomial(h)                                   # fall back to whole head
    return TYPO.get(binom, binom) if binom else None


def parse_other(title):
    """Species from a plain Commons filename such as 'Falco aesalon male.jpg'."""
    n = re.sub(r'\.(jpg|jpeg|png)$', '', title.replace('File:', ''), flags=re.I)
    n = re.sub(r'^Magnus von Wright\s*-\s*', '', n)
    m = re.search(r'Svenska Fåglar\s*\(([^)]*)\)', n)
    if m:
        n = m.group(1)
    n = n.split(',')[0]                                          # first species before comma
    drop = {'f', 'm', 'female', 'male', 'ung', 'von', 'wright', 'magnus'}
    toks = [t for t in re.findall(r'[A-Za-zåäöÅÄÖ]+', n)
            if t.lower() not in drop and len(t) >= 3]
    return f'{toks[0].lower()} {toks[1].lower()}' if len(toks) >= 2 else None


def slug(name):
    return re.sub(r'[^a-z]+', '-', name.lower()).strip('-')


# --- Commons API helpers ---------------------------------------------------

def api(params):
    params['format'] = 'json'
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(API, data=data, headers={'User-Agent': UA})
    return json.load(urllib.request.urlopen(req))


def list_files():
    files, cont = [], {}
    while True:
        p = dict(action='query', list='categorymembers', cmtitle=CATEGORY,
                 cmtype='file', cmlimit='500', **cont)
        d = api(p)
        files += [m['title'] for m in d['query']['categorymembers']]
        if 'continue' in d:
            cont = d['continue']
        else:
            return files


def image_info(titles):
    """{title: {'url':..., 'desc':...}} for up to 50 titles (POST avoids 414)."""
    d = api(dict(action='query', titles='|'.join(titles),
                 prop='imageinfo', iiprop='url|extmetadata'))
    out = {}
    for pg in d['query']['pages'].values():
        ii = pg['imageinfo'][0]
        out[pg['title']] = {
            'url': ii['url'],
            'desc': ii['extmetadata'].get('ImageDescription', {}).get('value', ''),
        }
    return out


def fetch(url):
    delay = 1.0
    for _ in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            return urllib.request.urlopen(req, timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code == 429:                      # be polite, back off
                time.sleep(delay); delay = min(delay * 2, 30); continue
            raise
    raise RuntimeError('gave up after retries')


def plate_number(title):
    m = re.search(r'(\d+)\.jpg', title)
    return int(m.group(1)) if m else 0


def main():
    os.makedirs(OUT, exist_ok=True)
    files = list_files()
    plates = sorted((f for f in files if f.startswith('File:Bird illustration')),
                    key=plate_number)
    others = sorted(f for f in files if not f.startswith('File:Bird illustration'))
    print(f'category: {len(files)} files  ({len(plates)} plates, {len(others)} others)')

    info = {}
    for group in (plates, others):
        for i in range(0, len(group), 50):
            info.update(image_info(group[i:i + 50]))
            time.sleep(0.3)

    counts = {}

    def assign(name, title):
        s = slug(name)
        counts[s] = counts.get(s, 0) + 1
        base = s if counts[s] == 1 else f'{s}-{counts[s]}'
        ext = 'png' if title.lower().endswith('.png') else 'jpg'
        return f'{base}.{ext}'

    plan = []
    for t in plates:
        name = parse_illustration(get_head(info[t]['desc']))
        if name:
            plan.append((assign(name, t), info[t]['url']))
    for t in others:
        name = parse_other(t)
        if name:
            plan.append((assign(name, t), info[t]['url']))

    ok = err = skip = 0
    for fname, url in plan:
        dest = os.path.join(OUT, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            skip += 1; continue
        try:
            with open(dest, 'wb') as f:
                f.write(fetch(url))
            ok += 1; time.sleep(0.4)
        except Exception as e:
            err += 1; print('ERR', fname, str(e)[:60])
    print(f'done: downloaded={ok} skipped={skip} errors={err} total={len(plan)}')


if __name__ == '__main__':
    main()
