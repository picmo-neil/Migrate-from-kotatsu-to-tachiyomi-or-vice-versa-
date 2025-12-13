#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 3.0.0 (Enterprise Architect)
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

# --- Configuration Constants ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'
OUTPUT_FILE = 'Backup.tachibk'
GH_TOKEN = os.environ.get('GH_TOKEN')

# --- External Repository Targets ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.html"
]

DOKI_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

# --- Global Domain Knowledge ---
TLD_LIST = [
    "com", "net", "org", "io", "co", "to", "me", "gg", "cc", "xyz", "fm", 
    "site", "club", "live", "world", "app", "dev", "tech", "space", "top", 
    "online", "info", "biz", "eu", "us", "uk", "ca", "au", "ru", "jp", "br", 
    "es", "fr", "de", "it", "nl", "pl", "in", "vn", "id", "th", "tw", "cn", 
    "kr", "my", "ph", "sg", "hk", "mo", "cl", "pe", "ar", "mx", "ve", "ink"
]

STATIC_MAP = {
    "MANGADEX": "mangadex.org", "MANGANATO": "manganato.com", "MANGAKAKALOT": "mangakakalot.com",
    "BATO": "bato.to", "NHENTAI": "nhentai.net", "VIZ": "viz.com", "WEBTOONS": "webtoons.com",
    "TAPAS": "tapas.io", "BILIBILI": "bilibilicomics.com", "MANGASEE": "mangasee123.com",
    "MANGALIFE": "manga4life.com", "MANGAPARK": "mangapark.net", "KISSMANGA": "kissmanga.org",
    "MANGAFIRE": "mangafire.to", "READM": "readm.org", "NINEMANGA": "ninemanga.com",
    "ASURA": "asuracomic.net", "FLAME": "flamecomics.com", "REAPER": "reaperscans.com",
    "LUMINOUS": "luminousscans.com", "LEVIATAN": "leviatanscans.com", "DRAKE": "drakescans.com",
    "RESET": "reset-scans.com", "XCALIBR": "xcalibrscans.com", "OZUL": "ozulscans.com",
    "TCB": "tcbscans.com", "VOID": "void-scans.com", "COSMIC": "cosmicscans.com",
    "SURYA": "suryascans.com", "MANHUAES": "manhuaes.com", "MANHUAF": "manhuafast.com",
    "MANHUAG": "manhuagold.com", "MANHWA18": "manhwa18.com", "MANHWA18CC": "manhwa18.cc",
    "MANHWACLUB": "manhwa18.club", "TOONILY": "toonily.com", "HIOPER": "hiperdex.com"
}

# --- Infrastructure ---

class SystemUtils:
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
        return SystemUtils.to_signed_64(h)

    @staticmethod
    def extract_domain(url):
        if not url: return None
        try:
            url = str(url).strip()
            clean_url = url if url.startswith('http') else 'https://' + url
            parsed = urlparse(clean_url)
            domain = parsed.netloc.lower()
            
            # Strip common subdomains and prefixes
            for prefix in ['www.', 'api.', 'v1.', 'm.']:
                domain = domain.replace(prefix, '')
            
            # Strip versioned prefixes (v2.site.com -> site.com)
            if domain.startswith('v') and len(domain) > 2 and domain[1].isdigit() and domain[2] == '.':
                domain = domain[3:]
                
            return domain
        except:
            return None

    @staticmethod
    def normalize_string(name):
        if not name: return ""
        n = name.lower()
        
        # Remove TLDs from name if present
        for tld in TLD_LIST:
            if n.endswith('.' + tld):
                n = n[:-(len(tld)+1)]
                break
                
        n = n.upper()
        
        # Remove jargon
        removals = ["(EN)", "(ID)", "SCANS", "SCAN", "COMICS", "COMIC", "NOVELS", "TEAM", "FANSUB", "WEBTOON", "TRANSLATION"]
        for r in removals:
            n = n.replace(r, "")
            n = n.replace(" " + r, "")
            
        # Strip non-alphanumeric
        n = re.sub(r'[^A-Z0-9]', '', n)
        return n

    @staticmethod
    def create_session():
        s = requests.Session()
        retries = Retry(total=10, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MigrationAssistant/3.0'
        })
        return s

# --- Intelligence Modules ---

