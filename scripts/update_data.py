#!/usr/bin/env python3
"""
Crossover player data updater.

Pulls, from Wikidata, every person recorded as a member of one of the game's clubs
(property P54 "member of sports team", all non-deprecated statements, so a player's
current club does not hide their earlier ones), keeps players with at least two of
these clubs, merges data/extra.txt, writes data/players.txt and injects it into index.html.

Run by .github/workflows/update-data.yml (monthly and on demand). Standard library only.
"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "players.txt"
EXTRA = ROOT / "data" / "extra.txt"
INDEX = ROOT / "index.html"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "CrossoverGameBot/1.0 (https://github.com/yessir03/crossover)"

# Club key (as used in the game) -> Wikidata item. Order matters: it fixes the 2-character club codes.
CLUBS = [
 ("Lyon","Q704"),("Juventus","Q1422"),("Milan","Q1543"),("Inter","Q631"),("Lazio","Q2609"),("Barcelona","Q7156"),
 ("Atalanta","Q1886"),("Fiorentina","Q2052"),("Athletic Bilbao","Q8687"),("Napoli","Q2641"),("Atlético Madrid","Q8701"),
 ("Real Sociedad","Q10315"),("Roma","Q2739"),("Sevilla","Q10329"),("Valencia","Q10333"),("Everton","Q5794"),("PSV","Q11938"),
 ("Villarreal","Q12297"),("Real Betis","Q8723"),("Bayern Münih","Q15789"),("Chelsea","Q9616"),("River Plate","Q15799"),
 ("Arsenal","Q9617"),("Rangers","Q19597"),("Manchester United","Q18656"),("Dortmund","Q41420"),("Manchester City","Q50602"),
 ("Aston Villa","Q18711"),("Hamburg","Q51974"),("Newcastle","Q18716"),("Wolfsburg","Q101859"),("Leverkusen","Q104761"),
 ("Tottenham","Q18741"),("Porto","Q128446"),("West Ham","Q18747"),("Benfica","Q131499"),("Marseille","Q132885"),
 ("Lille","Q19516"),("Celtic","Q19593"),("Feyenoord","Q134241"),("Boca Juniors","Q170703"),("Olympiakos","Q19628"),
 ("Beşiktaş","Q172567"),("Zenit","Q29108"),("Shakhtar","Q172969"),("Werder Bremen","Q51976"),("Monaco","Q180305"),
 ("Al Hilal","Q73965"),("Sporting","Q75729"),("Galatasaray","Q495299"),("Ajax","Q81888"),("Anderlecht","Q187528"),
 ("Liverpool","Q1130849"),("Trabzonspor","Q192641"),("Bursaspor","Q203573"),("LA Galaxy","Q204357"),("PSG","Q483020"),
 ("Başakşehir","Q857938"),("Fenerbahçe","Q6601875"),("Real Madrid","Q8682"),("Inter Miami","Q16844931"),
 ("Al Nassr","Q482764"),("Schalke 04","Q32494"),("Club Brugge","Q190916"),("Al Ittihad","Q309480"),
]
KEYS = [k for k, _ in CLUBS]
QIDS = dict(CLUBS)

# Some clubs also have a "multi-sports club" item that a few footballers are linked to instead of the football team.
# Only people whose occupation is association football player are taken from these.
ALT_ITEMS = {"Galatasaray": ["Q43134"], "Fenerbahçe": ["Q19648"], "Bursaspor": ["Q6096484"], "Trabzonspor": ["Q3536136", "Q28214543"]}

# Wikipedia editions whose "<Club> players" categories are read as a second source (club item -> P6112 category).
WIKIS = ["en", "tr", "es", "de", "it", "fr", "pt", "nl", "ru", "uk", "el", "ar"]
MIN_PLAYERS = 7000          # safety net: never publish a suspiciously small dataset
MIN_WIKIS = 2               # Wikipedia editions that must agree on a club link Wikidata lacks
MIN_PER_CLUB = 20

LANGS = ["en", "tr", "es", "de", "fr", "it", "pt", "nl"]
QUERY = """
SELECT ?p ?sl %s WHERE {
  ?p p:P54 ?st . ?st ps:P54 wd:%%s ; wikibase:rank ?rk .
  FILTER(?rk != wikibase:DeprecatedRank)
  ?p wdt:P31 wd:Q5 ; wikibase:sitelinks ?sl .
  FILTER NOT EXISTS { ?p wdt:P21 wd:Q6581072 }
  %s
}""" % (" ".join("?" + l for l in LANGS),
        "\n  ".join('OPTIONAL { ?p rdfs:label ?%s FILTER(lang(?%s) = "%s") }' % (l, l, l) for l in LANGS))

# Greek / Cyrillic letters that look like Latin ones (a common form of vandalism: "Αrda Güler" with a Greek Alpha)
CONFUSABLE = str.maketrans({
    "Α":"A","Β":"B","Ε":"E","Ζ":"Z","Η":"H","Ι":"I","Κ":"K","Μ":"M","Ν":"N","Ο":"O","Ρ":"P","Τ":"T","Υ":"Y","Χ":"X",
    "ο":"o","ν":"v","ρ":"p","τ":"t","ι":"i","κ":"k","α":"a","ε":"e",
    "А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","Х":"X","І":"I","Ј":"J","Ѕ":"S",
    "а":"a","е":"e","о":"o","р":"p","с":"c","у":"y","х":"x","і":"i","ј":"j","ѕ":"s"})

def clean(name):
    """Fix look-alike letters inside an otherwise Latin-script name."""
    if not name: return name
    latin = sum(1 for ch in name if "a" <= ch.lower() <= "z" or "\u00c0" <= ch <= "\u024f")
    letters = sum(1 for ch in name if ch.isalpha())
    return name.translate(CONFUSABLE) if letters and latin / letters >= 0.5 else name

ALT_QUERY = QUERY.replace("?p wdt:P31 wd:Q5 ;", "?p wdt:P31 wd:Q5 ; wdt:P106 wd:Q937857 ;")

DETAILS = """
SELECT ?p ?sl %s WHERE {
  VALUES ?p { %%s }
  ?p wdt:P31 wd:Q5 ; wikibase:sitelinks ?sl .
  FILTER NOT EXISTS { ?p wdt:P21 wd:Q6581072 }
  %s
}""" % (" ".join("?" + l for l in LANGS),
        "\n  ".join('OPTIONAL { ?p rdfs:label ?%s FILTER(lang(?%s) = "%s") }' % (l, l, l) for l in LANGS))

def http_json(url):
    for i in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            print(f"  retry {i+1}: {e}", file=sys.stderr); time.sleep(3 * (i + 1))
    raise SystemExit("Wikipedia did not answer; nothing was changed.")

def category_titles():
    """club key -> [(wiki, 'Category:...'), ...] via each club's 'category for members of a team' (P6112)."""
    values = " ".join("wd:" + q for q in QIDS.values())
    rows = sparql("""SELECT ?c ?site ?title WHERE { VALUES ?c { %s } ?c wdt:P6112 ?cat .
      ?art schema:about ?cat ; schema:isPartOf ?site ; schema:name ?title . }""" % values)
    by_qid = {q: k for k, q in CLUBS}
    out = {}
    for b in rows:
        site = b["site"]["value"]
        m = re.match(r"https://([a-z\-]+)\.wikipedia\.org/$", site)
        if not m or m.group(1) not in WIKIS: continue
        out.setdefault(by_qid[b["c"]["value"].rsplit("/", 1)[-1]], []).append((m.group(1), b["title"]["value"]))
    return out

