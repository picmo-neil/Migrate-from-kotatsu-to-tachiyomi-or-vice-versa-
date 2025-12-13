import os
import json
import zipfile
import gzip
import struct
import requests
import re
import time
import random
import difflib
import concurrent.futures
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- SETUP ---
try:
    import tachiyomi_pb2
except ImportError:
    print("❌ Error: tachiyomi_pb2.py not found.")
    exit(1)

# --- CONFIG ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'
GH_TOKEN = os.environ.get('GH_TOKEN')

# Cortex B Targets (Tri-Core Registry)
TARGET_INDEXES = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"
]

# Cortex A Targets (Doki Source)
DOKI_REPO_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- GLOBAL KNOWLEDGE ---
TLD_LIST = [
    "com", "net", "org", "io", "co", "to", "me", "gg", "cc", "xyz", "fm", 
    "site", "club", "live", "world", "app", "dev", "tech", "space", "top", 
    "online", "info", "biz", "eu", "us", "uk", "ca", "au", "ru", "jp", "br", 
    "es", "fr", "de", "it", "nl", "pl", "in", "vn", "id", "th", "tw", "cn", 
    "kr", "my", "ph", "sg", "hk", "mo", "cl", "pe", "ar", "mx", "co", "ve",
    "ink", "wiki", "moe", "fun", "games", "shop", "website", "social", "lat"
]

