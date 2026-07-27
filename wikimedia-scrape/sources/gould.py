"""Source: *The Birds of Europe* (John Gould, 5 volumes).

Most files are named by English common name ("GouldBirdsEuropeIBarn Owl.jpg"),
but most plates carry a `<Genus species> (illustrations)` member category on
Commons - a far cleaner signal than the filename. `plan` resolves each file to
a binomial by, in order: that category; a Latin binomial embedded in the
filename ("Asio otus by John Gould.jpg"); or COMMON_NAMES, for the ~215
"GouldBirdsEurope<vol><CommonName>" plates that carry only a volume category
and a bare English name.
"""
import re

from common.naming import to_binomial

NAME = "gould"

# Plates with no species category, keyed by their squashed lowercase common
# name (see _from_common_name). Modern eBird / BirdNET v2.4 binomials, so a
# curated cut-out drops straight into assets/birds/.
#
# Gould's archaic names with no BirdNET v2.4 label are deliberately absent,
# so plan() drops the plate: the frame could never surface the species.
#   bimaculatedteal, blackwingedgull, creamcolouredcourser, dalmatianpelican,
#   desmarestscormorant, doubtfulsparrow, duskyshearwater, greatauk,
#   greatbustard, ivorygull, keptushkalapwing, leadcolouredfalcon,
#   littlecormorant, maguartstork, marbledduck, marmoraswarbler,
#   redbreastedgoose, redchesteddottrell, rosygrosbeak, ruffedbustard,
#   shorttoedptarmigan, slenderbilledcurlew, vinousgrosbeak, westernduck,
#   whiteheadedduck, winterfinch
COMMON_NAMES = {
    "americanbittern": "botaurus lentiginosus",
    "andalusianturnix": "turnix sylvaticus",
    "avocet": "recurvirostra avosetta",
    "baillonscrake": "zapornia pusilla",
    "barbarypartridgegreekpartridge": "alectoris barbara",
    "barrowsduck": "bucephala islandica",
    "bartailedgodwit": "limosa lapponica",
    "bartramssandpiper": "bartramia longicauda",
    "blackbelliedwaterouzel": "cinclus cinclus",
    "blackgrouse": "lyrurus tetrix",
    "blackstork": "ciconia nigra",
    "blacktailedgodwit": "limosa limosa",
    "blackthroateddiver": "gavia arctica",
    "brentgoose": "branta bernicla",
    "broadbilledtringa": "calidris falcinellus",
    "brunnichsguillemot": "uria lomvia",
    "buffbreastedsandpiper": "calidris subruficollis",
    "bullfinch": "pyrrhula pyrrhula",
    "bulwerspetrel": "bulweria bulwerii",
    "calandralark": "melanocorypha calandra",
    "capercailzie": "tetrao urogallus",
    "caspiantern": "hydroprogne caspia",
    "chaffinch": "fringilla coelebs",
    "chough": "pyrrhocorax pyrrhocorax",
    "citrilfinch": "carduelis citrinella",
    "collaredpratincole": "glareola pratincola",
    "commonbittern": "botaurus stellaris",
    "commonbunting": "emberiza calandra",
    "commoncormorant": "phalacrocorax carbo",
    "commoncrane": "grus grus",
    "commoncreeper": "certhia familiaris",
    "commoncurlew": "numenius arquata",
    "commonflamingo": "phoenicopterus roseus",
    "commongallinule": "gallinula chloropus",
    "commongull": "larus canus",
    "commonheron": "ardea cinerea",
    "commonnightheron": "nycticorax nycticorax",
    "commonpartridge": "perdix perdix",
    "commonpheasant": "phasianus colchicus",
    "commonptarmigan": "lagopus muta",
    "commonsandpiper": "actitis hypoleucos",
    "commonsheldrake": "tadorna tadorna",
    "commonteal": "anas crecca",
    "commontern": "sterna hirundo",
    "commonwildduck": "anas platyrhynchos",
    "coot": "fulica atra",
    "cretzschmarsbunting": "emberiza caesia",
    "dalmatiannuthatch": "sitta neumayer",
    "domesticswan": "cygnus olor",
    "dottrell": "charadrius morinellus",
    "dunlin": "calidris alpina",
    "earedgrebe": "podiceps nigricollis",
    "egyptiangoose": "alopochen aegyptiaca",
    "eiderduck": "somateria mollissima",
    "europeanfrancolin": "francolinus francolinus",
    "forktailedstormpetrelcommonstormpetrel": "hydrobates pelagicus",
    "fulmarpetrel": "fulmarus glacialis",
    "gadwall": "mareca strepera",
    "garganyteal": "spatula querquedula",
    "glaucousgull": "larus hyperboreus",
    "glossyibis": "plegadis falcinellus",
    "goldeneye": "bucephala clangula",
    "goldenplover": "pluvialis apricaria",
    "goldfinch": "carduelis carduelis",
    "goosander": "mergus merganser",
    "greatblackbackedgull": "larus marinus",
    "greatblackwoodpecker": "dryocopus martius",
    "greatcrestedgrebe": "podiceps cristatus",
    "greategret": "ardea alba",
    "greatsedgewarbler": "acrocephalus arundinaceus",
    "greatsnipe": "gallinago media",
    "greatspottedcuckoo": "clamator glandarius",
    "greatspottedwoodpecker": "dendrocopos major",
    "greensandpiperwoodsandpiper": "tringa ochropus",
    "greenshank": "tringa nebularia",
    "greenwoodpecker": "picus viridis",
    "greycinereousowl": "strix nebulosa",
    "greyheadedgreenwoodpecker": "picus canus",
    "greylagwildgoose": "anser anser",
    "greyphalarope": "phalaropus fulicarius",
    "greyplover": "pluvialis squatarola",
    "greysnipe": "gallinago gallinago",
    "harlequinduck": "histrionicus histrionicus",
    "hawkowl": "surnia ulula",
    "hazelgrouse": "tetrastes bonasia",
    "herringgull": "larus argentatus",
    "hoodedmerganser": "lophodytes cucullatus",
    "hoopoe": "upupa epops",
    "hornedgrebe": "podiceps auritus",
    "hyacinthineporphyrio": "porphyrio porphyrio",
    "hybridgrouse": "lyrurus tetrix x tetrao urogallus",
    "icelandgull": "larus glaucoides",
    "jacksnipe": "lymnocryptes minimus",
    "kentishplover": "charadrius alexandrinus",
    "kingduck": "somateria spectabilis",
    "kittiwakegull": "rissa tridactyla",
    "knot": "calidris canutus",
    "landrail": "crex crex",
    "lapwing": "vanellus vanellus",
    "larkheeledbunting": "calcarius lapponicus",
    "laughinggull": "chroicocephalus ridibundus",
    "lesbianbunting": "emberiza cineracea",
    "lesserblackbackedgull": "larus fuscus",
    "lesserredpole": "acanthis cabaret",
    "lesserspottedwoodpecker": "dryobates minor",
    "littlebittern": "ixobrychus minutus",
    "littlebustard": "tetrax tetrax",
    "littlecrake": "zapornia parva",
    "littleegret": "egretta garzetta",
    "littlegrebe": "tachybaptus ruficollis",
    "littlegull": "hydrocoloeus minutus",
    "littleringdottrell": "charadrius dubius",
    "littlesandpiper": "calidris minuta",
    "littletern": "sternula albifrons",
    "longleggedplover": "himantopus himantopus",
    "longtailedduck": "clangula hyemalis",
    "manksshearwater": "puffinus puffinus",
    "marshbunting": "emberiza schoeniclus",
    "marshsandpiper": "tringa stagnatilis",
    "meadowbunting": "emberiza cia",
    "mealyredpole": "acanthis flammea",
    "moustachetern": "chlidonias hybrida",
    "nattererswarbler": "curruca conspicillata",
    "noddytern": "anous stolidus",
    "northerndiver": "gavia immer",
    "numidiandemoiselle": "anthropoides virgo",
    "oystercatcher": "haematopus ostralegus",
    "parasiticgull": "stercorarius parasiticus",
    "pectoralsandpiper": "calidris melanotos",
    "pinebunting": "emberiza leucocephalos",
    "pintailduck": "anas acuta",
    "pintailedsandgrouse": "pterocles alchata",
    "pomarinegull": "stercorarius pomarinus",
    "purpleheron": "ardea purpurea",
    "purplesandpiper": "calidris maritima",
    "pygmycurlew": "calidris ferruginea",
    "quail": "coturnix coturnix",
    "raven": "corvus corax",
    "redbreastedmerganser": "mergus serrator",
    "redcrestedduck": "netta rufina",
    "redgrouse": "lagopus lagopus",
    "redheadedpochard": "aythya ferina",
    "redleggedpartridge": "alectoris rufa",
    "redneckedgrebe": "podiceps grisegena",
    "redneckedphalarope": "phalaropus lobatus",
    "redshank": "tringa totanus",
    "redthroateddiver": "gavia stellata",
    "reedbunting": "emberiza schoeniclus",
    "richardsonslestris": "stercorarius parasiticus",
    "ringdottrell": "charadrius hiaticula",
    "rockdove": "columba livia",
    "rockptarmigan": "lagopus muta",
    "rook": "corvus frugilegus",
    "roseatetern": "sterna dougallii",
    "rosecolouredpastor": "pastor roseus",
    "ruddysheldrake": "tadorna ferruginea",
    "ruff": "calidris pugnax",
    "rufousbackedegret": "ardeola ralloides",
    "rufousswallow": "cecropis daurica",
    "russetwheatear": "oenanthe hispanica",
    "rusticbunting": "emberiza rustica",
    "sabinesgull": "xema sabini",
    "sabinessnipecommonsnipe": "gallinago gallinago",
    "sanderling": "calidris alba",
    "sandgrouse": "pterocles orientalis",
    "sandwichtern": "thalasseus sandvicensis",
    "sardinianwarbler": "curruca melanocephala",
    "scauppochard": "aythya marila",
    "schinzssandpiper": "calidris alpina",
    "sedgewarbler": "acrocephalus schoenobaenus",
    "semipalmatedsandpiper": "calidris pusilla",
    "serinfinch": "serinus serinus",
    "shorttoedlark": "calandrella brachydactyla",
    "shovellerduck": "spatula clypeata",
    "siberiangrosbeak": "pinicola enucleator",
    "siberianjay": "perisoreus infaustus",
    "silkywarbler": "cettia cetti",
    "siskin": "spinus spinus",
    "skuagull": "stercorarius skua",
    "smew": "mergellus albellus",
    "snowgoose": "anser caerulescens",
    "solangannet": "morus bassanus",
    "sombretitsiberiantit": "poecile lugubris",
    "spoonbill": "platalea leucorodia",
    "spottedcrake": "porzana porzana",
    "spottedredshank": "tringa erythropus",
    "spottedsandpiper": "actitis macularius",
    "spurwingedplover": "vanellus spinosus",
    "squaccoheron": "ardeola ralloides",
    "starling": "sturnus vulgaris",
    "stockdove": "columba oenas",
    "subalpinewarbler": "curruca iberiae",
    "surfscoter": "melanitta perspicillata",
    "temminckstringa": "calidris temminckii",
    "terekgodwit": "xenus cinereus",
    "thickkneedbustard": "burhinus oedicnemus",
    "threetoedwoodpecker": "picoides tridactylus",
    "tuftedduck": "aythya fuligula",
    "turnstone": "arenaria interpres",
    "turtledove": "streptopelia turtur",
    "twite": "linaria flavirostris",
    "velvetscoter": "melanitta fusca",
    "waterrail": "rallus aquaticus",
    "whimbrel": "numenius phaeopus",
    "whistlingswan": "cygnus cygnus",
    "whitebelliedswift": "apus melba",
    "whitecrane": "leucogeranus leucogeranus",
    "whiteeyedduck": "aythya nyroca",
    "whitefrontedgoose": "anser albifrons",
    "whiterumpedwoodpecker": "dendrocopos leucotos",
    "whitestork": "ciconia ciconia",
    "whitethroatlesserwhitethroat": "curruca communis",
    "whitewingedtern": "chlidonias leucopterus",
    "widgeon": "mareca penelope",
    "willowptarmigan": "lagopus lagopus",
    "woodcock": "scolopax rusticola",
    "woodlark": "lullula arborea",
    "woodpigeon": "columba palumbus",
    "wryneck": "jynx torquilla",
    "yellowbreastedbunting": "emberiza aureola",
    "yellowbunting": "emberiza citrinella",
    "yellowwillowwren": "phylloscopus trochilus",
}
CATEGORIES = [
    "Category:The Birds of Europe (Gould) Volume 1",
    "Category:The Birds of Europe (Gould) Volume 2",
    "Category:The Birds of Europe (Gould) Volume 3",
    "Category:The Birds of Europe (Gould) Volume 4",
    "Category:The Birds of Europe (Gould) Volume 5",
]

