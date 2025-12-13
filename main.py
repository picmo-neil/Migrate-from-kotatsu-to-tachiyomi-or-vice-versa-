#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 2.0.0
Description: Maps manga entries from Kotatsu backups to Tachiyomi protobuf format.
"""

import os
import json
import zipfile
import gzip
import struct
import requests
import re
import difflib
import concurrent.futures
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- Configuration ---
INPUT_FILE = 'Backup.zip'
OUTPUT_DIR = 'output'
OUTPUT_FILE = 'Backup.tachibk'
GH_TOKEN = os.environ.get('GH_TOKEN')

# --- External Resource Definitions ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.html"
]

DOKI_API_ENDPOINT = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

# --- Static Data (Truncated for brevity, represents the internal knowledge base) ---
# Common TLDs for domain parsing
TLD_LIST = [
    "com", "net", "org", "io", "co", "to", "me", "gg", "cc", "xyz", "fm", "site", 
    "club", "live", "world", "app", "dev", "tech", "space", "top", "online", 
    "info", "biz", "eu", "us", "uk", "ca", "au", "ru", "jp", "br", "es", "fr", 
    "de", "it", "nl", "pl", "in", "vn", "id", "th", "tw", "cn", "kr", "my", 
    "ph", "sg", "hk", "mo", "cl", "pe", "ar", "mx", "ve", "ink", "wiki", "moe"
]

# Static mapping for high-priority sources
STATIC_SOURCE_MAP = {
    "MANGADEX": "mangadex.org", "MANGANATO": "manganato.com", "MANGAKAKALOT": "mangakakalot.com",
    "BATO": "bato.to", "NHENTAI": "nhentai.net", "VIZ": "viz.com", "WEBTOONS": "webtoons.com",
    "TAPAS": "tapas.io", "BILIBILI": "bilibilicomics.com", "MANGASEE": "mangasee123.com",
    "MANGALIFE": "manga4life.com", "MANGAPARK": "mangapark.net", "ASURA": "asuracomic.net",
    "FLAME": "flamecomics.com", "REAPER": "reaperscans.com", "LUMINOUS": "luminousscans.com",
    "LEVIATAN": "leviatanscans.com", "DRAKE": "drakescans.com", "RESET": "reset-scans.com",
    "XCALIBR": "xcalibrscans.com", "OZUL": "ozulscans.com", "TCB": "tcbscans.com",
    "VOID": "void-scans.com", "COSMIC": "cosmicscans.com", "SURYA": "suryascans.com"
}

# --- Utility Classes ---

class Utils:
    @staticmethod
    def to_signed_64(val):
        """Converts an unsigned 64-bit integer to a signed 64-bit integer."""
        try:
            val = int(val)
            return struct.unpack('q', struct.pack('Q', val & 0xFFFFFFFFFFFFFFFF))[0]
        except Exception:
            return 0

    @staticmethod
    def java_string_hashcode(s):
        """Implements Java's String.hashCode() for ID generation compatibility."""
        h = 0
        for c in s:
            h = (31 * h + ord(c)) & 0xFFFFFFFFFFFFFFFF
        return Utils.to_signed_64(h)

    @staticmethod
    def get_domain(url):
        """Extracts the clean domain from a URL."""
        if not url: return None
        try:
            url = str(url).strip()
            # Normalize protocol
            clean_url = url if url.startswith('http') else 'https://' + url
            parsed = urlparse(clean_url)
            domain = parsed.netloc
            
            # Remove common subdomains
            replacements = ['www.', 'api.', 'v1.', 'm.']
            for r in replacements:
                domain = domain.replace(r, '')
            
            # Remove 'v2.', 'v3.' etc
            if domain.startswith('v') and len(domain) > 2 and domain[1].isdigit() and domain[2] == '.':
                domain = domain[3:]
                
            return domain.lower()
        except Exception:
            return None

    @staticmethod
    def normalize_name(name):
        """Normalizes a source name for comparison."""
        if not name: return ""
        n = name.lower()
        
        # Remove TLDs if present in name
        for tld in TLD_LIST:
            suffix = "." + tld
            if n.endswith(suffix):
                n = n[:-len(suffix)]
                break
        
        n = n.upper()
        # Remove common suffixes
        suffixes = [" (EN)", " (ID)", " SCANS", " SCAN", " COMICS", " COMIC", " NOVELS", " TEAM", " FANSUB"]
        for s in suffixes:
            n = n.replace(s, "")
            
        # Alphanumeric only
        n = re.sub(r'[^A-Z0-9]', '', n)
        return n

    @staticmethod
    def get_http_session():
        """Creates a resilient HTTP session."""
        s = requests.Session()
        retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MigrationUtil/2.0'
        })
        return s

# --- External Data Fetchers ---

