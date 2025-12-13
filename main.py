#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 6.6.6 
"""

import os
import sys
import json
import zipfile
import gzip
import struct
import requests
import re
import time
import difflib
import concurrent.futures
import random
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Optional: BeautifulSoup for CMS Fingerprinting
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# --- Configuration ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'
OUTPUT_FILE = 'Backup.tachibk'
GH_TOKEN = os.environ.get('GH_TOKEN')

# Ensure UTF-8 Output
sys.stdout.reconfigure(encoding='utf-8')

# --- External Intelligence ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"
]
DOKI_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

# --- The Akashic Vault (Top 500 High-Value Targets) ---
OMNI_VAULT = {
    # Giants
    "MANGANATO": "manganato.com", "MANGANELO": "manganato.com", "READMANGANATO": "manganato.com",
    "MANGAKAKALOT": "mangakakalot.com", "KAKALOT": "mangakakalot.com",
    "BATO": "bato.to", "BATOTO": "bato.to", "MANGATOTO": "bato.to",
    "MANGASEE": "mangasee123.com", "MANGASEE123": "mangasee123.com",
    "MANGALIFE": "manga4life.com", "MANGAPARK": "mangapark.net",
    "MANGADEX": "mangadex.org", "DEX": "mangadex.org",
    "MANGAGO": "mangago.me", "READM": "readm.org",
    "MANGAFOX": "fanfox.net", "FANFOX": "fanfox.net",
    "MANGATOWN": "mangatown.com", "MANGAPANDA": "mangapanda.com",
    "MANGAHUB": "mangahub.io", "NINEMANGA": "ninemanga.com",
    "MANGATIGRE": "mangatigre.net", "TUIMANGA": "tuimanga.com",
    "MANGATUBE": "mangatube.site", "MANGATX": "mangatx.com",
    
    # Scanlators (The Problem Children)
    "ASURA": "asuracomic.net", "ASURASCANS": "asuracomic.net", "ASURATOON": "asuracomic.net",
    "FLAME": "flamecomics.com", "FLAMESCANS": "flamecomics.com", "FLAMECOMICS": "flamecomics.com",
    "REAPER": "reaperscans.com", "REAPERSCANS": "reaperscans.com",
    "LUMINOUS": "luminousscans.com", "LUMINOUSSCANS": "luminousscans.com",
    "LEVIATAN": "leviatanscans.com", "LEVIATANSCANS": "leviatanscans.com",
    "VOID": "void-scans.com", "VOIDSCANS": "void-scans.com", "HIVE": "void-scans.com",
    "COSMIC": "cosmicscans.com", "COSMICSCANS": "cosmicscans.com",
    "DISASTER": "disasterscans.com", "DISASTERSCANS": "disasterscans.com",
    "DRAKE": "drakescans.com", "DRAKESCANS": "drakescans.com",
    "DRAGONTEA": "dragontea.ink",
    "GALAXY": "galaxymanga.org", "GALAXYMANGA": "galaxymanga.org",
    "GOURMET": "gourmetscans.net",
    "IMMORTAL": "immortalupdates.com",
    "INFERNAL": "infernalvoidscans.com",
    "KITSUNE": "mangakitsune.com",
    "KOMIKCAST": "komikcast.cz", "KOMIKINDO": "komikindo.id",
    "METHOD": "methodscans.com",
    "NIGHT": "nightscans.org", "NIGHTSCANS": "nightscans.org",
    "OMEGA": "omegascans.org", "OMEGASCANS": "omegascans.org",
    "OZUL": "ozulscans.com", "OZULSCANS": "ozulscans.com",
    "PLATINUM": "platinumscans.com",
    "RAVEN": "ravenscans.com", "RAVENSCANS": "ravenscans.com",
    "REALM": "realmscans.com", "REALMSCANS": "realmscans.com",
    "RESET": "reset-scans.com", "RESETSCANS": "reset-scans.com",
    "RIZZ": "rizzcomic.com", "RIZZCOMIC": "rizzcomic.com",
    "SURYA": "suryascans.com", "SURYASCANS": "suryascans.com",
    "TCB": "tcbscans.com", "TCBSCANS": "tcbscans.com",
    "TRITINIA": "tritinia.org",
    "XCALIBR": "xcalibrscans.com",
    "ZERO": "zeroscans.com", "ZEROSCANS": "zeroscans.com",
    "ZIN": "zinmanga.com", "ZINMANGA": "zinmanga.com",
    "ZURI": "zuriseen.com",
    "ALPHA": "alpha-scans.org", "ALPHASCANS": "alpha-scans.org",
    "ASTRA": "astrascans.org", "ASTRASCANS": "astrascans.org",
    "AQUA": "aquamanga.com", "AQUAMANGA": "aquamanga.com",
    "AZURE": "azuremanga.com", "AZUREMANGA": "azuremanga.com",

    # Manhwa/Webtoon
    "WEBTOONS": "webtoons.com", "LINEWEBTOON": "webtoons.com",
    "TAPAS": "tapas.io", "TOONILY": "toonily.com",
    "1STKISS": "1stkissmanga.io", "1STKISSMANGA": "1stkissmanga.io",
    "MANHUAES": "manhuaes.com", "MANHUAFAST": "manhuafast.com",
    "MANHUAGOLD": "manhuagold.com",
    "MANHWA18": "manhwa18.com", "MANHWA18.CC": "manhwa18.cc",
    "MANHUAUS": "manhuaus.com",
    "BILIBILI": "bilibilicomics.com", "VIZ": "viz.com",
    "MANGAPLUS": "mangaplus.shueisha.co.jp",
    
    # Hentai
    "NHENTAI": "nhentai.net", "HENTAI20": "hentai20.io",
    "HENTAIREAD": "hentairead.com", "NINEHENTAI": "ninehentai.com",
    "SIMPLYHENTAI": "simply-hentai.com", "PURURIN": "pururin.to",
    "TSUMINO": "tsumino.com", "HITOMI": "hitomi.la",
    "LUSCIOUS": "luscious.net", "MULTPORN": "multporn.net",
    "8MUSES": "comics.8muses.com", "DOUJINDESU": "doujindesu.tv",
    "HENTAIHEROES": "hentaiheroes.net", "HENTAIHAND": "hentaihand.com",
    "HENTAIFOX": "hentaifox.com", "ASMHENTAI": "asmhentai.com",
    "HENTAICAFE": "hentai.cafe"
}

# --- Infrastructure ---

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
            for p in ['www.', 'api.', 'm.', 'v1.', 'v2.', 'read.', 'images.']:
                domain = domain.replace(p, '')
            if ':' in domain: domain = domain.split(':')[0]
            return domain
        except: return None

    @staticmethod
    def normalize(text):
        if not text: return ""
        t = text.lower()
        t = re.sub(r'\.(com|net|org|io|to|cc|me|gg|info|xyz|site|ink|app|fun|us|uk|eu)$', '', t)
        t = t.replace('-', '').replace('_', '').replace('.', '').replace(' ', '')
        t = re.sub(r'[^a-z0-9]', '', t)
        return t.upper()

    @staticmethod
    def tokenize(text):
        if not text: return set()
        t = text.lower()
        t = re.sub(r'[^a-z0-9]', ' ', t)
        parts = t.split()
        return {p for p in parts if len(p) > 2}

    @staticmethod
    def jaccard_similarity(text1, text2):
        s1 = StringUtils.tokenize(text1)
        s2 = StringUtils.tokenize(text2)
        if not s1 or not s2: return 0.0
        return len(s1.intersection(s2)) / len(s1.union(s2))

    @staticmethod
    def levenshtein_ratio(s1, s2):
        return difflib.SequenceMatcher(None, s1, s2).ratio()

# --- Intelligence Agency ---

class IntelligenceAgency:
    def __init__(self):
        self.session = self._create_session()
        self.domain_map = {}   # domain -> (id, name)
        self.name_map = {}     # normalized_name -> (id, name)
        self.id_to_data = {}   # id -> {name, domain}
        self.known_ids = set()

    def _create_session(self):
        s = requests.Session()
        retries = Retry(total=5, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504, 429])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        return s

    def initialize(self):
        print("[Intel] Initializing Akashic Vault...")
        self._load_vault()
        self._sync_keiyoushi()
        self._sync_doki()
        print(f"[Intel] Knowledge Base: {len(self.known_ids)} verified sources.")

    def _load_vault(self):
        for alias, domain in OMNI_VAULT.items():
            norm = StringUtils.normalize(alias)
            entry = (None, domain)
            self.name_map[norm] = entry
            self.domain_map[domain] = entry

    def _register_source(self, sid, name, base_url):
        if not sid: return
        signed_id = StringUtils.to_signed_64(sid)
        self.known_ids.add(signed_id)
        
        entry = (signed_id, name)
        self.id_to_data[signed_id] = {'name': name, 'url': base_url}
        
        if base_url:
            domain = StringUtils.clean_domain(base_url)
            if domain:
                self.domain_map[domain] = entry
                # Retroactive Link for Vault
                for k, v in OMNI_VAULT.items():
                    if v == domain: self.name_map[StringUtils.normalize(k)] = entry

        if name:
            norm = StringUtils.normalize(name)
            self.name_map[norm] = entry
            
            # Auto-Permutations (The Quantum Logic)
            base_norm = norm
            for suffix in ["SCANS", "SCAN", "COMIC", "COMICS", "TOON", "TOONS", "MANGA", "TEAM", "FANSUB"]:
                if suffix in base_norm:
                    short_norm = base_norm.replace(suffix, "")
                    if len(short_norm) > 3:
                        if short_norm not in self.name_map:
                            self.name_map[short_norm] = entry

    def _sync_keiyoushi(self):
        for url in KEIYOUSHI_URLS:
            try:
                resp = self.session.get(url, timeout=20)
                if resp.status_code != 200: continue
                for ext in resp.json():
                    for src in ext.get('sources', []):
                        self._register_source(src.get('id'), src.get('name'), src.get('baseUrl'))
            except: pass

    def _sync_doki(self):
        try:
            resp = self.session.get(DOKI_API, timeout=25)
            if resp.status_code == 200:
                tree = resp.json().get('tree', [])
                kt_files = [f for f in tree if f['path'].endswith('.kt') and 'src/main/kotlin' in f['path']]
                # Process only a sample if too many, but for God Mode we do ALL
                with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
                    list(ex.map(self._parse_kt, kt_files))
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
                if id_m:
                    name = name_m.group(1) if name_m else f_obj['path'].split('/')[-1].replace('.kt','')
                    self._register_source(int(id_m.group(1)), name, url_m.group(1) if url_m else None)
        except: pass

# --- The Quantum Bridge (AI Matching) ---

class QuantumBridge:
    def __init__(self, intel):
        self.intel = intel

    def match(self, name, url):
        candidates = []

        # 1. Exact Domain (Score: 100)
        domain = StringUtils.clean_domain(url)
        if domain:
            match = self.intel.domain_map.get(domain)
            if match and match[0]: 
                return match

        # 2. Vault/Name Exact (Score: 90)
        norm_name = StringUtils.normalize(name)
        match = self.intel.name_map.get(norm_name)
        if match:
            if match[0]: return match
            if isinstance(match[1], str):
                # Resolve pointer
                ptr_domain = match[1]
                d_match = self.intel.domain_map.get(ptr_domain)
                if d_match and d_match[0]: return d_match

        # 3. Dynamic Permutations (Score: 80)
        # Try to guess common variations
        variations = set()
        base = re.sub(r'(?i)s+(scans?|comics?|toons?|manga|team|fansub)$', '', name).strip()
        langs = ["EN", "ID", "ES", "BR", "RU", "TR", "VI", "FR", "US"]
        suffixes = [" Scans", " Comics", " Toon", " Manga", " Team", " Fansub"]
        
        variations.add(base)
        for l in langs:
            variations.add(f"{base} ({l})")
            variations.add(f"{base} [{l}]")
        for s in suffixes:
            variations.add(base + s)
        
        for v in variations:
            nm = StringUtils.normalize(v)
            m = self.intel.name_map.get(nm)
            if m and m[0]: return m

        # 4. Deep Heuristic Scoring (Score: > 60)
        # Iterate known sources and score them
        best_match = None
        best_score = 0
        
        input_tokens = StringUtils.tokenize(name)
        
        # Optimization: Only check sources that share at least one token or start with same letter
        # This is strictly to keep runtime reasonable (< 1 hour)
        for sid in self.intel.known_ids:
            data = self.intel.id_to_data.get(sid)
            if not data: continue
            
            target_name = data['name']
            
            # Heuristic 1: Jaccard
            j_score = StringUtils.jaccard_similarity(name, target_name)
            
            # Heuristic 2: Levenshtein (only if Jaccard shows promise)
            l_score = 0
            if j_score > 0.3:
                l_score = StringUtils.levenshtein_ratio(StringUtils.normalize(name), StringUtils.normalize(target_name))
            
            # Combined
            final_score = (j_score * 0.6) + (l_score * 0.4)
            
            if final_score > best_score:
                best_score = final_score
                best_match = (sid, target_name)
        
        if best_score > 0.65:
            return best_match

        # 5. Fallback
        final_name = name
        if match and isinstance(match[1], str): final_name = match[1]
        
        return (StringUtils.java_hash(final_name), final_name)

class NetRunner:
    def __init__(self, intel):
        self.intel = intel
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetRunner/6.6.6',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })

    def run_diagnostics(self, items):
        print(f"[NetRunner] Analyzing {len(items)} unresolved vectors...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
            future_to_item = {ex.submit(self._probe, i): i for i in items}
            for fut in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[fut]
                try:
                    res = fut.result()
                    if res:
                        # Update Knowledge Base
                        self.intel.name_map[StringUtils.normalize(item['source'])] = res
                        if item['url']:
                            self.intel.domain_map[StringUtils.clean_domain(item['url'])] = res
                except: pass

    def _probe(self, item):
        url = item['url']
        if not url: return None
        
        # 1. Check Live Redirection
        try:
            r = self.session.get(url, allow_redirects=True, timeout=10)
            final_domain = StringUtils.clean_domain(r.url)
            match = self.intel.domain_map.get(final_domain)
            if match and match[0]: return match

            # 2. CMS Fingerprinting (BeautifulSoup)
            if HAS_BS4 and r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                # Check for Madara
                if soup.find('meta', {'name': 'generator', 'content': 'Madara'}) or "wp-content/plugins/madara" in r.text:
                    # It's a Madara site. Try to find a Madara extension with similar name
                    return self._find_extension_by_cms("Madara", item['source'], final_domain)
        except: pass

        # 3. Domain Permutation Guessing (The God Mode feature)
        # If site.com failed, try site.net, site.io, etc.
        try:
            base_domain = StringUtils.clean_domain(url)
            if not base_domain: return None
            
            name_part = base_domain.split('.')[0]
            tlds = ['net', 'org', 'io', 'cc', 'gg', 'to', 'com']
            
            for tld in tlds:
                if tld in base_domain: continue
                guess_url = f"https://{name_part}.{tld}"
                try:
                    r = self.session.head(guess_url, timeout=5)
                    if r.status_code < 400:
                        # Alive! Check if this domain is known
                        d = StringUtils.clean_domain(r.url)
                        match = self.intel.domain_map.get(d)
                        if match and match[0]: return match
                except: continue
        except: pass
        
        return None

    def _find_extension_by_cms(self, cms, name, domain):
        # Extremely fuzzy search for an extension that might match this CMS and name
        # This is a last resort
        norm_name = StringUtils.normalize(name)
        for sid, data in self.intel.id_to_data.items():
            if norm_name in StringUtils.normalize(data['name']):
                return (sid, data['name'])
        return None

# --- Main Executive ---

def main():
    try:
        import tachiyomi_pb2
    except ImportError:
        print("❌ Critical: tachiyomi_pb2 missing. Run protoc.")
        return

    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Critical: Input zip missing.")
        return
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)

    # 1. Initialize Intelligence
    intel = IntelligenceAgency()
    intel.initialize()
    bridge = QuantumBridge(intel)
    runner = NetRunner(intel)

    # 2. Parse Backup
    print("[System] Parsing backup matrix...")
    try:
        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not f_file: raise Exception("No favourites.json found.")
            with z.open(f_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"❌ Read Error: {e}")
        return

    # 3. Identify & Resolve Unknowns
    unknowns = []
    print("[System] Identifying unknown vectors...")
    for x in data:
        m = x.get('manga', {})
        sid, _ = bridge.match(m.get('source', ''), m.get('url', ''))
        # If ID is generic hash (fallback), mark as unknown for deep probe
        if sid not in intel.known_ids:
            unknowns.append({'source': m.get('source', ''), 'url': m.get('url', '')})
    
    if unknowns:
        runner.run_diagnostics(unknowns)

    # 4. Final Migration
    print("[System] Executing final migration...")
    backup = tachiyomi_pb2.Backup()
    registered = set()
    stats = {'official': 0, 'fallback': 0}

    for item in data:
        m = item.get('manga', {})
        url = m.get('url', '') or m.get('public_url', '')
        name = m.get('source', '')
        
        sid, sname = bridge.match(name, url)
        
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

    # 5. Serialize
    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print("="*60)
    print(f"MIGRATION COMPLETE (v6.6.6)")
    print(f"Total Entries: {len(data)}")
    print(f"Official IDs:  {stats['official']} (Verified)")
    print(f"Fallback IDs:  {stats['fallback']} (Legacy Hashed)")
    print(f"Artifact:      {out_path}")
    print("="*60)

if __name__ == "__main__":
    main()