STATIC_WISDOM = {
    "MANGADEX": "mangadex.org", "MANGANATO": "manganato.com", "MANGAKAKALOT": "mangakakalot.com",
    "BATO": "bato.to", "BATOTO": "bato.to", "NHENTAI": "nhentai.net", "VIZ": "viz.com",
    "WEBTOONS": "webtoons.com", "TAPAS": "tapas.io", "BILIBILI": "bilibilicomics.com",
    "MANGASEE": "mangasee123.com", "MANGALIFE": "manga4life.com", "MANGAPARK": "mangapark.net",
    "KISSMANGA": "kissmanga.org", "MANGAFIRE": "mangafire.to", "MANGATOWN": "mangatown.com",
    "READM": "readm.org", "NINEMANGA": "ninemanga.com", "MANGATUBE": "mangatube.site",
    "MANGAHUB": "mangahub.io", "MANGABOX": "mangabox.me", "MANGAEDEN": "mangaeden.com",
    "MANGAHERE": "mangahere.cc", "MANGAFOX": "fanfox.net", "MANGAPANDA": "mangapanda.com",
    "MANGAREADER": "mangareader.to", "READMANGA": "readmanga.me", "MINTMANGA": "mintmanga.com",
    "ASURA": "asuracomic.net", "ASURASCANS": "asuracomic.net", "FLAME": "flamecomics.com",
    "FLAMECOMICS": "flamecomics.com", "REAPER": "reaperscans.com", "REAPERSCANS": "reaperscans.com",
    "LUMINOUS": "luminousscans.com", "LUMINOUSSCANS": "luminousscans.com", "LEVIATAN": "leviatanscans.com",
    "LEVIATANSCANS": "leviatanscans.com", "DRAKE": "drakescans.com", "DRAKESCANS": "drakescans.com",
    "RESET": "reset-scans.com", "RESETSCANS": "reset-scans.com", "XCALIBR": "xcalibrscans.com",
    "XCALIBRSCANS": "xcalibrscans.com", "OZUL": "ozulscans.com", "OZULSCANS": "ozulscans.com",
    "TRITINIA": "tritiniascans.ml", "TRITINIASCANS": "tritiniascans.ml", "MANGATX": "mangatx.com",
    "MANGATIGRE": "mangatigre.net", "ASTRASCANS": "astrascans.org", "RST": "readshoujo.com",
    "ZINMANGA": "zinmanga.com", "1STKISS": "1stkissmanga.io", "1STKISSMANGA": "1stkissmanga.io",
    "ZERO": "zeroscans.com", "ZEROSCANS": "zeroscans.com", "MANGABUDDY": "mangabuddy.com",
    "MANGAPILOT": "mangapilot.com", "MANGA3S": "manga3s.com", "MANGA18FX": "manga18fx.com",
    "MANGA18": "manga18.club", "RAWKUMA": "rawkuma.com", "MANGAGO": "mangago.me",
    "DESU": "desu.me", "SELFMANGA": "selfmanga.ru", "RUMANGA": "rumanga.ru",
    "UNIYOMI": "uniyomi.com", "TOONILY": "toonily.com", "HIOPER": "hiperdex.com",
    "COMICK": "comick.io", "COMICK_FUN": "comick.io", "TCB": "tcbscans.com", "TCBSCANS": "tcbscans.com",
    "VOI": "void-scans.com", "VOIDSCANS": "void-scans.com", "COSMIC": "cosmicscans.com",
    "COSMICSCANS": "cosmicscans.com", "SURYA": "suryascans.com", "SURYASCANS": "suryascans.com",
    "DRAGONTEA": "dragontea.ink", "DRAGONTEAIN": "dragontea.ink", "FUS": "fuyollne.com",
    "GALAXY": "galaxymanga.com", "GALAXYMANGA": "galaxymanga.com", "IMPERIAL": "imperialscans.com",
    "IMPERIALSCANS": "imperialscans.com", "INFERNAL": "infernalvoidscans.com", 
    "INFERNALVOID": "infernalvoidscans.com", "KAISER": "kaiserscans.com", "KAISERSCANS": "kaiserscans.com",
    "KITSUNE": "kitsune.club", "KITSUNESCANS": "kitsune.club", "LILY": "lily-manga.com",
    "LILYMANGA": "lily-manga.com", "LYNCX": "lynxscans.com", "LYNXSCANS": "lynxscans.com",
    "MANGACULT": "mangacultivator.com", "CULTIVATOR": "mangacultivator.com", 
    "MANGADODS": "mangadods.com", "DODS": "mangadods.com", "MANGAEFFECT": "mangaeffect.com",
    "EFFECT": "mangaeffect.com", "MANGAFENIX": "manganenix.com", "FENIX": "manganenix.com",
    "MANGAGALAXY": "mangagalaxy.me", "MANGAGEAT": "mangagreat.com", "GREAT": "mangagreat.com",
    "MANGAHO": "mangahosted.com", "HOSTED": "mangahosted.com", "MANGAHZ": "mangahz.com",
    "MANGAI": "mangaii.com", "MANGAINDEX": "mangaindex.com", "MANGAITA": "mangaita.com",
    "MANGAKIK": "mangakik.com", "MANGAKIS": "mangakiss.org", "MANGAKITSUNE": "mangakitsune.com",
    "MANGALOR": "mangalords.com", "LORDS": "mangalords.com", "MANGANELO": "manganelo.com",
    "MANGAPRO": "mangapro.co", "MANGAROCK": "mangarockteam.com", "MANGAROSE": "mangarose.net",
    "MANGASTAR": "mangastar.net", "MANGASTREAM": "mangastream.mobi", "MANGASUSHI": "mangasushi.org",
    "MANGASW": "mangasw.com", "MANGASY": "mangasy.com", "MANGATANK": "mangatank.com",
    "MANGATECA": "mangateca.com", "MANGATOP": "mangatop.com", "MANGATOTAL": "mangatotal.com",
    "MANGATOWN": "mangatown.com", "MANGAUP": "mangaup.net", "MANGAZONE": "mangazoneapp.com",
    "MANHUAES": "manhuaes.com", "MANHUAF": "manhuafast.com", "FAST": "manhuafast.com",
    "MANHUAG": "manhuagold.com", "GOLD": "manhuagold.com", "MANHUAM": "manhuamanga.net",
    "MANHUAP": "manhuaplus.com", "PLUS": "manhuaplus.com", "MANHUAR": "manhuarock.net",
    "ROCK": "manhuarock.net", "MANHUAS": "manhuascan.com", "SCAN": "manhuascan.com",
    "MANHUAT": "manhuatop.com", "TOP": "manhuatop.com", "MANHUAUS": "manhuaus.com",
    "MANHWA18": "manhwa18.com", "MANHWA18CC": "manhwa18.cc", "MANHWA18NET": "manhwa18.net",
    "MANHWACO": "manhwaco.com", "MANHWAF": "manhwaful.com", "FUL": "manhwaful.com",
    "MANHWAG": "manhwagold.com", "MANHWAH": "manhwahentai.me", "HENTAI": "manhwahentai.me",
    "MANHWAIND": "manhwaindo.com", "INDO": "manhwaindo.com", "MANHWAIV": "manhwaivan.com",
    "MANHWAK": "manhwaky.com", "KY": "manhwaky.com", "MANHUAL": "manhualand.com",
    "LAND": "manhualand.com", "MANHWAM": "manhwamanga.com", "MANHWAN": "manhwanew.com",
    "NEW": "manhwanew.com", "MANHWAR": "manhwaraw.com", "RAW": "manhwaraw.com",
    "MANHWAS": "manhwas.net", "MANHWAT": "manhwatop.com", "MANHWAW": "manhwaworld.com",
    "WORLD": "manhwaworld.com"
}

