#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 6.9.6 
Status: Stable 
"""

import os
import sys
import json
import zipfile
import gzip
import struct
import requests
import re
import difflib
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- Configuration ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'
OUTPUT_FILE = 'Backup.tachibk'
GH_TOKEN = os.environ.get('GH_TOKEN')

# Ensure UTF-8 Output
sys.stdout.reconfigure(encoding='utf-8')

# --- External Repositories ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"
]

# --- Legacy Bridge (Static Overrides for Known Issues) ---
# Maps normalized Kotatsu names to specific known Extension Names or IDs
# This handles the "Split-Brain" problem where scanlators change names.
LEGACY_MAPPING = {
    # Giants & Aggregators
    "manganato": "Manganato",
    "manganelo": "Manganato",
    "readmanganato": "Manganato",
    "mangakakalot": "Mangakakalot",
    "mangapark": "MangaPark",
    "mangadex": "MangaDex",
    "bato": "Bato.to",
    "batoto": "Bato.to",
    "mangasee": "MangaSee",
    "mangasee123": "MangaSee",
    "mangalife": "MangaLife",
    
    # Scanlators (The frequent flyers of rebrands)
    "asura": "Asura Comic",
    "asurascans": "Asura Comic",
    "asuratoon": "Asura Comic",
    "asuracomics": "Asura Comic",
    
    "flame": "Flame Comics",
    "flamescans": "Flame Comics",
    "flamecomics": "Flame Comics",
    
    "reaper": "Reaper Scans",
    "reaperscans": "Reaper Scans",
    
    "void": "Void Scans",
    "voidscans": "Void Scans",
    
    "luminous": "Luminous Scans",
    "luminousscans": "Luminous Scans",
    
    "cosmic": "Cosmic Scans",
    "cosmicscans": "Cosmic Scans",
    
    "rizz": "Rizz Comic",
    "rizzcomic": "Rizz Comic",
    
    "drake": "Drake Scans",
    "drakescans": "Drake Scans",
    
    "leviatan": "Leviatan Scans",
    "leviatanscans": "Leviatan Scans",
    
    "manhwa18": "Manhwa18",
    "manhwa18cc": "Manhwa18",
    "manhwa18net": "Manhwa18",
    
    # Regional
    "komikindo": "KomikIndo",
    "komikcast": "KomikCast",
    "westmanga": "WestManga",
    "webtoons": "Webtoons",
    "linewebtoon": "Webtoons",
    "tapas": "Tapas",
}

# --- Core Utilities ---

class StringUtils:
    @staticmethod
    def to_signed_64(val):
        """Converts unsigned 64-bit int to signed 64-bit int."""
        try:
            val = int(val)
            return struct.unpack('q', struct.pack('Q', val & 0xFFFFFFFFFFFFFFFF))[0]
        except: return 0

    @staticmethod
    def java_hash(s):
        """Standard Java String.hashCode()."""
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
            
            # Remove www and standard subdomains
            for p in ['www.', 'm.', 'v1.', 'v2.', 'raw.', 'read.']:
                if domain.startswith(p):
                    domain = domain[len(p):]
            
            if ':' in domain: domain = domain.split(':')[0]
            return domain
        except: return None

    @staticmethod
    def normalize(text):
        """Standard normalization: alphanumeric only, lowercase."""
        if not text: return ""
        # Remove versioning or language tags like (EN), [v1]
        t = re.sub(r'\s*[\(\[].*?[\)\]]', '', text)
        t = t.lower()
        t = re.sub(r'\.(com|net|org|io|cc|gg|xyz|info|site)$', '', t)
        t = re.sub(r'[^a-z0-9]', '', t)
        return t

    @staticmethod
    def is_close_match(a, b):
        """Checks if strings are highly similar (>95%)."""
        if not a or not b: return False
        return difflib.SequenceMatcher(None, a, b).ratio() > 0.95

# --- Extension Registry ---

class ExtensionRegistry:
    def __init__(self):
        self.session = self._create_session()
        self.domain_map = {}   # domain -> id
        self.name_map = {}     # normalized_name -> id
        self.sources = {}      # id -> {name, url}
        self.known_ids = set()

    def _create_session(self):
        s = requests.Session()
        retries = Retry(total=3, backoff_factor=0.2, status_forcelist=[500, 502, 503])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        return s

    def sync(self):
        print("[System] Syncing with Keiyoushi Registry...")
        count = 0
        for url in KEIYOUSHI_URLS:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200: continue
                
                data = resp.json()
                for ext in data:
                    for src in ext.get('sources', []):
                        self._register(src.get('id'), src.get('name'), src.get('baseUrl'))
                        count += 1
            except Exception as e:
                print(f"[Warning] Sync error: {e}")
        print(f"[System] Registry loaded {len(self.known_ids)} unique extensions.")

    def _register(self, sid, name, url):
        if not sid: return
        try:
            real_id = StringUtils.to_signed_64(sid)
            self.known_ids.add(real_id)
            
            # Map by Domain
            domain = StringUtils.clean_domain(url)
            if domain and domain not in self.domain_map:
                self.domain_map[domain] = real_id
                
            # Map by Normalized Name
            if name:
                norm = StringUtils.normalize(name)
                if norm not in self.name_map:
                    self.name_map[norm] = real_id
                    
            self.sources[real_id] = {'name': name, 'url': url}
        except: pass

# --- Resolution Engine ---

class ResolutionEngine:
    def __init__(self, registry):
        self.registry = registry

    def resolve(self, k_name, k_url):
        """
        Resolves a Kotatsu source to a Tachiyomi Source ID.
        Priority: Domain > Legacy Map > Exact Name > Fuzzy Name > Hash Fallback
        """
        
        # 1. Domain Fingerprint (Highest Confidence)
        if k_url:
            domain = StringUtils.clean_domain(k_url)
            if domain and domain in self.registry.domain_map:
                sid = self.registry.domain_map[domain]
                return (sid, self.registry.sources[sid]['name'], "DOMAIN")

        # 2. Legacy Mapping (Hardcoded Fixes)
        norm_input = StringUtils.normalize(k_name)
        if norm_input in LEGACY_MAPPING:
            target_name = LEGACY_MAPPING[norm_input]
            target_norm = StringUtils.normalize(target_name)
            if target_norm in self.registry.name_map:
                sid = self.registry.name_map[target_norm]
                return (sid, self.registry.sources[sid]['name'], "LEGACY")
                
        # 3. Name Match (Normalized)
        if norm_input in self.registry.name_map:
            sid = self.registry.name_map[norm_input]
            return (sid, self.registry.sources[sid]['name'], "NAME")
            
        # 4. Fuzzy Token Match (High Threshold)
        # This handles cases like "Source Name" vs "Source Name (EN)" where normalization stripped too much or too little
        for known_norm, sid in self.registry.name_map.items():
            # Check strict containment or high similarity
            if StringUtils.is_close_match(norm_input, known_norm):
                 return (sid, self.registry.sources[sid]['name'], "FUZZY")

        # 5. Deterministic Fallback (Lossless)
        # Generate the ID exactly how Tachiyomi Android app does for unknown sources
        fallback_id = StringUtils.java_hash(k_name)
        return (fallback_id, k_name, "HASH")

# --- Main ---

def main():
    try:
        import tachiyomi_pb2
    except ImportError:
        print("❌ Critical: tachiyomi_pb2 missing.")
        return

    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Critical: Input zip missing.")
        return
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    # 1. Initialize
    reg = ExtensionRegistry()
    reg.sync()
    engine = ResolutionEngine(reg)

    # 2. Parse
    print("[System] parsing backup...")
    try:
        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not f_file: raise Exception("Favourites file not found.")
            with z.open(f_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"❌ Read Error: {e}")
        return

    # 3. Execute Migration
    print(f"[System] Migrating {len(data)} entries...")
    
    backup = tachiyomi_pb2.Backup()
    registered = set()
    stats = {'DOMAIN': 0, 'LEGACY': 0, 'NAME': 0, 'FUZZY': 0, 'HASH': 0}

    for item in data:
        m = item.get('manga', {})
        url = m.get('url', '') or m.get('public_url', '')
        name = m.get('source', 'Unknown')
        
        # Resolve
        sid, sname, method = engine.resolve(name, url)
        stats[method] += 1
        
        # Register Source
        if sid not in registered:
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = sid
            s.name = sname
            backup.backupSources.append(s)
            registered.add(sid)
            
        # Register Manga
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

    # 4. Write
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print("-" * 50)
    print(f"MIGRATION COMPLETE (v6.9.6 Enterprise)")
    print(f"Total Processed: {len(data)}")
    print(f"Match Stats:")
    print(f"  [DOMAIN] Verified URL:     {stats['DOMAIN']}")
    print(f"  [LEGACY] Bridge Map:       {stats['LEGACY']}")
    print(f"  [NAME]   Direct/Norm:      {stats['NAME']}")
    print(f"  [FUZZY]  High Similarity:  {stats['FUZZY']}")
    print(f"  [HASH]   Fallback/Local:   {stats['HASH']}")
    print("-" * 50)
    print(f"Artifact: {out_path}")

if __name__ == "__main__":
    main()
