#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 4.0.0 
"""

import os
import json
import zipfile
import gzip
import struct
import requests
import re
import time
import difflib
import concurrent.futures
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- Configuration ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'
OUTPUT_FILE = 'Backup.tachibk'
GH_TOKEN = os.environ.get('GH_TOKEN')

# --- External Intelligence Targets ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.html"
]
DOKI_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

# --- Knowledge Base: Stop Words ---
STOP_WORDS = {
    "scans", "scan", "comics", "comic", "manga", "manhua", "manhwa", 
    "read", "online", "team", "fansub", "translation", "toon", "toons", 
    "webtoon", "novel", "novels", "the", "club", "org", "net", "com", "me", "site"
}

# --- Knowledge Base: Graveyard (Dead -> Alive) ---
# Maps dead domains to known active sources to bridge gaps without HTTP redirects
GRAVEYARD_MAP = {
    "manganelo.com": "manganato.com",
    "manganelo.tv": "manganato.com",
    "mangakakalot.com": "mangakakalot.com", # Self-ref
    "mangakakalot.tv": "mangakakalot.com",
    "mangabat.com": "mangabat.com",
    "readmanganato.com": "manganato.com",
    "chapmanganato.com": "manganato.com",
    "mangadex.org": "mangadex.org",
    "mangadex.com": "mangadex.org",
    "mangasee123.com": "mangasee123.com",
    "mangasee.com": "mangasee123.com",
    "mangalife.us": "manga4life.com",
    "manga4life.com": "manga4life.com",
    "1stkissmanga.io": "1stkissmanga.io",
    "1stkissmanga.com": "1stkissmanga.io",
    "1stkissmanga.love": "1stkissmanga.io",
    "manhuaes.com": "manhuaes.com",
    "manhuaes.io": "manhuaes.com",
    "asurascans.com": "asuracomic.net",
    "asuratoon.com": "asuracomic.net",
    "asura.gg": "asuracomic.net",
    "reaperscans.com": "reaperscans.com",
    "reaper-scans.com": "reaperscans.com",
    "luminousscans.com": "luminousscans.com",
    "luminous-scans.com": "luminousscans.com",
    "flamescans.org": "flamecomics.com",
    "flamecomics.com": "flamecomics.com",
    "flame-scans.com": "flamecomics.com",
    "void-scans.com": "void-scans.com",
    "voidscans.net": "void-scans.com",
    "hivescans.com": "void-scans.com",
    "leviatanscans.com": "leviatanscans.com",
    "en.leviatanscans.com": "leviatanscans.com",
    "manhwa18.com": "manhwa18.com",
    "manhwa18.net": "manhwa18.com",
    "manhwa18.cc": "manhwa18.cc",
    "webtoons.com": "webtoons.com",
    "linewebtoon.com": "webtoons.com"
}

# --- Knowledge Base: Omni-Map (Manual Override) ---
# Hardcoded links between Name aliases and Domains/IDs
OMNI_MAP = {
    # Aggregators
    "MANGANATO": "manganato.com", "MANGANELO": "manganato.com", "READMANGANATO": "manganato.com",
    "MANGAKAKALOT": "mangakakalot.com", "KAKALOT": "mangakakalot.com",
    "MANGABAT": "mangabat.com",
    "MANGADEX": "mangadex.org", "DEX": "mangadex.org",
    "BATO": "bato.to", "BATOTO": "bato.to", "BATO.TO": "bato.to",
    "MANGASEE": "mangasee123.com", "MANGASEE123": "mangasee123.com",
    "MANGALIFE": "manga4life.com", "MANGA4LIFE": "manga4life.com",
    "MANGAPARK": "mangapark.net",
    "KISSMANGA": "kissmanga.org", "1STKISSMANGA": "1stkissmanga.io", "1STKISS": "1stkissmanga.io",
    
    # Scan Groups
    "ASURA": "asuracomic.net", "ASURASCANS": "asuracomic.net", "ASURATOON": "asuracomic.net",
    "FLAME": "flamecomics.com", "FLAMESCANS": "flamecomics.com", "FLAMECOMICS": "flamecomics.com",
    "REAPER": "reaperscans.com", "REAPERSCANS": "reaperscans.com",
    "LUMINOUS": "luminousscans.com", "LUMINOUSSCANS": "luminousscans.com",
    "LEVIATAN": "leviatanscans.com", "LEVIATANSCANS": "leviatanscans.com",
    "DRAKE": "drakescans.com", "DRAKESCANS": "drakescans.com",
    "RESET": "reset-scans.com", "RESETSCANS": "reset-scans.com",
    "XCALIBR": "xcalibrscans.com", "XCALIBRSCANS": "xcalibrscans.com",
    "OZUL": "ozulscans.com", "OZULSCANS": "ozulscans.com",
    "TCB": "tcbscans.com", "TCBSCANS": "tcbscans.com",
    "VOID": "void-scans.com", "VOIDSCANS": "void-scans.com", "HIVE": "void-scans.com", "HIVESCANS": "void-scans.com",
    "COSMIC": "cosmicscans.com", "COSMICSCANS": "cosmicscans.com",
    "SURYA": "suryascans.com", "SURYASCANS": "suryascans.com",
    "RST": "reset-scans.com",
    "ASTRASCANS": "astrascans.org", "ASTRA": "astrascans.org",
    
    # Manhwa/Manhua
    "MANHUAES": "manhuaes.com", 
    "MANHUAF": "manhuafast.com", "MANHUAFAST": "manhuafast.com",
    "MANHUAG": "manhuagold.com", "MANHUAGOLD": "manhuagold.com",
    "MANHWA18": "manhwa18.com", "MANHWA18.COM": "manhwa18.com",
    "MANHWA18CC": "manhwa18.cc", "MANHWA18.CC": "manhwa18.cc",
    "TOONILY": "toonily.com", 
    "HIOPER": "hiperdex.com", "HIPERDEX": "hiperdex.com",
    "WEBTOONS": "webtoons.com", "LINEWEBTOON": "webtoons.com",
    "TAPAS": "tapas.io", 
    "BILIBILI": "bilibilicomics.com", "BILIBILICOMICS": "bilibilicomics.com",
    
    # Legacy / Misc
    "READM": "readm.org", 
    "NINEMANGA": "ninemanga.com",
    "MANGATUBE": "mangatube.site",
    "MANGATOWN": "mangatown.com",
    "MANGAPANDA": "mangapanda.com",
    "MANGAFOX": "fanfox.net", "FANFOX": "fanfox.net",
    "MANGATX": "mangatx.com",
    "MANGATIGRE": "mangatigre.net",
    "ZINMANGA": "zinmanga.com"
}

# --- Core Logic ---

class StringUtils:
    @staticmethod
    def to_signed_64(val):
        try:
            val = int(val)
            return struct.unpack('q', struct.pack('Q', val & 0xFFFFFFFFFFFFFFFF))[0]
        except:
            return 0

    @staticmethod
    def java_hash(s):
        h = 0
        for c in s:
            h = (31 * h + ord(c)) & 0xFFFFFFFFFFFFFFFF
        return StringUtils.to_signed_64(h)

    @staticmethod
    def clean_domain(url):
        if not url: return None
        try:
            url = str(url).strip()
            clean = url if url.startswith('http') else 'https://' + url
            parsed = urlparse(clean)
            domain = parsed.netloc.lower()
            
            # Common prefixes
            for p in ['www.', 'api.', 'm.', 'v1.', 'v2.', 'read.']:
                domain = domain.replace(p, '')
            
            # Remove port if present
            if ':' in domain: domain = domain.split(':')[0]
            
            return domain
        except:
            return None

    @staticmethod
    def normalize(text):
        if not text: return ""
        # Lowercase
        t = text.lower()
        # Remove TLDs (simple approach)
        t = re.sub(r'\.(com|net|org|io|to|cc|me|gg|info|xyz|site)$', '', t)
        # Remove separators
        t = t.replace('-', '').replace('_', '').replace('.', '')
        # Remove stop words for strict normalization (Aggressive)
        # We don't remove them here to preserve "Asura Scans" vs "Asura", 
        # but the Token Matcher will handle that.
        # Just alphanumeric
        t = re.sub(r'[^a-z0-9]', '', t)
        return t.upper()

    @staticmethod
    def tokenize(text):
        # Split into conceptual words
        if not text: return set()
        t = text.lower()
        t = re.sub(r'[^a-z0-9]', ' ', t) # Replace separators with space
        parts = t.split()
        
        # Filter stop words
        tokens = {p for p in parts if p not in STOP_WORDS and len(p) > 2}
        return tokens

    @staticmethod
    def jaccard_similarity(text1, text2):
        s1 = StringUtils.tokenize(text1)
        s2 = StringUtils.tokenize(text2)
        if not s1 or not s2: return 0.0
        
        intersection = len(s1.intersection(s2))
        union = len(s1.union(s2))
        return intersection / union

# --- Intelligence Agency ---

class IntelligenceAgency:
    def __init__(self):
        self.session = self._create_session()
        self.domain_map = {}  # domain -> (id, name)
        self.name_map = {}    # normalized_name -> (id, name)
        self.known_ids = set()

    def _create_session(self):
        s = requests.Session()
        retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MigrationEngine/4.0'
        })
        return s

    def initialize(self):
        print("[Intel] Loading Omni-Map & Graveyard...")
        self._load_static_data()
        self._sync_keiyoushi()
        self._sync_doki()

    def _load_static_data(self):
        # 1. Load Omni-Map (Name -> Domain)
        for alias, domain in OMNI_MAP.items():
            norm = StringUtils.normalize(alias)
            self.name_map[norm] = (None, domain)
            self.domain_map[domain] = (None, alias)

        # 2. Load Graveyard (Dead Domain -> Active Domain)
        # We point dead domains to the entry of the active domain if it exists
        # If not, we store it so future registrations link it up.
        for dead, alive in GRAVEYARD_MAP.items():
            self.domain_map[dead] = (None, alive) # Placeholder

    def _register_source(self, sid, name, base_url):
        if not sid: return
        signed_id = StringUtils.to_signed_64(sid)
        self.known_ids.add(signed_id)
        
        entry = (signed_id, name)
        
        if base_url:
            domain = StringUtils.clean_domain(base_url)
            if domain:
                self.domain_map[domain] = entry
                
                # Check Graveyard: Does this new active domain have dead ancestors?
                # If so, update the dead domain entries to point to this new ID
                for dead, alive in GRAVEYARD_MAP.items():
                    if alive == domain:
                        self.domain_map[dead] = entry
                
                # Check Omni-Map: Link hardcoded aliases to this ID
                for k, v in OMNI_MAP.items():
                    if v == domain:
                        norm = StringUtils.normalize(k)
                        self.name_map[norm] = entry

        if name:
            norm = StringUtils.normalize(name)
            self.name_map[norm] = entry
            
            # Register tokens for fuzzy lookup later?
            # Handled in matcher

    def _sync_keiyoushi(self):
        for url in KEIYOUSHI_URLS:
            try:
                print(f"[Sync] Fetching {url}...")
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200: continue
                
                if url.endswith('.json'):
                    data = resp.json()
                    for ext in data:
                        for src in ext.get('sources', []):
                            self._register_source(src.get('id'), src.get('name'), src.get('baseUrl'))
                elif url.endswith('.html'):
                    content = resp.text
                    # HTML Scrape
                    rows = re.findall(r'<tr[^>]*>.*?</tr>', content, flags=re.DOTALL)
                    for row in rows:
                        name_m = re.search(r'class="name"[^>]*>(.*?)<', row)
                        id_m = re.search(r'data-id="(-?d+)"', row)
                        if name_m and id_m:
                            self._register_source(int(id_m.group(1)), name_m.group(1).strip(), None)
            except: pass

    def _sync_doki(self):
        try:
            resp = self.session.get(DOKI_API, timeout=20)
            if resp.status_code != 200: return
            tree = resp.json().get('tree', [])
            kt_files = [f for f in tree if f['path'].endswith('.kt') and 'src/main/kotlin' in f['path']]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                list(executor.map(self._parse_kt, kt_files))
        except: pass

    def _parse_kt(self, f_obj):
        url = DOKI_RAW_BASE + f_obj['path']
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                txt = resp.text
                id_m = re.search(r'vals+ids*=s*(d+)L?', txt)
                name_m = re.search(r'vals+names*=s*"([^"]+)"', txt)
                url_m = re.search(r'vals+baseUrls*=s*"([^"]+)"', txt)
                
                sid = int(id_m.group(1)) if id_m else None
                name = name_m.group(1) if name_m else f_obj['path'].split('/')[-1].replace('.kt','')
                base = url_m.group(1) if url_m else None
                
                if sid: self._register_source(sid, name, base)
        except: pass

# --- Cognitive Matching Engine ---

class MatchingEngine:
    def __init__(self, intel):
        self.intel = intel

    def match(self, name, url):
        # 1. Exact URL/Domain (Includes Graveyard)
        domain = StringUtils.clean_domain(url)
        if domain:
            match = self.intel.domain_map.get(domain)
            if match and match[0]: return match

        # 2. Normalized Name Match
        norm_name = StringUtils.normalize(name)
        match = self.intel.name_map.get(norm_name)
        if match:
            # Check if match is ID or Domain Pointer
            if match[0]: return match
            # If domain pointer, resolve domain
            if isinstance(match[1], str) and '.' in match[1]:
                d_match = self.intel.domain_map.get(match[1])
                if d_match and d_match[0]: return d_match

        # 3. Semantic Token Match (The "Smart" Layer)
        # Checks if tokens overlap significantly (Jaccard > 0.6)
        # e.g. "Asura Toon" vs "Asura Scans" (tokens: {asura, toon} vs {asura}) -> Match
        best_token_match = None
        best_score = 0
        
        # Iterate only through entries with IDs
        for k_norm, entry in self.intel.name_map.items():
            if not entry[0]: continue
            
            # Compare original name vs known name
            score = StringUtils.jaccard_similarity(name, entry[1])
            if score > best_score:
                best_score = score
                best_token_match = entry
        
        if best_score > 0.6: # 60% overlap
            return best_token_match

        # 4. Fuzzy Match (Levenshtein) - Backup for typos
        keys = list(self.intel.name_map.keys())
        fuzzy = difflib.get_close_matches(norm_name, keys, n=1, cutoff=0.85)
        if fuzzy:
            m = self.intel.name_map[fuzzy[0]]
            if m[0]: return m

        # 5. Deterministic Fallback
        # Use the name found in static map if available, else original
        final_name = name
        if match and isinstance(match[1], str): final_name = match[1]
        
        gen_id = StringUtils.java_hash(final_name)
        return (gen_id, final_name)

class ConnectivityProber:
    def __init__(self, intel):
        self.intel = intel
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

    def resolve_dead_links(self, items):
        print(f"[Prober] Analyzing {len(items)} unknown sources for redirects...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            future_to_item = {ex.submit(self._trace, i['url']): i for i in items}
            for fut in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[fut]
                new_url = fut.result()
                if new_url:
                    d = StringUtils.clean_domain(new_url)
                    match = self.intel.domain_map.get(d)
                    if match and match[0]:
                        print(f"   -> Found redirection: {item['source']} -> {match[1]}")
                        self.intel.name_map[StringUtils.normalize(item['source'])] = match

    def _trace(self, url):
        if not url: return None
        try:
            r = self.session.head(url, allow_redirects=True, timeout=8)
            return r.url
        except:
            try:
                r = self.session.get(url, allow_redirects=True, timeout=8, stream=True)
                r.close()
                return r.url
            except: return None

# --- Main ---

def main():
    try:
        import tachiyomi_pb2
    except ImportError:
        print("❌ Error: tachiyomi_pb2 missing.")
        return

    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Input zip missing.")
        return

    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    # 1. Initialize Intelligence
    intel = IntelligenceAgency()
    intel.initialize()
    
    engine = MatchingEngine(intel)
    prober = ConnectivityProber(intel)

    # 2. Load Data
    print("[System] Reading backup...")
    try:
        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not f_file: raise Exception("No favourites.")
            with z.open(f_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print(f"[System] Processing {len(data)} items...")

    # 3. Probe Unknowns
    unknowns = []
    for x in data:
        m = x.get('manga', {})
        url = m.get('url', '') or m.get('public_url', '')
        name = m.get('source', '')
        
        mid, _ = engine.match(name, url)
        if mid not in intel.known_ids:
            unknowns.append({'source': name, 'url': url})
    
    if unknowns: prober.resolve_dead_links(unknowns)

    # 4. Convert
    backup = tachiyomi_pb2.Backup()
    registered = set()
    stats = {'official': 0, 'fallback': 0}

    for item in data:
        m = item.get('manga', {})
        url = m.get('url', '') or m.get('public_url', '')
        name = m.get('source', '')
        
        sid, sname = engine.match(name, url)
        
        if sid in intel.known_ids: stats['official'] += 1
        else: stats['fallback'] += 1
        
        if sid not in registered:
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = sid
            s.name = sname
            backup.backupSources.append(s)
            registered.add(sid)
            
        bm = backup.backupManga.add()
        bm.source = sid
        bm.url = url
        bm.title = m.get('title', '')
        bm.artist = m.get('artist', '')
        bm.author = m.get('author', '')
        bm.description = m.get('description', '')
        bm.thumbnailUrl = m.get('cover_url', '')
        bm.dateAdded = int(item.get('created_at', 0) * 1000) if item.get('created_at') else 0
        
        st = (m.get('state') or '').upper()
        if st == 'ONGOING': bm.status = 1
        elif st in ['FINISHED', 'COMPLETED']: bm.status = 2
        else: bm.status = 0
        
        for t in m.get('tags', []):
            if t: bm.genre.append(str(t))

    # 5. Write
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print("="*50)
    print(f"MIGRATION COMPLETE (v4.0.0)")
    print(f"Total:      {len(data)}")
    print(f"Official:   {stats['official']} (Perfect Match)")
    print(f"Fallback:   {stats['fallback']} (Deterministic)")
    print(f"Output:     {out_path}")
    print("="*50)

if __name__ == "__main__":
    main()