# --- UTILS ---

def to_signed_64(val):
    try:
        val = int(val)
        return struct.unpack('q', struct.pack('Q', val & 0xFFFFFFFFFFFFFFFF))[0]
    except:
        return 0

def java_string_hashcode(s):
    h = 0
    for c in s:
        h = (31 * h + ord(c)) & 0xFFFFFFFFFFFFFFFF
    return to_signed_64(h)

def get_domain(url):
    if not url: return None
    url = str(url).strip()
    clean_url = url.replace("api.", "").replace("www.", "").replace("v1.", "").replace("m.", "")
    if not clean_url.startswith('http'): clean_url = 'https://' + clean_url
    try:
        parsed = urlparse(clean_url)
        domain = parsed.netloc
        domain = domain.replace('www.', '')
        if domain.startswith('v') and len(domain) > 2 and domain[1].isdigit() and domain[2] == '.':
            domain = domain[3:]
        return domain.lower()
    except:
        return None

def get_root_domain(domain):
    if not domain: return ""
    parts = domain.split('.')
    if len(parts) >= 2:
        return parts[-2]
    return domain

def normalize_name(name):
    # Standard cleanup
    if not name: return ""
    n = name.lower()
    # TLD Stripping
    for tld in TLD_LIST:
        if n.endswith(f".{tld}"):
            n = n[:-len(tld)-1]
            break
    n = n.upper()
    suffixes = [
        " (EN)", " (ID)", " (ES)", " (BR)", " (FR)", " (RU)", " (JP)",
        " SCANS", " SCAN", " COMICS", " COMIC", " TOON", " TOONS",
        " MANGAS", " MANGA", " NOVELS", " NOVEL", " TEAM", " FANSUB",
        " WEBTOON"
    ]
    for s in suffixes:
        n = n.replace(s, "")
    # Remove all non-alphanumeric (Skeleton Key)
    n = re.sub(r'[^A-Z0-9]', '', n)
    return n

def get_session():
    s = requests.Session()
    retries = Retry(total=20, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retries))
    if GH_TOKEN:
        s.headers.update({'Authorization': f'token {GH_TOKEN}'})
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })
    return s