def category_members(wiki, title):
    """Wikidata items of the articles in a Wikipedia category."""
    qids, cont = set(), {}
    for _ in range(60):
        params = {"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": title,
                  "gcmnamespace": "0", "gcmlimit": "500", "prop": "pageprops", "ppprop": "wikibase_item", **cont}
        j = http_json(f"https://{wiki}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params))
        for pg in (j.get("query", {}).get("pages", {}) or {}).values():
            q = (pg.get("pageprops") or {}).get("wikibase_item")
            if q: qids.add(q)
        if "continue" not in j: break
        cont = j["continue"]
        time.sleep(0.2)
    return qids

def pick_name(b):
    """Choose the spelling most languages agree on, so a vandalised label in one language loses."""
    votes = {}
    for i, l in enumerate(LANGS):
        v = b.get(l, {}).get("value")
        if not v: continue
        v = clean(v)
        if not any("a" <= ch.lower() <= "z" for ch in v): continue      # skip non-Latin scripts
        votes.setdefault(v, [0, i])[0] += 1
    if not votes: return None
    return sorted(votes.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[0][0]

def sparql(q, tries=5):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:
            wait = 5 * (i + 1)
            print(f"  retry {i+1}/{tries} in {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit("Wikidata did not answer; nothing was changed.")

def _b36(n):
    d = "0123456789abcdefghijklmnopqrstuvwxyz"
    return d[n] if n < 36 else d[n // 36] + d[n % 36]

def main():
    people = {}
    for key, qid in CLUBS:
        rows = sparql(QUERY % qid)
        print(f"{key:20s} {len(rows):5d}")
        if len(rows) < MIN_PER_CLUB:
            raise SystemExit(f"Only {len(rows)} players for {key}; refusing to publish.")
        for b in rows:
            pid = b["p"]["value"].rsplit("/", 1)[-1]
            name = pick_name(b)
            o = people.setdefault(pid, {"n": name, "s": int(b["sl"]["value"]), "c": set()})
            o["c"].add(key)
            if not o["n"] and name: o["n"] = name
        for alt in ALT_ITEMS.get(key, []):
            for b in sparql(ALT_QUERY % alt):
                pid = b["p"]["value"].rsplit("/", 1)[-1]
                o = people.setdefault(pid, {"n": pick_name(b), "s": int(b["sl"]["value"]), "c": set()})
                o["c"].add(key)
        time.sleep(1)

    # second source: Wikipedia "<Club> players" categories in several languages
    cats = category_titles()
    # A club link that Wikidata lacks is accepted only when at least MIN_WIKIS language editions agree,
    # so a mistake in a single Wikipedia (e.g. one edition listing De Bruyne as a Man United player) is ignored.
    for key in KEYS:
        support = {}
        for wiki, title in cats.get(key, []):
            for pid in category_members(wiki, title):
                support[pid] = support.get(pid, 0) + 1
        new = 0
        for pid, n in support.items():
            if n < MIN_WIKIS: continue
            o = people.get(pid)
            if o is None:
                o = people[pid] = {"n": None, "s": None, "c": set(), "check": True}
            if key not in o["c"]: new += 1
            o["c"].add(key)
        print(f"{key:20s} +{new:4d} from {len(cats.get(key, []))} Wikipedia categories")

    # names, popularity and a 'is a person' check for people found only through categories
    todo = [pid for pid, o in people.items() if o.get("check") and len(o["c"]) >= 2]
    print(f"\nChecking {len(todo)} people found only on Wikipedia")
    for i in range(0, len(todo), 200):
        batch = todo[i:i + 200]
        got = {}
        for b in sparql(DETAILS % " ".join("wd:" + q for q in batch)):
            got[b["p"]["value"].rsplit("/", 1)[-1]] = b
        for pid in batch:
            b = got.get(pid)
            if b is None: people.pop(pid, None); continue        # not a person (e.g. a list article)
            people[pid].update(n=pick_name(b), s=int(b["sl"]["value"]), check=False)
        time.sleep(1)
    for pid in [pid for pid, o in people.items() if o.get("check")]:
        people.pop(pid)                                          # category-only people with fewer than 2 clubs

    # manual additions: "Name|Club key,Club key"
    if EXTRA.exists():
        for line in EXTRA.read_text(encoding="utf8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line: continue
            name, clubs = line.split("|", 1)
            cl = {c.strip() for c in clubs.split(",") if c.strip() in KEYS}
            hit = next((o for o in people.values() if o["n"] == name.strip()), None)
            if hit: hit["c"] |= cl
            else: people["extra:" + name] = {"n": name.strip(), "s": 0, "c": cl}

    rows = [o for o in people.values()
            if o["n"] and len(o["c"]) >= 2 and not re.fullmatch(r"Q\d+", o["n"])]
    rows.sort(key=lambda o: (-o["s"], o["n"]))
    if len(rows) < MIN_PLAYERS:
        raise SystemExit(f"Only {len(rows)} players; refusing to publish.")

    head = "#CLUBS " + ";".join(f"{k}={q}" for k, q in CLUBS)
    lines = [head] + [o["n"].replace("|", " ").replace("\n", " ") + "|" + str(o["s"]) + "|" +
                      "".join(_b36(KEYS.index(c)).rjust(2, "0") for c in sorted(o["c"], key=KEYS.index))
                      for o in rows]
    text = "\n".join(lines)
    old = OUT.read_text(encoding="utf8") if OUT.exists() else ""
    OUT.write_text(text, encoding="utf8")

    html = INDEX.read_text(encoding="utf8")
    blob = json.dumps(text, ensure_ascii=False).replace("</", "<\\/")
    new_html, n = re.subn(r"/\*DATA-START\*/.*?/\*DATA-END\*/", lambda m: "/*DATA-START*/" + blob + "/*DATA-END*/", html, count=1, flags=re.S)
    if n != 1: raise SystemExit("Data markers not found in index.html.")
    INDEX.write_text(new_html, encoding="utf8")

    before = {l.split("|")[0] for l in old.splitlines()[1:]}
    after = {l.split("|")[0] for l in lines[1:]}
    print(f"\nPlayers: {len(rows)} (added {len(after - before)}, removed {len(before - after)})")
    summary = ROOT / "data" / "last-update.txt"
    summary.write_text(f"{time.strftime('%Y-%m-%d')}\nplayers={len(rows)}\nadded={len(after-before)}\nremoved={len(before-after)}\n", encoding="utf8")

if __name__ == "__main__":
    main()