# Gould's washes are paler than von Wright's; erase less of them, wider halo.
BG = {
    "buffer_frac": 0.032,
    "pale_gray": 218,
    "pale_sat": 20,
    "coloured_sat": 22,
}

ATTRIBUTION = """Images derived from *The Birds of Europe* by John Gould
(1832-1837), via the Wikimedia Commons categories "The Birds of Europe (Gould)
Volume 1-5". Public domain (PD-old-70-expired)."""

# "Category:Genus species (illustrations)" (also matches a trailing subspecies).
_SPECIES_CAT = re.compile(r"^Category:([A-Z][a-z]+) ([a-z]+)(?: [a-z]+)? \(illustrations\)$")


def _from_categories(cats):
    for c in cats:
        m = _SPECIES_CAT.match(c)
        if m:
            return f"{m.group(1).lower()} {m.group(2)}"
    return None


# A bulk archive.org upload of the whole book: every page (plates and text)
# titled with only the book title and a numeric id, e.g. "The birds of Europe
# (1837) (14565247670).jpg". No species signal in title, category, or
# description, so to_binomial would mistake the book title's first two words
# ("The birds") for a binomial. Reject them so they resolve to None and drop.
_BOOK_TITLE = re.compile(r"^The birds of Europe \(\d{4}\)", re.I)