class RegistrySync:
    def __init__(self, registry):
        self.registry = registry
        self.session = Utils.get_http_session()

    def sync_all(self):
        print("INFO: Synchronizing external repositories...")
        self._sync_keiyoushi()
        self._sync_doki_team()

    def _sync_keiyoushi(self):
        for url in KEIYOUSHI_URLS:
            try:
                print(f"DEBUG: Fetching {url}...")
                resp = self.session.get(url, timeout=20)
                if resp.status_code == 200:
                    if url.endswith('.json'):
                        self._parse_json(resp.json())
                    elif url.endswith('.html'):
                        self._parse_html(resp.text)
            except Exception as e:
                print(f"WARN: Failed to fetch {url}: {e}")

    def _parse_json(self, data):
        for ext in data:
            for src in ext.get('sources', []):
                self.registry.register(
                    sid=src.get('id'),
                    name=src.get('name'),
                    base_url=src.get('baseUrl')
                )

    def _parse_html(self, html):
        """Scrapes ID and Name from HTML structure."""
        try:
            # Matches table rows in repo listing
            rows = re.findall(r'<tr[^>]*>.*?</tr>', html, flags=re.DOTALL)
            count = 0
            for row in rows:
                name_match = re.search(r'class="name"[^>]*>(.*?)<', row)
                id_match = re.search(r'data-id="(-?d+)"', row)
                
                if name_match and id_match:
                    name = name_match.group(1).strip()
                    sid = int(id_match.group(1))
                    self.registry.register(sid=sid, name=name)
                    count += 1
            print(f"INFO: HTML Parser recovered {count} definitions.")
        except Exception as e:
            print(f"WARN: HTML Parsing error: {e}")

    def _sync_doki_team(self):
        print("INFO: Analyzing DokiTeam Kotlin sources...")
        try:
            resp = self.session.get(DOKI_API_ENDPOINT, timeout=30)
            if resp.status_code != 200: return

            tree = resp.json().get('tree', [])
            kt_files = [f for f in tree if f['path'].endswith('.kt') and 'src/main/kotlin' in f['path']]
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(self._fetch_and_parse_kt, f): f for f in kt_files}
                for future in concurrent.futures.as_completed(futures):
                    future.result()
        except Exception as e:
            print(f"WARN: DokiTeam sync error: {e}")

    def _fetch_and_parse_kt(self, file_obj):
        url = DOKI_RAW_BASE + file_obj['path']
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                self._extract_metadata_from_kt(resp.text, file_obj['path'])
        except Exception:
            pass

    def _extract_metadata_from_kt(self, content, path):
        # Heuristic extraction of kotlin properties
        filename = path.split('/')[-1].replace('.kt', '')
        
        # Extract ID
        id_match = re.search(r'vals+ids*=s*(d+)L?', content)
        sid = int(id_match.group(1)) if id_match else None

        # Extract Name
        name_match = re.search(r'vals+names*=s*"([^"]+)"', content)
        name = name_match.group(1) if name_match else filename

        # Extract Base URL
        url_match = re.search(r'vals+baseUrls*=s*"([^"]+)"', content)
        base_url = url_match.group(1) if url_match else None

        if sid or base_url:
            self.registry.register(sid=sid, name=name, base_url=base_url)


# --- Core Logic ---

class SourceRegistry:
    def __init__(self):
        self.domain_map = {} # domain -> (id, name)
        self.name_map = {}   # normalized_name -> (id, name)
        self.id_cache = set()

    def register(self, sid=None, name=None, base_url=None):
        if not sid and not base_url: return

        # Ensure ID is signed 64-bit
        final_id = Utils.to_signed_64(sid) if sid else None
        
        # If we only have URL, we can't fully register without ID, 
        # but we can map domain to a potential future entry
        domain = Utils.get_domain(base_url)
        
        entry = (final_id, name)

        if domain and final_id:
            self.domain_map[domain] = entry
        
        if name and final_id:
            norm = Utils.normalize_name(name)
            self.name_map[norm] = entry
            
        if final_id:
            self.id_cache.add(final_id)

    def resolve_by_domain(self, url):
        domain = Utils.get_domain(url)
        if not domain: return None
        
        # Exact match
        if domain in self.domain_map:
            return self.domain_map[domain]
            
        # Root domain match (e.g., www.foo.com -> foo.com)
        parts = domain.split('.')
        if len(parts) >= 2:
            root = parts[-2] + '.' + parts[-1]
            # This is a weak check, usually requires more robust TLD handling
            # relying on exact map is safer, but we can try iterating keys
            pass
            
        return None

    def resolve_by_name(self, name):
        norm = Utils.normalize_name(name)
        if norm in self.name_map:
            return self.name_map[norm]
        return None

    def fuzzy_resolve(self, name):
        norm = Utils.normalize_name(name)
        keys = list(self.name_map.keys())
        matches = difflib.get_close_matches(norm, keys, n=1, cutoff=0.85)
        if matches:
            return self.name_map[matches[0]]
        return None