class ExternalIntelligence:
    def __init__(self):
        self.session = SystemUtils.create_session()
        self.domain_registry = {}  # domain -> (id, name)
        self.name_registry = {}    # normalized_name -> (id, name)
        self.known_ids = set()

    def sync(self):
        print("[System] Synchronizing intelligence databases...")
        self._load_static_map()
        self._sync_keiyoushi()
        self._sync_doki()

    def _load_static_map(self):
        # We don't have IDs for these yet, but we map domains to names
        # Later, if the ID is found via sync, it links up. 
        # If not, the deterministic ID will be consistent based on the mapped name.
        for name, domain in STATIC_MAP.items():
            norm = SystemUtils.normalize_string(name)
            self.name_registry[norm] = (None, name)
            self.domain_registry[domain] = (None, name)

    def _register(self, sid, name, base_url):
        if not sid: return
        
        signed_id = SystemUtils.to_signed_64(sid)
        self.known_ids.add(signed_id)
        
        entry = (signed_id, name)
        
        if base_url:
            domain = SystemUtils.extract_domain(base_url)
            if domain:
                self.domain_registry[domain] = entry
                # Also register root domain
                parts = domain.split('.')
                if len(parts) >= 2:
                    root = parts[-2] + '.' + parts[-1]
                    self.domain_registry[root] = entry

        if name:
            norm = SystemUtils.normalize_string(name)
            self.name_registry[norm] = entry

    def _sync_keiyoushi(self):
        for url in KEIYOUSHI_URLS:
            try:
                print(f"[Sync] Querying {url}...")
                resp = self.session.get(url, timeout=20)
                if resp.status_code != 200: continue
                
                if url.endswith('.json'):
                    data = resp.json()
                    for ext in data:
                        for src in ext.get('sources', []):
                            self._register(src.get('id'), src.get('name'), src.get('baseUrl'))
                            
                elif url.endswith('.html'):
                    # HTML Scraping Logic
                    content = resp.text
                    rows = re.findall(r'<tr[^>]*>.*?</tr>', content, flags=re.DOTALL)
                    for row in rows:
                        name_m = re.search(r'class="name"[^>]*>(.*?)<', row)
                        id_m = re.search(r'data-id="(-?d+)"', row)
                        if name_m and id_m:
                            self._register(int(id_m.group(1)), name_m.group(1).strip(), None)
                            
            except Exception as e:
                print(f"[Warning] Sync failure on {url}: {e}")

    def _sync_doki(self):
        print("[Sync] Analyzing DokiTeam repositories...")
        try:
            resp = self.session.get(DOKI_API, timeout=30)
            if resp.status_code != 200: return
            
            tree = resp.json().get('tree', [])
            kt_files = [f for f in tree if f['path'].endswith('.kt') and 'src/main/kotlin' in f['path']]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(self._parse_kotlin, f): f for f in kt_files}
                for _ in concurrent.futures.as_completed(futures):
                    pass
        except Exception:
            pass

    def _parse_kotlin(self, file_obj):
        url = DOKI_RAW_BASE + file_obj['path']
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                txt = resp.text
                # Heuristic parsing
                id_m = re.search(r'vals+ids*=s*(d+)L?', txt)
                name_m = re.search(r'vals+names*=s*"([^"]+)"', txt)
                url_m = re.search(r'vals+baseUrls*=s*"([^"]+)"', txt)
                
                sid = int(id_m.group(1)) if id_m else None
                name = name_m.group(1) if name_m else file_obj['path'].split('/')[-1].replace('.kt','')
                base = url_m.group(1) if url_m else None
                
                if sid: self._register(sid, name, base)
        except:
            pass

# --- Matching Engine ---

class HeuristicEngine:
    def __init__(self, intelligence):
        self.intel = intelligence

    def identify(self, name, url):
        # Strategy 1: Exact URL/Domain Match (Highest Confidence)
        domain = SystemUtils.extract_domain(url)
        if domain:
            match = self.intel.domain_registry.get(domain)
            if match and match[0]: return match

        # Strategy 2: Exact Name Match
        norm_name = SystemUtils.normalize_string(name)
        match = self.intel.name_registry.get(norm_name)
        if match and match[0]: return match

        # Strategy 3: Permutations
        # Generate variations of the name (e.g., adding/removing 'scans', trying TLDs)
        candidates = self._generate_permutations(name)
        for cand in candidates:
            # Check if permutation is a known domain
            d_match = self.intel.domain_registry.get(cand)
            if d_match and d_match[0]: return d_match
            
            # Check if permutation is a known name
            n_match = self.intel.name_registry.get(SystemUtils.normalize_string(cand))
            if n_match and n_match[0]: return n_match

        # Strategy 4: Fuzzy Match
        keys = list(self.intel.name_registry.keys())
        fuzzy_matches = difflib.get_close_matches(norm_name, keys, n=1, cutoff=0.85)
        if fuzzy_matches:
            return self.intel.name_registry[fuzzy_matches[0]]

        # Strategy 5: Deterministic Fallback (Guarantee)
        # We prefer the mapped name if available, otherwise original
        final_name = name
        if match: final_name = match[1] # Use the official name even if we lack ID
        
        gen_id = SystemUtils.java_hash(final_name)
        return (gen_id, final_name)

    def _generate_permutations(self, name):
        # Create domain-like variations from the name
        n = SystemUtils.normalize_string(name).lower()
        vars = [n, n.replace("scans", "")]
        perms = []
        for v in vars:
            for tld in ['com', 'net', 'org', 'io', 'to']:
                perms.append(f"{v}.{tld}")
        return perms

