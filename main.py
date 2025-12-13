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
import time
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

# --- Constants ---
MANGADEX_SOURCE_ID = 2499283573021220255 # Standard ID for MangaDex in Tachiyomi

# --- Legacy Bridge ---
LEGACY_MAPPING = {
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
    "asura": "Asura Comic",
    "asurascans": "Asura Comic",
    "asuratoon": "Asura Comic",
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
        try:
            val = int(val)
            return struct.unpack('q', struct.pack('Q', val & 0xFFFFFFFFFFFFFFFF))[0]
        except: return 0

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
            for p in ['www.', 'm.', 'v1.', 'v2.', 'raw.', 'read.']:
                if domain.startswith(p):
                    domain = domain[len(p):]
            if ':' in domain: domain = domain.split(':')[0]
            return domain
        except: return None

    @staticmethod
    def normalize(text):
        if not text: return ""
        t = re.sub(r'\s*[\(\[].*?[\)\]]', '', text)
        t = t.lower()
        t = re.sub(r'\.(com|net|org|io|cc|gg|xyz|info|site)$', '', t)
        t = re.sub(r'[^a-z0-9]', '', t)
        return t

    @staticmethod
    def is_close_match(a, b):
        if not a or not b: return False
        return difflib.SequenceMatcher(None, a, b).ratio() > 0.95

# --- Semantic Intelligence ---

class SemanticProcessor:
    NOISE_WORDS = {
        'scan', 'scans', 'scanlation', 'scanlations',
        'comic', 'comics', 'webcomic', 'webcomics',
        'manga', 'manhwa', 'manhua',
        'toon', 'toons', 'webtoon', 'webtoons',
        'team', 'group', 'fansub', 'fansubs',
        'translation', 'translations', 'tl',
        'studio', 'media', 'inc', 'corp', 'org', 'net', 'com',
        'official', 'english', 'en', 'us', 'uk', 'id', 'fr'
    }

    @staticmethod
    def extract_core_identity(text):
        if not text: return ""
        t = text.lower()
        t = re.sub(r'[^a-z0-9\s]', ' ', t)
        tokens = t.split()
        core_tokens = [tok for tok in tokens if tok not in SemanticProcessor.NOISE_WORDS and len(tok) > 2]
        if not core_tokens:
            return StringUtils.normalize(text)
        return "".join(core_tokens)

# --- Active Intelligence Modules ---

class NetworkProbe:
    """Tier 5: Active Network Pathfinder"""
    @staticmethod
    def check_redirect(url):
        if not url or not url.startswith('http'): return None
        try:
            # Short timeout, we just want to know if it moved
            print(f"    [Probe] Checking {url}...")
            resp = requests.head(url, allow_redirects=True, timeout=5)
            if resp.history: # If redirects happened
                final_url = resp.url
                print(f"    [Probe] Redirect found: -> {final_url}")
                return final_url
        except:
            pass
        return None

class LazarusEngine:
    """Tier 6: Content Recovery Protocol (MangaDex Integration)"""
    def __init__(self):
        self.session = requests.Session()
        # MangaDex API rate limit is generous but let's be polite
        self.last_req = 0
    
    def find_manga(self, title, artist=None):
        if not title: return None
        
        # Rate limit (2 req/sec)
        now = time.time()
        if now - self.last_req < 0.5:
            time.sleep(0.5)
        self.last_req = time.time()

        try:
            print(f"    [Lazarus] Searching Archive for: {title}")
            # Search MangaDex
            params = {
                'title': title,
                'limit': 5,
                'contentRating[]': ['safe', 'suggestive', 'erotica', 'pornographic']
            }
            resp = self.session.get('https://api.mangadex.org/manga', params=params, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get('data', [])
                for manga in results:
                    attr = manga.get('attributes', {})
                    
                    # Check Titles (en, ja, romaji)
                    alt_titles = [attr['title'].get('en')]
                    for alt in attr.get('altTitles', []):
                        alt_titles.extend(alt.values())
                    
                    # Fuzzy match title
                    for t in alt_titles:
                        if t and StringUtils.is_close_match(StringUtils.normalize(title), StringUtils.normalize(t)):
                            # Found a high confidence match!
                            print(f"    [Lazarus] MATCH FOUND: {t} ({manga['id']})")
                            return manga['id'] # Return UUID
                            
        except Exception as e:
            print(f"    [Lazarus] Error: {e}")
        return None

# --- Extension Registry ---

class ExtensionRegistry:
    def __init__(self):
        self.session = requests.Session()
        self.domain_map = {}
        self.name_map = {}
        self.core_map = {}
        self.sources = {}
        self.known_ids = set()

    def sync(self):
        print("[System] Syncing with Keiyoushi Registry...")
        for url in KEIYOUSHI_URLS:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200: continue
                data = resp.json()
                for ext in data:
                    for src in ext.get('sources', []):
                        self._register(src.get('id'), src.get('name'), src.get('baseUrl'))
            except Exception as e:
                print(f"[Warning] Sync error: {e}")
        print(f"[System] Registry loaded {len(self.known_ids)} unique extensions.")

    def _register(self, sid, name, url):
        if not sid: return
        try:
            real_id = StringUtils.to_signed_64(sid)
            self.known_ids.add(real_id)
            self.sources[real_id] = {'name': name, 'url': url}
            
            domain = StringUtils.clean_domain(url)
            if domain and domain not in self.domain_map:
                self.domain_map[domain] = real_id
                
            if name:
                norm = StringUtils.normalize(name)
                if norm not in self.name_map: self.name_map[norm] = real_id
                core = SemanticProcessor.extract_core_identity(name)
                if core:
                    if core not in self.core_map: self.core_map[core] = []
                    self.core_map[core].append(real_id)
        except: pass

# --- Resolution Engine ---

class ResolutionEngine:
    def __init__(self, registry):
        self.registry = registry
        self.lazarus = LazarusEngine()

    def resolve(self, k_name, k_url, k_title, k_artist):
        """
        Returns: (Source_ID, Source_Name, Method, Updated_Manga_URL)
        """
        
        # 1. Domain Fingerprint
        if k_url:
            domain = StringUtils.clean_domain(k_url)
            if domain and domain in self.registry.domain_map:
                sid = self.registry.domain_map[domain]
                return (sid, self.registry.sources[sid]['name'], "DOMAIN", None)

        # 2. Legacy Mapping
        norm_input = StringUtils.normalize(k_name)
        if norm_input in LEGACY_MAPPING:
            target = LEGACY_MAPPING[norm_input]
            target_norm = StringUtils.normalize(target)
            if target_norm in self.registry.name_map:
                sid = self.registry.name_map[target_norm]
                return (sid, self.registry.sources[sid]['name'], "LEGACY", None)
                
        # 3. Name Match
        if norm_input in self.registry.name_map:
            sid = self.registry.name_map[norm_input]
            return (sid, self.registry.sources[sid]['name'], "NAME", None)
            
        # 4. Fuzzy Match
        for known_norm, sid in self.registry.name_map.items():
            if StringUtils.is_close_match(norm_input, known_norm):
                 return (sid, self.registry.sources[sid]['name'], "FUZZY", None)

        # 5. Semantic Match
        input_core = SemanticProcessor.extract_core_identity(k_name)
        if input_core in self.registry.core_map:
            candidates = self.registry.core_map[input_core]
            if len(candidates) == 1:
                sid = candidates[0]
                return (sid, self.registry.sources[sid]['name'], "SEMANTIC", None)
            # Pick best length match
            best_sid, best_diff = None, 999
            for sid in candidates:
                diff = abs(len(k_name) - len(self.registry.sources[sid]['name']))
                if diff < best_diff:
                    best_diff, best_sid = diff, sid
            if best_sid:
                return (best_sid, self.registry.sources[best_sid]['name'], "SEMANTIC", None)

        # --- ADVANCED INTELLIGENCE TIERS ---
        
        # 5. Active Network Probe (Pathfinder)
        # Check if URL redirects to a known domain
        if k_url:
            new_url = NetworkProbe.check_redirect(k_url)
            if new_url:
                new_domain = StringUtils.clean_domain(new_url)
                if new_domain and new_domain in self.registry.domain_map:
                    sid = self.registry.domain_map[new_domain]
                    return (sid, self.registry.sources[sid]['name'], "PROBE_REDIRECT", None)

        # 6. Lazarus Protocol (Content Recovery)
        # If we are here, the source is unknown/dead. Search MangaDex.
        if k_title:
            md_uuid = self.lazarus.find_manga(k_title, k_artist)
            if md_uuid:
                # We found the manga on MangaDex!
                # We must use MangaDex Source ID and update the URL to /manga/{uuid}
                return (MANGADEX_SOURCE_ID, "MangaDex", "LAZARUS_RECOVERY", f"/manga/{md_uuid}")

        # 7. Deterministic Fallback
        fallback_id = StringUtils.java_hash(k_name)
        return (fallback_id, k_name, "HASH", None)

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

    reg = ExtensionRegistry()
    reg.sync()
    engine = ResolutionEngine(reg)

    print("[System] Parsing backup...")
    try:
        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not f_file: raise Exception("Favourites file not found.")
            with z.open(f_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"❌ Read Error: {e}")
        return

    print(f"[System] Migrating {len(data)} entries...")
    
    backup = tachiyomi_pb2.Backup()
    registered = set()
    
    stats = {
        'DOMAIN': 0, 'LEGACY': 0, 'NAME': 0, 'FUZZY': 0, 
        'SEMANTIC': 0, 'PROBE_REDIRECT': 0, 'LAZARUS_RECOVERY': 0, 'HASH': 0
    }

    for item in data:
        m = item.get('manga', {})
        original_url = m.get('url', '') or m.get('public_url', '')
        name = m.get('source', 'Unknown')
        title = m.get('title', '')
        artist = m.get('artist', '')
        
        # Resolve
        sid, sname, method, new_url = engine.resolve(name, original_url, title, artist)
        stats[method] += 1
        
        # Use new URL if provided (Lazarus), otherwise original
        final_url = new_url if new_url else original_url

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
        bm.url = final_url
        bm.title = title
        bm.artist = artist
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

    # Write
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print("-" * 50)
    print(f"MIGRATION COMPLETE (v6.9.6)")
    print(f"Total Processed: {len(data)}")
    print("-" * 20)
    print(f"  [TIER 1] Domain Match:     {stats['DOMAIN']}")
    print(f"  [TIER 2] Legacy Bridge:    {stats['LEGACY']}")
    print(f"  [TIER 3] Name Match:       {stats['NAME']} / {stats['FUZZY']}")
    print(f"  [TIER 4] Semantic AI:      {stats['SEMANTIC']}")
    print(f"  [TIER 5] Network Probe:    {stats['PROBE_REDIRECT']} (Redirects Found)")
    print(f"  [TIER 6] Lazarus Recovery: {stats['LAZARUS_RECOVERY']} (Recovered via MangaDex)")
    print(f"  [TIER 7] Hash Fallback:    {stats['HASH']}")
    print("-" * 50)
    print(f"Artifact: {out_path}")

if __name__ == "__main__":
    main()