# "GouldBirdsEurope<vol><CommonName>.jpg". The volume numeral runs straight into
# the common name with no separator, so `\bGould\b` never fires and to_binomial
# would read "GouldBirdsEuropeVEared" as a genus. These carry no Latin name at
# all - reject them here so they fall through to COMMON_NAMES.
_VOL_TITLE = re.compile(r"^GouldBirdsEurope(?:III|IV|II|V|I)")


def _from_filename(title):
    n = re.sub(r"\.(jpg|jpeg|png)$", "", title.replace("File:", ""), flags=re.I)
    if _BOOK_TITLE.match(n) or _VOL_TITLE.match(n):
        return None
    n = re.sub(r"\b(by John|John)?\s*Gould\b", "", n, flags=re.I)
    return to_binomial(n)


def _from_common_name(title):
    """Squash the 'GouldBirdsEurope<vol><CommonName>.jpg' tail to a lookup key."""
    n = re.sub(r"\.(jpg|jpeg|png)$", "", title.replace("File:", ""), flags=re.I)
    n = _VOL_TITLE.sub("", n)       # ordered alternation: "VIvory" is vol V, not VI
    return COMMON_NAMES.get(re.sub(r"[^a-z]", "", n.lower()))


def plan(info):
    out = []
    for t in sorted(info):
        name = (_from_categories(info[t]["categories"])
                or _from_filename(t) or _from_common_name(t))
        if name:
            out.append((name, t))
    return out
