"""HedgeRow crop guide (UK). Compiled from published guidance; pending agronomist review.

Water use: FAO Irrigation & Drainage Paper 56 (Allen et al., 1998) crop coefficients (Kc, Table 12)
and growth-stage lengths (Table 11, closest listed climate). Crop water use = ET0 x Kc.
Growing conditions and pest controls: RHS grow-your-own guides, AHDB and organic-growing practice.
Controls listed are non-chemical or biological product *types*; always check UK approval (HSE) and the label.
"""
import re

FAO56 = {"title": "Allen, Pereira, Raes & Smith (1998). Crop evapotranspiration: guidelines for computing crop water "
                  "requirements. FAO Irrigation and Drainage Paper 56 (Tables 11-12).",
         "url": "https://www.fao.org/4/x0490e/x0490e00.htm"}
HARGREAVES = {"title": "Hargreaves & Samani (1985). Reference crop evapotranspiration from temperature. "
                       "Applied Engineering in Agriculture 1(2): 96-99.", "url": None}
HSE = {"title": "HSE pesticides register: check a product is approved for UK use",
       "url": "https://secure.pesticides.gov.uk/pestreg/"}
UK_CAVEAT = ("Check any product is approved for UK use (HSE register) and follow the label. "
             "These are general crop-care options, not a diagnosis.")
GENERAL_FEEDS = [
    {"name": "Garden compost or well-rotted manure", "use": "Dig in before planting to improve soil structure and water holding."},
    {"name": "Organic mulch (straw, leaf mould, bark)", "use": "Keeps moisture in and weeds down; apply to moist soil."},
    {"name": "Seaweed-based feed", "use": "General tonic feed during active growth."},
]


def rhs(path, name):
    return {"title": f"RHS: How to grow {name}", "url": f"https://www.rhs.org.uk/{path}/grow-your-own"}


def crop(key, name, emoji, aliases, kc, stages, sun_h, temp, ph, harvest, pests, feeds, sources, notes, weather_tips):
    return key, {
        "key": key, "name": name, "emoji": emoji, "aliases": aliases,
        "kc": dict(zip(("ini", "mid", "end"), kc)),
        "stages": dict(zip(("initial", "development", "mid", "late"), stages)),
        "sun_hours": sun_h, "temp_c": dict(zip(("min", "max"), temp)), "ph": ph,
        "harvest_days": harvest, "pests": pests, "feeds": feeds, "sources": [FAO56, *sources, HSE],
        "notes": notes, "weather_tips": weather_tips,
    }


def P(name, signs, controls):
    return {"name": name, "signs": signs, "controls": controls}


SLUGS = P("Slugs and snails", "Ragged holes in leaves; slime trails",
          ["Biological control: Phasmarhabditis hermaphrodita nematodes, watered in when soil is above 5 °C",
           "Ferric phosphate pellets (approved for organic growing), used sparingly",
           "Beer traps and evening hand-picking; encourage frogs, birds and ground beetles"])
APHIDS = P("Aphids", "Clusters of small green or black insects; curled leaves",
           ["Encourage ladybirds, lacewings and hoverflies (flowering margins and hedgerows)",
            "Fatty-acid or plant-oil insecticidal sprays (contact only; spray when bees are not active)",
            "Squash small colonies by hand or wash off with water"])

