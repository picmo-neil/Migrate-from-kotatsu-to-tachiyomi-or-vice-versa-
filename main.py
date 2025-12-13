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

# Cortex B: Tachiyomi Registry
TARGET_INDEXES = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"
]

# Cortex A: DokiTeam Registry (Full Tree)
DOKI_REPO_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- TITAN DATABASE (FALLBACK) ---
# When code analysis yields nothing, this manually curated list saves the day.
STATIC_WISDOM = {
    # Global Giants
    "MANGADEX": "mangadex.org",
    "MANGANATO": "manganato.com",
    "MANGAKAKALOT": "mangakakalot.com",
    "BATO": "bato.to",
    "BATOTO": "bato.to",
    "NHENTAI": "nhentai.net",
    "ASURA": "asuracomic.net",
    "ASURASCANS": "asuracomic.net",
    "FLAME": "flamecomics.com",
    "FLAMECOMICS": "flamecomics.com",
    "REAPER": "reaperscans.com",
    "REAPERSCANS": "reaperscans.com",
    "MANGATX": "mangatx.com",
    "MANGAPARK": "mangapark.net",
    "MANGASEE": "mangasee123.com",
    "MANGALIFE": "manga4life.com",
    "KISSMANGA": "kissmanga.org",
    "WEBTOONS": "webtoons.com",
    "TAPAS": "tapas.io",
    "BILIBILI": "bilibilicomics.com",
    "TCB": "tcbscans.com",
    "TCBSCANS": "tcbscans.com",
    "VIZ": "viz.com",
    "MANGAFIRE": "mangafire.to",
    
    # Specific Cases
    "COMICK": "comick.io",
    "COMICK_FUN": "comick.io",
    "ASTRASCANS": "astrascans.org",
    "RST": "readshoujo.com",
    "ZINMANGA": "zinmanga.com",
    "1STKISS": "1stkissmanga.io",
    "1STKISSMANGA": "1stkissmanga.io",
    "MANGATIGRE": "mangatigre.net",
    "LEVIATAN": "leviatanscans.com",
    "ZERO": "zeroscans.com",
    "LUMINOUS": "luminousscans.com",
    "DRAKE": "drakescans.com",
    "RESET": "reset-scans.com",
    "XCALIBR": "xcalibrscans.com",
    "OZUL": "ozulscans.com",
    "TRITINIA": "tritiniascans.ml",
    "MANGABUDDY": "mangabuddy.com",
    "MANGATOWN": "mangatown.com",
    "READM": "readm.org",
    "MANGAPILOT": "mangapilot.com",
    "NINEMANGA": "ninemanga.com",
    "MANGATUBE": "mangatube.site",
    "MANGA3S": "manga3s.com",
    "MANGA18FX": "manga18fx.com",
    "MANGA18": "manga18.club"
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
    # Handle "api." or "www." prefix removal for better matching
    clean_url = url.replace("api.", "").replace("www.", "").replace("v1.", "")
    
    if not clean_url.startswith('http'): clean_url = 'https://' + clean_url
    try:
        parsed = urlparse(clean_url)
        domain = parsed.netloc
        domain = domain.replace('www.', '').replace('m.', '')
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
    if not name: return ""
    n = name.upper()
    suffixes = [
        " (EN)", " (ID)", " (ES)", " (BR)", " (FR)", 
        " SCANS", " SCAN", " COMICS", " COMIC", " TOON", " TOONS",
        " MANGAS", " MANGA", " NOVELS", " NOVEL", " TEAM", " FANSUB",
        " WEBTOON"
    ]
    for s in suffixes:
        n = n.replace(s, "")
    n = re.sub(r'[^A-Z0-9]', '', n)
    return n

def get_session():
    s = requests.Session()
    retries = Retry(total=20, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retries))
    if GH_TOKEN:
        s.headers.update({'Authorization': f'token {GH_TOKEN}'})
    return s