# --- 🛰️ CORTEX A: DOKI POLYGLOT SCANNER ---
class DokiCortex:
    def __init__(self):
        self.knowledge = {} 
        self.session = get_session()

    def scan(self):
        print("🛰️ Cortex A: Scanning DokiTeam Repo (Code Breaker)...")
        try:
            resp = self.session.get(DOKI_REPO_API, timeout=30)
            if resp.status_code != 200:
                print(f"⚠️ Repo API blocked: {resp.status_code}.")
                return self.knowledge

            tree = resp.json().get('tree', [])
            kt_files = []
            for f in tree:
                path = f['path']
                if path.endswith('.kt') and ('parsers/site' in path or 'src/main/kotlin' in path):
                    kt_files.append(f)
            
            print(f"   -> Found {len(kt_files)} source files. Breaking code DNA...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
                futures = {executor.submit(self.process_file, f): f for f in kt_files}
                for _ in concurrent.futures.as_completed(futures):
                    pass 
            print(f"   -> Cortex A Learned: {len(self.knowledge)} definitions.")
        except Exception as e:
            print(f"⚠️ Scanner Error: {e}")
        return self.knowledge

    def process_file(self, file_obj):
        path = file_obj['path']
        filename = path.split('/')[-1].replace('.kt', '')
        url = DOKI_RAW_BASE + path
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                self.extract_dna(resp.text, filename)
        except:
            pass

    def extract_dna(self, content, filename):
        # Clean comments
        content = re.sub(r'//.*', '', content)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

        potential_domains = set()
        
        # 1. Regex for class definitions
        class_match = re.search(r'classs+([a-zA-Z0-9_]+)', content)
        class_name = class_match.group(1) if class_match else filename

        # 2. Regex for baseUrl
        base_url_matches = re.findall(r'(?:override|private|protected|open)s+vals+baseUrls*=s*"([^"]+)"', content)
        for match in base_url_matches:
            d = get_domain(match)
            if d: potential_domains.add(d)

        # 3. Regex for Name
        name_match = re.search(r'(?:override|private)s+vals+names*=s*"([^"]+)"', content)
        explicit_name = name_match.group(1) if name_match else None

        # 4. Fallback strings
        if not potential_domains:
            raw_strings = re.findall(r'"([^"s]+.[^"s]+)"', content)
            for s in raw_strings:
                if any(tld in s for tld in ['.com', '.net', '.org', '.io']):
                     d = get_domain(s)
                     if d: potential_domains.add(d)

        # Map Everything
        if potential_domains:
            best_domain = sorted(list(potential_domains), key=len)[0]
            keys = [filename, class_name]
            if explicit_name: keys.append(explicit_name)
            
            for k in keys:
                self.knowledge[normalize_name(k)] = best_domain
                self.knowledge[k] = best_domain

# --- 🔮 STAGE 8: THE ORACLE ---
class Oracle:
    def __init__(self, brain):
        self.brain = brain
        self.session = get_session()

    def consult(self, unbridged_items):
        unique_urls = {}
        for item in unbridged_items:
            u = item.get('url')
            if u and u.startswith('http'):
                unique_urls[u] = item.get('source')
        
        if not unique_urls: return
        print(f"🔮 Oracle: Probing {len(unique_urls)} signals...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_url = {executor.submit(self.probe, u): (u, s) for u, s in unique_urls.items()}
            for future in concurrent.futures.as_completed(future_to_url):
                orig_url, orig_source = future_to_url[future]
                try:
                    final_domain = future.result()
                    if final_domain:
                        match = self.brain.resolve_domain(final_domain)
                        if match:
                            self.brain.name_map[normalize_name(orig_source)] = match
                            orig_domain = get_domain(orig_url)
                            if orig_domain:
                                self.brain.domain_map[orig_domain] = match
                except:
                    pass

    def probe(self, url):
        try:
            resp = self.session.head(url, allow_redirects=True, timeout=8)
            return get_domain(resp.url)
        except:
            try:
                resp = self.session.get(url, allow_redirects=True, timeout=8, stream=True)
                resp.close()
                return get_domain(resp.url)
            except:
                return None

# --- 🧠 BRIDGE BRAIN ---
class BridgeBrain:
    def __init__(self):
        self.domain_map = {} 
        self.root_domain_map = {}
        self.name_map = {}   
        self.skeleton_map = {} # SKELETON KEY
        self.doki_map = {}  
        self.session = get_session()

    def ingest(self):
        print("🧠 BridgeBrain: Initializing The Singularity (v68.0 Omni-Bridge)...")
        doki_cortex = DokiCortex()
        self.doki_map = doki_cortex.scan()

        print("📚 Loading Omni-Database...")
        for k, v in STATIC_WISDOM.items():
            if k not in self.doki_map:
                self.doki_map[k] = v
                self.doki_map[normalize_name(k)] = v

        for url in TARGET_INDEXES:
            print(f"📡 Cortex B: Fetching {url.split('/')[-1]}...")
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    self.parse_registry_json(resp.json())
            except Exception as e:
                print(f"⚠️ Index Error: {e}")

    def parse_registry_json(self, data):
        for ext in data:
            for src in ext.get('sources', []):
                sid = src.get('id')
                name = src.get('name')
                base = src.get('baseUrl')
                
                signed_id = to_signed_64(sid)
                domain = get_domain(base)
                norm = normalize_name(name)
                
                entry = (signed_id, name)
                
                if domain: 
                    self.domain_map[domain] = entry
                    root = get_root_domain(domain)
                    if root: self.root_domain_map[root] = entry
                
                if norm: 
                    self.name_map[norm] = entry
                    self.skeleton_map[norm] = entry # Norm IS the skeleton

    def resolve_domain(self, domain):
        if not domain: return None
        if domain in self.domain_map: return self.domain_map[domain]
        root = get_root_domain(domain)
        if root in self.root_domain_map: return self.root_domain_map[root]
        return None

    def synthesize_permutations(self, name):
        n = normalize_name(name).lower()
        if not n: return []
        candidates = []
        bases = [n, n.replace("scans", "")]
        for base in bases:
            for tld in TLD_LIST:
                candidates.append(f"{base}.{tld}")
        return candidates

    def librarian_match(self, name):
        """The Librarian: Fuzzy Matcher using Difflib"""
        norm_keys = list(self.skeleton_map.keys())
        norm_name = normalize_name(name)
        
        matches = difflib.get_close_matches(norm_name, norm_keys, n=1, cutoff=0.8)
        if matches:
            return self.skeleton_map[matches[0]]
        return None

    def identify(self, kotatsu_name, kotatsu_url):
        # 1. URL/Domain Logic
        manga_domain = get_domain(kotatsu_url)
        match = self.resolve_domain(manga_domain)
        if match: return match

        # 2. Doki Learning
        norm_name = normalize_name(kotatsu_name)
        learned_domain = self.doki_map.get(norm_name) or self.doki_map.get(kotatsu_name)
        if learned_domain:
            match = self.resolve_domain(learned_domain)
            if match: return match

        # 3. Direct Name & Skeleton Key
        if norm_name in self.name_map: return self.name_map[norm_name]
        if norm_name in self.skeleton_map: return self.skeleton_map[norm_name]

        # 4. TLD Heuristic (Name is URL)
        if "." in kotatsu_name:
             d = get_domain(kotatsu_name)
             match = self.resolve_domain(d)
             if match: return match

        # 5. Quantum Permutations
        for cand in self.synthesize_permutations(kotatsu_name):
            d = get_domain(cand)
            match = self.resolve_domain(d)
            if match: return match

        # 6. The Librarian (Fuzzy)
        match = self.librarian_match(kotatsu_name)
        if match: return match

        # 7. FAIL-SAFE: Generate ID
        # If we can't find it, we generate the ID Tachiyomi would expect for a generic source.
        # This ensures it shows up in the library.
        gen_id = java_string_hashcode(kotatsu_name)
        return (gen_id, kotatsu_name)

# --- CONVERTER ---

def main():
    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Backup.zip not found.")
        return

    brain = BridgeBrain()
    brain.ingest()

    print("\n🔄 STARTING MIGRATION (SINGULARITY OMNI-BRIDGE)...")
    with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
        fav_file = next((n for n in z.namelist() if 'favourites' in n), None)
        if not fav_file: raise Exception("No favourites file in zip.")
        fav_data = json.loads(z.read(fav_file))

    print(f"📊 Analyzing {len(fav_data)} entries...")
    
    unbridged_items = []
    
    # Check 1: Initial Pass
    all_real_ids = set(x[0] for x in brain.domain_map.values())
    all_real_ids.update(x[0] for x in brain.root_domain_map.values())
    all_real_ids.update(x[0] for x in brain.name_map.values())
    
    for item in fav_data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        source_name = manga.get('source', '')
        final_id, _ = brain.identify(source_name, url)
        if final_id not in all_real_ids:
            unbridged_items.append({'source': source_name, 'url': url})

    # Oracle Pass
    if unbridged_items:
        Oracle(brain).consult(unbridged_items)
        all_real_ids = set(x[0] for x in brain.domain_map.values())
        all_real_ids.update(x[0] for x in brain.root_domain_map.values())
        all_real_ids.update(x[0] for x in brain.name_map.values())

    # Final Pass
    backup = tachiyomi_pb2.Backup()
    registry_ids = set()
    matches = 0

    for item in fav_data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        source_name = manga.get('source', '')

        final_id, final_name = brain.identify(source_name, url)
‎        
‎        # Count "Real" matches vs "Generated" matches
‎        if final_id in all_real_ids: matches += 1
‎            
‎        if final_id not in registry_ids:
‎            s = tachiyomi_pb2.BackupSource()
‎            s.sourceId = final_id
‎            s.name = final_name
‎            backup.backupSources.append(s)
‎            registry_ids.add(final_id)
‎
‎        bm = backup.backupManga.add()
‎        bm.source = final_id
‎        bm.url = url 
‎        bm.title = manga.get('title', '')
‎        bm.artist = manga.get('artist', '')
‎        bm.author = manga.get('author', '')
‎        bm.description = manga.get('description', '')
‎        bm.thumbnailUrl = manga.get('cover_url', '')
‎        bm.dateAdded = int(item.get('created_at', 0))
‎
‎        state = (manga.get('state') or '').upper()
‎        if state == 'ONGOING': bm.status = 1
‎        elif state in ['FINISHED', 'COMPLETED']: bm.status = 2
‎        else: bm.status = 0
‎        
‎        tags = manga.get('tags', [])
‎        if tags:
‎            for t in tags:
‎                if t: bm.genre.append(str(t))
‎
‎    out_path = os.path.join(OUTPUT_DIR, 'Backup.tachibk')
‎    with gzip.open(out_path, 'wb') as f:
‎        f.write(backup.SerializeToString())
‎
‎    print(f"✅ SUCCESS. Bridge Rate: {matches}/{len(fav_data)} confirmed. Others generated.")
‎    print(f"📂 Saved to {out_path}")
‎
‎if __name__ == "__main__":
‎    main()
 