GUIDE = dict([
    crop("carrot", "Carrots", "🥕", ["carrot", "carrots"], (0.7, 1.05, 0.95), (20, 30, 40, 20), 6, (7, 24), "6.0-6.8",
         (80, 120),
         [P("Carrot fly", "Rusty tunnels in roots; leaves turn reddish",
            ["Insect-proof mesh or fleece over the crop from sowing (low flying pest)",
             "Sow thinly to avoid thinning (the scent attracts the fly)",
             "Fly-resistant varieties"]), SLUGS,
          P("Willow-carrot aphid", "Twisted, yellowing leaves in early summer", APHIDS["controls"])],
         GENERAL_FEEDS[1:], [rhs("vegetables/carrots", "carrots")],
         "Light, stone-free soil; avoid fresh manure (causes forked roots). Keep moisture even to stop splitting.",
         {"heavy_rain": "Firm soil around exposed shoulders after heavy rain to prevent greening.",
          "drought": "Water steadily; a dry spell followed by a soaking splits roots.",
          "frost": "Mature roots tolerate light frost; cover with straw if a hard frost is due.",
          "storm": "Check mesh covers are pegged down."}),
    crop("beetroot", "Beetroot", "🟣", ["beetroot", "beet", "beets", "beetroots"], (0.5, 1.05, 0.95), (15, 25, 20, 10),
         6, (10, 24), "6.5-7.5", (60, 90),
         [P("Beet leaf miner", "Pale blotches and tunnels in leaves",
            ["Pick off affected leaves", "Cover with fleece in spring"]),
          P("Birds", "Seedlings pecked or pulled", ["Netting or fleece over young plants"]), SLUGS],
         GENERAL_FEEDS, [rhs("vegetables/beetroot", "beetroot")],
         "Bolts if checked by cold or drought; sow successionally. Harvest at golf-ball to tennis-ball size.",
         {"heavy_rain": "Hoe lightly once soil dries to stop capping.",
          "drought": "Water every 10-14 days in dry spells; dry roots turn woody.",
          "frost": "Lift and store roots before hard frosts.",
          "storm": "Little risk; check covers are secure."}),
    crop("potato", "Potatoes", "🥔", ["potato", "potatoes", "spud", "spuds"], (0.5, 1.15, 0.75), (25, 30, 45, 30), 6,
         (7, 25), "5.0-6.0", (100, 150),
         [P("Late blight", "Brown patches on leaves and stems in warm, humid weather",
            ["Blight-resistant varieties", "Earth up well to protect tubers",
             "Remove and dispose of infected foliage promptly; do not compost"]),
          SLUGS,
          P("Common scab", "Rough corky patches on tubers",
            ["Water during tuber formation", "Do not lime before potatoes"])],
         GENERAL_FEEDS, [rhs("vegetables/potatoes", "potatoes"),
                         {"title": "AHDB Potatoes: crop and storage guidance", "url": "https://ahdb.org.uk/"}],
         "Water most at tuber initiation (around flowering). Chit seed tubers for earlier crops.",
         {"heavy_rain": "Check earthing-up after heavy rain so tubers stay covered.",
          "drought": "Prioritise water at flowering, when tubers are forming.",
          "frost": "Earth up or fleece emerging shoots; frost blackens foliage.",
          "storm": "Little wind risk; watch for blight in the humid days after storms."}),
    crop("onion", "Onions", "🧅", ["onion", "onions", "shallot", "shallots"], (0.7, 1.05, 0.75), (15, 25, 70, 40), 6,
         (7, 25), "6.0-7.0", (120, 150),
         [P("Allium leaf miner / onion fly", "Wilting leaves; maggots or tunnels in bulbs",
            ["Insect-proof mesh during spring and autumn egg-laying"]),
          P("Downy mildew", "Grey-purple fuzz on leaves in damp weather", ["Wide spacing for airflow", "Rotate crops"]),
          P("White rot", "Yellowing; white fluffy growth on bulb base", ["Long rotation (8+ years)", "Remove affected plants"])],
         GENERAL_FEEDS[1:], [rhs("vegetables/onions", "onions")],
         "Stop watering once bulbs swell and leaves start to yellow, to help storage.",
         {"heavy_rain": "Lift and dry ripe bulbs before prolonged wet weather.",
          "drought": "Water only in long dry spells while bulbs are swelling.",
          "frost": "Hardy; autumn sets can lift in frost, so firm them back in.",
          "storm": "Little risk."}),
    crop("lettuce", "Lettuce", "🥬", ["lettuce", "lettuces", "salad", "salad leaves"], (0.7, 1.0, 0.95), (20, 30, 15, 10),
         4, (7, 21), "6.5-7.0", (50, 80),
         [SLUGS, APHIDS, P("Downy mildew", "Yellow patches with grey fuzz underneath",
                            ["Resistant varieties", "Water in the morning at the base", "Space for airflow"])],
         GENERAL_FEEDS[:2], [rhs("vegetables/lettuce", "lettuce")],
         "Tolerates partial shade; bolts in heat (over about 24 °C) and drought.",
         {"heavy_rain": "Watch for slugs after rain.",
          "drought": "Water little and often; dry plants bolt and turn bitter.",
          "frost": "Fleece young plants.", "storm": "Cover with fleece against hail damage."}),
    crop("cabbage", "Cabbage and brassicas", "🥦", ["cabbage", "cabbages", "broccoli", "kale", "cauliflower",
                                                    "brussels sprouts", "sprouts", "brassica", "brassicas"],
         (0.7, 1.05, 0.95), (40, 60, 50, 15), 6, (5, 25), "6.5-7.5", (90, 180),
         [P("Cabbage white caterpillars", "Holes in leaves; green caterpillars",
            ["Fine insect mesh or butterfly netting over the crop",
             "Bacillus thuringiensis (Bt) biological insecticide, if approved for your use",
             "Hand-pick eggs and caterpillars"]),
          P("Cabbage root fly", "Wilting young plants; maggots on roots", ["Brassica collars at planting", "Fleece or mesh"]),
          P("Clubroot", "Swollen, distorted roots; wilting", ["Lime soil to pH 7 or above", "Long rotation", "Resistant varieties"])],
         GENERAL_FEEDS, [rhs("vegetables/cabbages", "cabbages")],
         "Firm soil and steady moisture; tall brassicas need staking in exposed sites.",
         {"heavy_rain": "Re-firm soil around stems after heavy rain.",
          "drought": "Water deeply every week or so in dry weather.",
          "frost": "Most are hardy; frost sweetens kale and sprouts.",
          "storm": "Stake tall plants (sprouts, kale) and earth up stems."}),
    crop("peas", "Peas", "🫛", ["pea", "peas", "mangetout", "sugar snap"], (0.5, 1.15, 1.10), (15, 25, 35, 15), 6,
         (7, 24), "6.0-7.5", (70, 90),
         [P("Pea moth", "Maggots inside pods", ["Fleece or mesh during flowering", "Sow early or late to miss the moth"]),
          P("Mice and birds", "Seeds dug up; seedlings pecked", ["Start in modules; net young plants"]),
          P("Powdery mildew", "White powder on leaves late in season", ["Water at the roots in dry spells", "Resistant varieties"])],
         GENERAL_FEEDS[1:], [rhs("vegetables/peas", "peas")],
         "Water well once flowering starts. Peas fix nitrogen; little feeding needed.",
         {"heavy_rain": "Little risk once established.", "drought": "Water at flowering and pod fill.",
          "frost": "Fleece seedlings.", "storm": "Check supports and netting are secure."}),
    crop("broad_beans", "Broad beans", "🫘", ["broad bean", "broad beans", "fava", "faba bean", "faba beans"],
         (0.5, 1.15, 1.10), (15, 25, 35, 15), 6, (5, 24), "6.5-7.5", (80, 100),
         [P("Blackfly", "Dense black aphids on shoot tips",
            ["Pinch out tips once the first pods set", *APHIDS["controls"][:2]]),
          P("Chocolate spot", "Brown spots on leaves in damp weather", ["Wider spacing", "Avoid excess nitrogen"])],
         GENERAL_FEEDS[1:], [rhs("vegetables/broad-beans", "broad beans")],
         "Hardy; autumn sowings crop earlier and suffer less blackfly.",
         {"heavy_rain": "Little risk.", "drought": "Water at flowering and pod set.",
          "frost": "Autumn-sown plants are hardy; fleece in severe cold.",
          "storm": "Support tall plants with canes and string."}),
    crop("tomato", "Tomatoes", "🍅", ["tomato", "tomatoes", "cherry tomato", "cherry tomatoes"], (0.6, 1.15, 0.8),
         (30, 40, 40, 25), 8, (13, 30), "6.0-6.8", (60, 100),
         [P("Late blight", "Brown leaf patches; rotting fruit outdoors", ["Blight-resistant varieties", "Grow under cover",
                                                                         "Water at the base, not over leaves"]),
          P("Glasshouse whitefly", "Tiny white flies under leaves",
            ["Biological control: Encarsia formosa parasitic wasp (under cover)", "Yellow sticky traps"]),
          P("Blossom end rot", "Black sunken patch at fruit base", ["Water regularly; never let pots dry out"])],
         [{"name": "Tomato or comfrey liquid feed (high potash)", "use": "Weekly once the first fruits set."},
          *GENERAL_FEEDS[:2]], [rhs("vegetables/tomatoes", "tomatoes")],
         "Frost-tender; plant outside only after the last frost. Irregular watering causes split fruit and blossom end rot.",
         {"heavy_rain": "Remove lower leaves to cut splash-borne blight.",
          "drought": "Water daily in hot weather (pots twice).",
          "frost": "Bring plants under cover or fleece; any frost kills them.",
          "heat": "Ventilate greenhouses; shade above 30 °C.",
          "storm": "Tie in stems and check stakes."}),
    crop("courgette", "Courgettes and squash", "🥒", ["courgette", "courgettes", "zucchini", "squash", "pumpkin",
                                                      "marrow", "cucumber", "cucumbers"],
         (0.5, 0.95, 0.75), (25, 35, 25, 15), 8, (15, 30), "6.0-7.5", (45, 60),
         [P("Powdery mildew", "White powder on leaves", ["Water consistently at the base", "Remove badly affected leaves",
                                                          "Space plants for airflow"]),
          SLUGS, P("Cucumber mosaic virus", "Mottled yellow leaves; stunted plants", ["Control aphids", "Remove affected plants"])],
         [{"name": "High-potash liquid feed (e.g. comfrey)", "use": "Every 10-14 days once fruiting starts."},
          *GENERAL_FEEDS[:2]], [rhs("vegetables/courgettes", "courgettes")],
         "Frost-tender and thirsty; water at the base of the plant.",
         {"heavy_rain": "Lift fruit off wet soil on a tile or straw.", "drought": "Water deeply twice a week.",
          "frost": "Any frost kills plants; cover or delay planting out.", "storm": "Protect young plants with cloches."}),
    crop("strawberry", "Strawberries", "🍓", ["strawberry", "strawberries"], (0.4, 0.85, 0.75), (30, 40, 60, 30), 6,
         (10, 26), "5.5-6.5", None,
         [P("Grey mould (botrytis)", "Fuzzy grey mould on fruit", ["Straw mulch under fruit", "Remove mouldy fruit",
                                                                    "Good airflow; water at the base"]),
          P("Birds", "Pecked fruit", ["Netting as fruit ripens"]),
          P("Vine weevil", "Wilting; C-shaped grubs at roots",
            ["Biological control: Steinernema kraussei nematodes in spring and late summer"]), SLUGS],
         [{"name": "High-potash feed", "use": "Every 1-2 weeks from flowering to harvest."}, *GENERAL_FEEDS[1:2]],
         [rhs("fruit/strawberries", "strawberries")],
         "Perennial: fruits in early summer. Replace plants every 3-4 years.",
         {"heavy_rain": "Keep straw under fruit to stop rot.", "drought": "Water during flowering and fruiting.",
          "frost": "Fleece flowers on frosty nights in spring.", "storm": "Secure netting."}),
    crop("apple", "Apples", "🍎", ["apple", "apples", "apple tree", "orchard"], (0.45, 0.95, 0.70), (20, 70, 90, 30), 6,
         (5, 27), "6.0-7.0", None,
         [P("Codling moth", "Maggots in fruit", ["Pheromone traps in May-June to monitor and disrupt mating"]),
          P("Apple scab", "Dark scabby patches on leaves and fruit", ["Resistant varieties", "Clear fallen leaves in autumn"]),
          P("Aphids", "Curled leaves in spring", APHIDS["controls"][:2])],
         GENERAL_FEEDS, [rhs("fruit/apples", "apples")],
         "Perennial: crop in late summer to autumn. Young trees need watering in dry spells.",
         {"heavy_rain": "Little risk to established trees.",
          "drought": "Water young trees (first 2-3 years) deeply every 10 days.",
          "frost": "Spring frost at blossom time can lose the crop; fleece small trees.",
          "storm": "Check stakes and ties; pick ripe fruit before strong winds."}),
    crop("wheat", "Wheat", "🌾", ["wheat", "winter wheat", "spring wheat"], (0.4, 1.15, 0.4), (30, 140, 40, 30), 6,
         (5, 25), "6.0-7.0", (300, 330),
         [P("Aphids (barley yellow dwarf virus)", "Yellowing patches in autumn crops",
            ["Encourage natural enemies with field margins and hedgerows", "Later sowing reduces autumn aphid risk"]),
          P("Septoria tritici", "Brown leaf blotches", ["Choose resistant varieties (AHDB Recommended Lists)", "Avoid very early sowing"]),
          SLUGS],
         [{"name": "Farmyard manure or compost", "use": "Before sowing, based on a soil test."}],
         [{"title": "AHDB Recommended Lists for cereals and oilseeds", "url": "https://ahdb.org.uk/"}],
         "Autumn-sown wheat stands about 10 months in the ground; water needs peak from stem extension to grain fill.",
         {"heavy_rain": "Avoid travelling on wet fields; watch for lodging.",
          "drought": "Most sensitive at flowering and grain fill.",
          "frost": "Hardy once established.", "storm": "Strong wind and rain can flatten (lodge) crops near harvest."}),
    crop("barley", "Barley", "🌾", ["barley", "spring barley", "winter barley"], (0.3, 1.15, 0.25), (15, 25, 50, 30), 6,
         (5, 22), "6.5-7.5", (120, 140),
         [P("Aphids (barley yellow dwarf virus)", "Yellow patches", ["Field margins for natural enemies", "Later sowing"]),
          P("Net blotch / rhynchosporium", "Leaf blotches", ["Resistant varieties (AHDB Recommended Lists)", "Rotation"])],
         [{"name": "Farmyard manure or compost", "use": "Before sowing, based on a soil test."}],
         [{"title": "AHDB Recommended Lists for cereals and oilseeds", "url": "https://ahdb.org.uk/"}],
         "Spring barley is quick-growing; water stress at ear emergence reduces yield.",
         {"heavy_rain": "Watch for lodging.", "drought": "Most sensitive at ear emergence.",
          "frost": "Hardy.", "storm": "Wind and rain can lodge ripe crops."}),
    crop("spinach", "Spinach", "🥬", ["spinach", "chard", "swiss chard", "perpetual spinach"], (0.7, 1.0, 0.95),
         (20, 20, 15, 5), 4, (5, 22), "6.5-7.5", (40, 60),
         [P("Downy mildew", "Yellow patches with grey fuzz", ["Resistant varieties", "Wide spacing"]), SLUGS,
          P("Leaf miner", "Pale tunnels in leaves", ["Pick off affected leaves", "Fleece"])],
         GENERAL_FEEDS[:2], [rhs("vegetables/spinach", "spinach")],
         "Tolerates partial shade; bolts in heat and long dry days.",
         {"heavy_rain": "Watch for slugs.", "drought": "Water regularly to prevent bolting.",
          "frost": "Fairly hardy; cloche for winter leaves.", "storm": "Little risk."}),
])