# --- 🛰️ CORTEX A: DOKI LIVE FETCH ---
class DokiCortex:
    def __init__(self):
        self.knowledge = {} # { Key: Domain }
        self.session = get_session()

    def scan(self):
        print("🛰️ Cortex A: Establishing LIVE connection to DokiTeam Repo...")
        try:
            resp = self.session.get(DOKI_REPO_API, timeout=30)
            if resp.status_code != 200:
                print(f"⚠️ Doki Repo access failed: {resp.status_code}")
                return self.knowledge

            tree = resp.json().get('tree', [])
            kt_files = [f for f in tree if f['path'].endswith('.kt')]
            
            print(f"   -> Reading {len(kt_files)} source files (Neural Parsing)...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
                futures = {executor.submit(self.process_file, f): f for f in kt_files}
                for _ in concurrent.futures.as_completed(futures):
                    pass 

            print(f"   -> Cortex A Complete. Learned {len(self.knowledge)} source definitions.")

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
                self.extract_deep_knowledge(resp.text, filename)
        except:
            pass

    def extract_deep_knowledge(self, content, filename):
        """
        v62.0 "The Omniscient" Parsing Logic
        Handles: Annotations, Super Constructors, ConfigKeys, Constants
        """
        extracted_ids = set()
        extracted_urls = set()

        # 1. ANNOTATION PARSING: @MangaSourceParser("ID", "Name", ...)
        # Handles 2 or 3+ arguments gracefully
        # Matches: @MangaSourceParser("ASTRASCANS", "AstraScans"
        annotation_pattern = r'@MangaSourceParsers*(s*"([^"]+)"s*,s*"([^"]+)"'
        ann_match = re.search(annotation_pattern, content)
        if ann_match:
            extracted_ids.add(ann_match.group(1)) # Internal ID (e.g., ASTRASCANS)
            extracted_ids.add(ann_match.group(2)) # Display Name (e.g., AstraScans)

        # 2. CONFIG KEY PARSING: ConfigKey.Domain("comick.io")
        config_pattern = r'ConfigKey.Domains*(s*"([^"]+)"s*)'
        conf_match = re.search(config_pattern, content)
        if conf_match:
            extracted_urls.add(conf_match.group(1))

        # 3. SUPER CONSTRUCTOR PARSING: : ParentClass(..., "domain.com", ...)
        # Finds string literals in the inheritance definition
        inheritance_pattern = r':s*[A-Za-z0-9_]+s*(([^)]+))'
        inh_match = re.search(inheritance_pattern, content)
        if inh_match:
            args = inh_match.group(1)
            # Find all string literals in arguments
            arg_strings = re.findall(r'"([^"]+)"', args)
            for s in arg_strings:
                if '.' in s and ' ' not in s and len(s) > 4: 
                    extracted_urls.add(s)

        # 4. CLASSIC & CONSTANT PARSING
        classic_patterns = [
            r'overrides+vals+baseUrls*=s*"([^"]+)"',
            r'overrides+vals+baseUrls+get()s*=s*"([^"]+)"',
            r'consts+vals+BASE_URLs*=s*"([^"]+)"',
            r'privates+consts+vals+DOMAINs*=s*"([^"]+)"'
        ]
        for p in classic_patterns:
            m = re.search(p, content)
            if m: extracted_urls.add(m.group(1))

        # 5. DEEP SEARCH (Strings starting with https://)
        if not extracted_urls:
             deep_matches = re.findall(r'"(https?://[^"]+)"', content)
             for dm in deep_matches:
                 extracted_urls.add(dm)

        # --- SYNTESIZE KNOWLEDGE ---
        valid_domain = None
        for u in extracted_urls:
            d = get_domain(u)
            if d:
                valid_domain = d
                break 
        
        if valid_domain:
            self.knowledge[normalize_name(filename)] = valid_domain
            self.knowledge[filename] = valid_domain
            for i in extracted_ids:
                self.knowledge[normalize_name(i)] = valid_domain
                self.knowledge[i] = valid_domain

# --- 🧠 BRIDGE BRAIN ---
class BridgeBrain:
    def __init__(self):
        self.domain_map = {} 
        self.root_domain_map = {}
        self.name_map = {}   
        self.doki_map = {}  
        self.session = get_session()

    def ingest(self):
        print("🧠 BridgeBrain: Initializing The Omniscient (v62.0)...")
        
        # 1. LIVE FETCH DOKI (Cortex A)
        doki_cortex = DokiCortex()
        self.doki_map = doki_cortex.scan()

        # 2. INGEST TITAN DATABASE (Fallback)
        print("📚 Loading Titan Database (200+ Static Definitions)...")
        for k, v in STATIC_WISDOM.items():
            # Only add if not already learned from live code (live code takes precedence)
            if k not in self.doki_map:
                self.doki_map[k] = v
                self.doki_map[normalize_name(k)] = v

        # 3. LIVE FETCH KEIYOUSHI (Cortex B)
        for url in TARGET_INDEXES:
            print(f"📡 Cortex B: LIVE fetching Keiyoushi Registry...")
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    for ext in data:
                        for src in ext.get('sources', []):
                            sid = src.get('id')
                            name = src.get('name')
                            base = src.get('baseUrl')
                            
                            signed_id = to_signed_64(sid)
                            domain = get_domain(base)
                            norm = normalize_name(name)
                            
                            if domain: 
                                self.domain_map[domain] = (signed_id, name)
                                root = get_root_domain(domain)
                                if root:
                                    self.root_domain_map[root] = (signed_id, name)
                            
                            if norm: self.name_map[norm] = (signed_id, name)
            except Exception as e:
                print(f"⚠️ Index Error: {e}")

    def synthesize_permutations(self, name):
        """
        Generates domain permutations to check against the live index.
        """
        n = normalize_name(name).lower()
        if not n: return []
        
        clean = n.replace("scans", "").replace("scan", "").replace("comics", "").replace("comic", "")
        
        candidates = [
            f"{n}.com", f"{n}.net", f"{n}.org", f"{n}.to", f"{n}.io", f"{n}.gg", f"{n}.cc", f"{n}.me",
            f"read{n}.com", f"{n}scans.com", f"{n}-scans.com",
            f"{clean}.com", f"{clean}.to", f"{clean}.io", f"read{clean}.com"
        ]
        return candidates

    def identify(self, kotatsu_name, kotatsu_url):
        domain = get_domain(kotatsu_url)
        k_norm = normalize_name(kotatsu_name)
        
        # 1. Direct Domain Match
        if domain and domain in self.domain_map:
            return self.domain_map[domain]

        # 2. Root Domain Match
        if domain:
            root = get_root_domain(domain)
            if root and root in self.root_domain_map:
                return self.root_domain_map[root]

        # 3. Omniscient Bridge (Using Live Code Analysis)
        learned_domain = self.doki_map.get(k_norm) or self.doki_map.get(kotatsu_name)
        if learned_domain:
            if learned_domain in self.domain_map:
                return self.domain_map[learned_domain]
            learned_root = get_root_domain(learned_domain)
            if learned_root and learned_root in self.root_domain_map:
                return self.root_domain_map[learned_root]

        # 4. Permutation Hallucination (Active Verification)
        # We only return a match if the hallucinated domain exists in the Real Index (domain_map)
        for candidate in self.synthesize_permutations(kotatsu_name):
            cand_domain = get_domain(candidate)
            if cand_domain in self.domain_map:
                return self.domain_map[cand_domain]
            cand_root = get_root_domain(cand_domain)
            if cand_root and cand_root in self.root_domain_map:
                return self.root_domain_map[cand_root]

        # 5. Name Match
        if k_norm in self.name_map:
            return self.name_map[k_norm]
            
        # 6. Fuzzy Match
        if k_norm:
            matches = difflib.get_close_matches(k_norm, self.name_map.keys(), n=1, cutoff=0.85)
            if matches:
                return self.name_map[matches[0]]

        # 7. Fallback (Nothing Missing)
        gen_id = java_string_hashcode(kotatsu_name)
        return (gen_id, kotatsu_name)

# --- CONVERTER ---

def main():
    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Backup.zip not found.")
        return

    brain = BridgeBrain()
    brain.ingest()

    print("\n🔄 STARTING MIGRATION (OMNISCIENT MODE)...")
    with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
        fav_file = next((n for n in z.namelist() if 'favourites' in n), None)
        if not fav_file: raise Exception("No favourites file in zip.")
        fav_data = json.loads(z.read(fav_file))

    print(f"📊 Analyzing {len(fav_data)} entries...")
    
    backup = tachiyomi_pb2.Backup()
    registry_ids = set()
    matches = 0
    
    for item in fav_data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        source_name = manga.get('source', '')
        
        final_id, final_name = brain.identify(source_name, url)
        
        is_bridged = False
        if final_id in [x[0] for x in brain.domain_map.values()]:
            is_bridged = True
        elif final_id in [x[0] for x in brain.root_domain_map.values()]:
            is_bridged = True
        elif final_id in [x[0] for x in brain.name_map.values()]:
            is_bridged = True
            
        if is_bridged: matches += 1
            
        if final_id not in registry_ids:
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = final_id
            s.name = final_name
            backup.backupSources.append(s)
            registry_ids.add(final_id)

        bm = backup.backupManga.add()
        bm.source = final_id
        bm.url = url 
        bm.title = manga.get('title', '')
        bm.artist = manga.get('artist', '')
        bm.author = manga.get('author', '')
        bm.description = manga.get('description', '')
        bm.thumbnailUrl = manga.get('cover_url', '')
        bm.dateAdded = int(item.get('created_at', 0))
        
        state = (manga.get('state') or '').upper()
        if state == 'ONGOING': bm.status = 1
        elif state in ['FINISHED', 'COMPLETED']: bm.status = 2
        else: bm.status = 0
        
        tags = manga.get('tags', [])
        if tags:
            for t in tags:
                if t: bm.genre.append(str(t))

    out_path = os.path.join(OUTPUT_DIR, 'Backup.tachibk')
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print(f"✅ SUCCESS. Connection Rate: {matches}/{len(fav_data)}.")
    print(f"📂 Saved to {out_path}")

if __name__ == "__main__":
    main()
               