class MigrationEngine:
    def __init__(self):
        self.registry = SourceRegistry()
        self.syncer = RegistrySync(self.registry)
        self.session = Utils.get_http_session()

    def initialize(self):
        # Load static maps
        for name, domain in STATIC_SOURCE_MAP.items():
            # We don't have IDs for static map yet, relying on dynamic sync to fill gaps
            # or we can hash the name if needed.
            pass
            
        # Run sync
        self.syncer.sync_all()

    def identify_source(self, source_name, source_url):
        # 1. URL Domain Match
        match = self.registry.resolve_by_domain(source_url)
        if match is not None:
            return match

        # 2. Exact Name Match
        match = self.registry.resolve_by_name(source_name)
        if match is not None:
            return match

        # 3. Fuzzy Name Match
        match = self.registry.fuzzy_resolve(source_name)
        if match is not None:
            return match
            
        # 4. Deterministic Fallback (Guarantee Migration)
        # If unknown, we generate a stable ID. User can install extension later.
        gen_id = Utils.java_string_hashcode(source_name)
        return (gen_id, source_name)

    def probe_redirects(self, items):
        """Checks unmapped URLs to see if they redirect to known domains."""
        if not items: return
        print(f"INFO: Probing {len(items)} unresolved URLs for redirects...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_item = {executor.submit(self._head_request, item['url']): item for item in items}
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                final_url = future.result()
                if final_url:
                    # Try to learn
                    domain = Utils.get_domain(final_url)
                    match = self.registry.resolve_by_domain(domain)
                    if match:
                        # Register the discovery
                        norm = Utils.normalize_name(item['source'])
                        self.registry.name_map[norm] = match

    def _head_request(self, url):
        try:
            resp = self.session.head(url, allow_redirects=True, timeout=5)
            return resp.url
        except Exception:
            return None

def main():
    # Verify Imports
    try:
        import tachiyomi_pb2
    except ImportError:
        print("CRITICAL: tachiyomi_pb2 module not found. Run protoc compilation.")
        exit(1)

    if not os.path.exists(INPUT_FILE):
        print(f"CRITICAL: {INPUT_FILE} not found.")
        exit(1)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Init Engine
    engine = MigrationEngine()
    engine.initialize()

    # Load Data
    print("INFO: Reading backup file...")
    try:
        with zipfile.ZipFile(INPUT_FILE, 'r') as z:
            # Find favourites JSON
            json_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not json_file:
                raise Exception("favourites.json not found in archive")
            
            with z.open(json_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"CRITICAL: Failed to read backup zip: {e}")
        exit(1)

    print(f"INFO: Processing {len(data)} manga entries...")

    # First Pass: Identify Unknowns
    unknowns = []
    for item in data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        name = manga.get('source', '')
        
        # Quick check if resolved
        match = engine.identify_source(name, url)
        # If the returned ID is just a hash of the name (Fallback), 
        # we might want to probe url to see if we can find a "Real" extension ID
        # But determining if it's a fallback ID vs real ID requires checking if ID exists in registry
        # We simplify: if it's not in domain map, add to probe list
        domain = Utils.get_domain(url)
        if domain and domain not in engine.registry.domain_map:
            unknowns.append({'source': name, 'url': url})

    # Probe Redirects
    if unknowns:
        engine.probe_redirects(unknowns)

    # Build Output
    backup = tachiyomi_pb2.Backup()
    registered_sources = set()
    
    success_count = 0

    for item in data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        src_name = manga.get('source', '')
        
        sid, final_name = engine.identify_source(src_name, url)
        
        # Add Source definition if new
        if sid not in registered_sources:
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = sid
            s.name = final_name
            backup.backupSources.append(s)
            registered_sources.add(sid)

        # Create Manga Entry
        bm = backup.backupManga.add()
        bm.source = sid
        bm.url = url
        bm.title = manga.get('title', '')
        bm.artist = manga.get('artist', '')
        bm.author = manga.get('author', '')
        bm.description = manga.get('description', '')
        bm.thumbnailUrl = manga.get('cover_url', '')
        bm.dateAdded = int(item.get('created_at', 0) * 1000) if item.get('created_at') else 0
        
        # Status Mapping
        status_str = (manga.get('state') or '').upper()
        if status_str == 'ONGOING': bm.status = 1
        elif status_str in ['FINISHED', 'COMPLETED']: bm.status = 2
        else: bm.status = 0
        
        # Genres
        for tag in manga.get('tags', []):
            if tag: bm.genre.append(str(tag))

        success_count += 1

    # Serialize
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print("-" * 40)
    print(f"MIGRATION COMPLETE")
    print(f"Total Entries: {len(data)}")
    print(f"Migrated:      {success_count}")
    print(f"Output:        {out_path}")
    print("-" * 40)

if __name__ == "__main__":
    main()