GENERIC = {
    "key": "generic", "name": None, "emoji": "🌱", "aliases": [], "kc": {"ini": 0.6, "mid": 1.0, "end": 0.8},
    "stages": {"initial": 20, "development": 30, "mid": 40, "late": 20}, "sun_hours": 6,
    "temp_c": {"min": 7, "max": 25}, "ph": "6.0-7.0", "harvest_days": None, "pests": [SLUGS, APHIDS],
    "feeds": GENERAL_FEEDS, "sources": [FAO56, HSE], "weather_tips": {},
    "notes": "This crop isn't in our guide yet, so general vegetable values are used. Advice is less precise.",
}

_ALIASES = {re.sub(r"[^a-z ]", "", a): k for k, c in GUIDE.items() for a in c["aliases"]}


def match_crop(name: str) -> dict:
    """Map free text ('Carrots', 'beet', 'Maris Piper potatoes') to a guide entry, or a generic profile."""
    text = re.sub(r"[^a-z ]", " ", (name or "").lower()).strip()
    text = re.sub(r"\s+", " ", text)
    if text in _ALIASES:
        return GUIDE[_ALIASES[text]]
    # longest alias contained in the text wins ("maris piper potatoes" -> potato)
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return GUIDE[_ALIASES[alias]]
    return {**GENERIC, "name": name.strip().title() if name else "Crop"}