class ConnectivityProber:
    def __init__(self, intelligence):
        self.intel = intelligence
        self.session = SystemUtils.create_session()

    def probe(self, items):
        print(f"[Prober] Investigating {len(items)} unresolved URLs...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            future_to_item = {executor.submit(self._check_redirect, i['url']): i for i in items}
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                final_url = future.result()
                if final_url:
                    domain = SystemUtils.extract_domain(final_url)
                    match = self.intel.domain_registry.get(domain)
                    if match:
                        # We found a redirect to a known source!
                        # Update knowledge base dynamically
                        print(f"   -> Redirect found: {item['source']} -> {match[1]}")
                        norm = SystemUtils.normalize_string(item['source'])
                        self.intel.name_registry[norm] = match

    def _check_redirect(self, url):
        if not url: return None
        try:
            resp = self.session.head(url, allow_redirects=True, timeout=5)
            return resp.url
        except:
            return None

# --- Main Execution ---

def main():
    # Dependency Check
    try:
        import tachiyomi_pb2
    except ImportError:
        print("❌ Error: tachiyomi_pb2 missing.")
        return

    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Error: Input zip not found.")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Initialize Systems
    intelligence = ExternalIntelligence()
    intelligence.sync()
    
    engine = HeuristicEngine(intelligence)
    prober = ConnectivityProber(intelligence)

    # Read Input
    print("[System] Reading Kotatsu backup...")
    try:
        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not f_file: raise Exception("No favourites data.")
            with z.open(f_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"❌ Read Error: {e}")
        return

    print(f"[System] Processing {len(data)} entries...")

    # Pre-Analysis (Probing Phase)
    # Identify items that don't match any known ID or Domain immediately
    unresolved = []
    for item in data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        name = manga.get('source', '')
        
        # Check if we have a solid match
        match_id, _ = engine.identify(name, url)
        
        # If the ID we generated isn't in our "Known Official IDs" list, it's a fallback or unknown.
        # We should probe the URL to see if it redirects to a known one.
        if match_id not in intelligence.known_ids:
            unresolved.append({'source': name, 'url': url})

    if unresolved:
        prober.probe(unresolved)

    # Migration Phase
    backup = tachiyomi_pb2.Backup()
    processed_ids = set()
    success_count = 0

    for item in data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        raw_name = manga.get('source', '')
        
        # Identify
        sid, name = engine.identify(raw_name, url)
        
        # Add Source to Backup Registry
        if sid not in processed_ids:
            src = tachiyomi_pb2.BackupSource()
            src.sourceId = sid
            src.name = name
            backup.backupSources.append(src)
            processed_ids.add(sid)

        # Add Manga
        bm = backup.backupManga.add()
        bm.source = sid
        bm.url = url
        bm.title = manga.get('title', '')
        bm.artist = manga.get('artist', '')
        bm.author = manga.get('author', '')
        bm.description = manga.get('description', '')
        bm.thumbnailUrl = manga.get('cover_url', '')
        bm.dateAdded = int(item.get('created_at', 0) * 1000) if item.get('created_at') else 0
        
        # State
        st = (manga.get('state') or '').upper()
        if st == 'ONGOING': bm.status = 1
        elif st in ['FINISHED', 'COMPLETED']: bm.status = 2
        else: bm.status = 0
        
        # Genres
        for t in manga.get('tags', []):
            if t: bm.genre.append(str(t))
            
        success_count += 1

    # Save
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print("-" * 50)
    print(f"MIGRATION REPORT")
    print(f"Total: {len(data)} | Migrated: {success_count}")
    print(f"File:  {out_path}")
    print("-" * 50)

if __name__ == "__main__":
    main()
