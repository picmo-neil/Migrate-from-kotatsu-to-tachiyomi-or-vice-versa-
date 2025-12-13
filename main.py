#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 6.9.0
Status: MAXIMUM POWER
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

# --- External Intelligence ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.html"
]
DOKI_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

# --- The Omniscience Database ---
# A massive, comprehensive mapping of Alias -> Canonical Domain
# This list is intentionally aggressive to catch everything.

OMNI_VAULT = {
    # === AGGREGATORS & GIANTS ===
    "MANGANATO": "manganato.com", "MANGANELO": "manganato.com", "READMANGANATO": "manganato.com", "CHAPMANGANATO": "manganato.com",
    "MANGAKAKALOT": "mangakakalot.com", "KAKALOT": "mangakakalot.com",
    "BATO": "bato.to", "BATOTO": "bato.to", "MANGATOTO": "bato.to", "ZHBATO": "bato.to", "BATO.TO": "bato.to",
    "MANGASEE": "mangasee123.com", "MANGASEE123": "mangasee123.com",
    "MANGALIFE": "manga4life.com", "MANGA4LIFE": "manga4life.com",
    "MANGAPARK": "mangapark.net", "MANGAPARKV3": "mangapark.net", "MANGAPARKV5": "mangapark.net",
    "MANGADEX": "mangadex.org", "DEX": "mangadex.org",
    "MANGAGO": "mangago.me",
    "READM": "readm.org",
    "MANGAFOX": "fanfox.net", "FANFOX": "fanfox.net",
    "MANGATOWN": "mangatown.com",
    "MANGAPANDA": "mangapanda.com",
    "MANGAHUB": "mangahub.io",
    "NINEMANGA": "ninemanga.com", "NINEMANGA(EN)": "ninemanga.com",
    "MANGATIGRE": "mangatigre.net",
    "TUIMANGA": "tuimanga.com",
    "MANGATUBE": "mangatube.site",
    "MANGATX": "mangatx.com",
    
    # === SCANLATORS (A-Z) ===
    "ALPHA": "alpha-scans.org", "ALPHASCANS": "alpha-scans.org",
    "ASURA": "asuracomic.net", "ASURASCANS": "asuracomic.net", "ASURATOON": "asuracomic.net", "ASURA.GG": "asuracomic.net",
    "ASTRA": "astrascans.org", "ASTRASCANS": "astrascans.org",
    "AQUA": "aquamanga.com", "AQUAMANGA": "aquamanga.com",
    "AZURE": "azuremanga.com", "AZUREMANGA": "azuremanga.com",
    "COSMIC": "cosmicscans.com", "COSMICSCANS": "cosmicscans.com",
    "DISASTER": "disasterscans.com", "DISASTERSCANS": "disasterscans.com",
    "DRAKE": "drakescans.com", "DRAKESCANS": "drakescans.com",
    "DRAGONTEA": "dragontea.ink",
    "FLAME": "flamecomics.com", "FLAMESCANS": "flamecomics.com", "FLAMECOMICS": "flamecomics.com",
    "GALAXY": "galaxymanga.org", "GALAXYMANGA": "galaxymanga.org",
    "GOURMET": "gourmetscans.net",
    "HIVE": "void-scans.com", "HIVESCANS": "void-scans.com", "VOID": "void-scans.com", "VOIDSCANS": "void-scans.com",
    "IMMORTAL": "immortalupdates.com",
    "INFERNAL": "infernalvoidscans.com",
    "KITSUNE": "mangakitsune.com",
    "KKJ": "kkjscans.co",
    "KOMIKCAST": "komikcast.cz",
    "KOMIKINDO": "komikindo.id",
    "LEVIATAN": "leviatanscans.com", "LEVIATANSCANS": "leviatanscans.com",
    "LUMINOUS": "luminousscans.com", "LUMINOUSSCANS": "luminousscans.com",
    "LYRA": "lyrascans.com",
    "METHOD": "methodscans.com",
    "MMSCANS": "mm-scans.org",
    "NEOX": "neoxscans.net",
    "NIGHT": "nightscans.org", "NIGHTSCANS": "nightscans.org",
    "OMEGA": "omegascans.org", "OMEGASCANS": "omegascans.org",
    "OZUL": "ozulscans.com", "OZULSCANS": "ozulscans.com",
    "PLATINUM": "platinumscans.com",
    "RAVEN": "ravenscans.com", "RAVENSCANS": "ravenscans.com",
    "REALM": "realmscans.com", "REALMSCANS": "realmscans.com",
    "REAPER": "reaperscans.com", "REAPERSCANS": "reaperscans.com",
    "RESET": "reset-scans.com", "RESETSCANS": "reset-scans.com",
    "RIZZ": "rizzcomic.com", "RIZZCOMIC": "rizzcomic.com",
    "SURYA": "suryascans.com", "SURYASCANS": "suryascans.com",
    "TCB": "tcbscans.com", "TCBSCANS": "tcbscans.com",
    "TRITINIA": "tritinia.org",
    "XCALIBR": "xcalibrscans.com",
    "ZERO": "zeroscans.com", "ZEROSCANS": "zeroscans.com",
    "ZIN": "zinmanga.com", "ZINMANGA": "zinmanga.com",
    "ZURI": "zuriseen.com",

    # === MANHWA/WEBTOON ===
    "WEBTOONS": "webtoons.com", "LINEWEBTOON": "webtoons.com",
    "TAPAS": "tapas.io",
    "TOONILY": "toonily.com",
    "1STKISS": "1stkissmanga.io", "1STKISSMANGA": "1stkissmanga.io",
    "MANHUAES": "manhuaes.com",
    "MANHUAFAST": "manhuafast.com",
    "MANHUAGOLD": "manhuagold.com",
    "MANHWA18": "manhwa18.com", "MANHWA18.CC": "manhwa18.cc",
    "MANHUAUS": "manhuaus.com",
    "BILIBILI": "bilibilicomics.com",
    "VIZ": "viz.com",
    "MANGAPLUS": "mangaplus.shueisha.co.jp",
    
    # === REGIONAL (LATAM/BR/ES) ===
    "LECTORM": "lectormanga.com",
    "LEERCAPITULO": "leercapitulo.com",
    "MANGABR": "mangabr.net",
    "SILENCESCANS": "silencescan.com.br",
    "HUNTER": "huntersscan.com",
    "MUNDOMANHWA": "mundomanhwa.com.br",
    "PRISMA": "prismascans.net",
    "REMANGAS": "remangas.top",
    "OLYMPUS": "olympus-scans.com",
    "YONA": "yonabar.com",
    
    # === HENTAI ===
    "NHENTAI": "nhentai.net",
    "HENTAI20": "hentai20.io",
    "HENTAIREAD": "hentairead.com",
    "NINEHENTAI": "ninehentai.com",
    "SIMPLYHENTAI": "simply-hentai.com",
    "PURURIN": "pururin.to",
    "TSUMINO": "tsumino.com",
    "HITOMI": "hitomi.la",
    "LUSCIOUS": "luscious.net",
    "MULTPORN": "multporn.net",
    "8MUSES": "comics.8muses.com",
    "DOUJINDESU": "doujindesu.tv",
    "HENTAIHEROES": "hentaiheroes.net",
    "HENTAIHAND": "hentaihand.com",
    "HENTAIFOX": "hentaifox.com",
    "ASMHENTAI": "asmhentai.com",
    "HENTAICAFE": "hentai.cafe"
}

# --- The Graveyard (Dead Sites to Modern Mirrors) ---
GRAVEYARD_MAP = {
    "kissmanga.com": "kissmanga.org",
    "mangastream.com": "mangastream.mobi",
    "mangarock.com": "mangarockteam.com",
    "reaperscans.com.br": "reaperscans.com",
    "asurascans.com": "asuracomic.net",
    "asuratoon.com": "asuracomic.net",
    "flamescans.org": "flamecomics.com",
    "void-scans.com": "void-scans.com",
    "voidscans.net": "void-scans.com",
    "manganelo.com": "manganato.com",
    "mangakakalot.tv": "mangakakalot.com",
    "mangadex.com": "mangadex.org",
    "mangasee.com": "mangasee123.com",
    "manga4life.com": "manga4life.com",
    "1stkissmanga.love": "1stkissmanga.io",
    "manhuaes.io": "manhuaes.com"
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
        t = re.sub(r'\.(com|net|org|io|to|cc|me|gg|info|xyz|site|ink|app|fun)$', '', t)
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

# --- Intelligence Agency ---

class IntelligenceAgency:
    def __init__(self):
        self.session = self._create_session()
        self.domain_map = {}   # domain -> (id, name)
        self.name_map = {}     # normalized_name -> (id, name)
        self.known_ids = set()

    def _create_session(self):
        s = requests.Session()
        retries = Retry(total=3, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Architect/5.0'
        })
        return s

    def initialize(self):
        print("[Intel] Initializing Omniscience Database...")
        self._load_static_data()
        self._sync_keiyoushi()
        self._sync_doki()
        print(f"[Intel] Knowledge Base: {len(self.known_ids)} verified sources.")

    def _load_static_data(self):
        # Load Vault
        for alias, domain in OMNI_VAULT.items():
            norm = StringUtils.normalize(alias)
            entry = (None, domain)
            self.name_map[norm] = entry
            self.domain_map[domain] = entry
        
        # Load Graveyard
        for dead, alive in GRAVEYARD_MAP.items():
            self.domain_map[dead] = (None, alive)

    def _register_source(self, sid, name, base_url):
        if not sid: return
        signed_id = StringUtils.to_signed_64(sid)
        self.known_ids.add(signed_id)
        
        entry = (signed_id, name)
        
        if base_url:
            domain = StringUtils.clean_domain(base_url)
            if domain:
                self.domain_map[domain] = entry
                
                # Retroactive Link
                for dead, alive in GRAVEYARD_MAP.items():
                    if alive == domain: self.domain_map[dead] = entry
                for k, v in OMNI_VAULT.items():
                    if v == domain: self.name_map[StringUtils.normalize(k)] = entry

        if name:
            norm = StringUtils.normalize(name)
            self.name_map[norm] = entry
            # Register Permutations
            base_norm = norm
            for suffix in ["SCANS", "SCAN", "COMIC", "COMICS", "TOON", "TOONS", "MANGA"]:
                if suffix in base_norm:
                    short_norm = base_norm.replace(suffix, "")
                    if short_norm and len(short_norm) > 3:
                        if short_norm not in self.name_map:
                            self.name_map[short_norm] = entry

    def _sync_keiyoushi(self):
        for url in KEIYOUSHI_URLS:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200: continue
                if url.endswith('.json'):
                    for ext in resp.json():
                        for src in ext.get('sources', []):
                            self._register_source(src.get('id'), src.get('name'), src.get('baseUrl'))
                elif url.endswith('.html'):
                    rows = re.findall(r'<tr[^>]*>.*?</tr>', resp.text, flags=re.DOTALL)
                    for row in rows:
                        name_m = re.search(r'class="name"[^>]*>(.*?)<', row)
                        id_m = re.search(r'data-id="(-?d+)"', row)
                        if name_m and id_m:
                            self._register_source(int(id_m.group(1)), name_m.group(1).strip(), None)
            except: pass

    def _sync_doki(self):
        try:
            resp = self.session.get(DOKI_API, timeout=20)
            if resp.status_code == 200:
                tree = resp.json().get('tree', [])
                kt_files = [f for f in tree if f['path'].endswith('.kt') and 'src/main/kotlin' in f['path']]
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
                    list(ex.map(self._parse_kt, kt_files))
        except: pass

    def _parse_kt(self, f_obj):
        url = DOKI_RAW_BASE + f_obj['path']
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                txt = resp.text
                id_m = re.search(r'val\s+id\s*=\s*(\d+)L?', txt)
                name_m = re.search(r'val\s+name\s*=\s*"([^"]+)"', txt)
                url_m = re.search(r'val\s+baseUrl\s*=\s*"([^"]+)"', txt)
                if id_m:
                    name = name_m.group(1) if name_m else f_obj['path'].split('/')[-1].replace('.kt','')
                    self._register_source(int(id_m.group(1)), name, url_m.group(1) if url_m else None)
        except: pass

# --- The Neural Matcher ---

class NeuralMatcher:
    def __init__(self, intel):
        self.intel = intel

    def match(self, name, url):
        # 1. Exact Domain Match (100%)
        domain = StringUtils.clean_domain(url)
        if domain:
            match = self.intel.domain_map.get(domain)
            if match and match[0]: return match

        # 2. Vault/Name Match (95%)
        norm_name = StringUtils.normalize(name)
        match = self.intel.name_map.get(norm_name)
        if match:
            if match[0]: return match
            if isinstance(match[1], str) and '.' in match[1]:
                d_match = self.intel.domain_map.get(match[1])
                if d_match and d_match[0]: return d_match

        # 3. Neural Bridge (Permutations) (80%)
        # Generates variants like "MangaDex (EN)", "MangaDex [EN]", "MangaDex"
        variations = []
        base = name
        # Strip common suffixes
        base = re.sub(r'(?i)s+(scans?|comics?|toons?|manga)$', '', base)
        
        langs = ["EN", "ID", "ES", "BR", "RU", "TR", "VI", "FR"]
        variations.append(base) # "Asura"
        for l in langs:
            variations.append(f"{base} ({l})")
            variations.append(f"{base} [{l}]")
            variations.append(f"{name} ({l})")
        
        # Add suffixes back
        for s in [" Scans", " Comics", " Toon", " Manga"]:
            variations.append(base + s)

        for v in variations:
            n = StringUtils.normalize(v)
            m = self.intel.name_map.get(n)
            if m and m[0]: return m

        # 4. Fuzzy Token Match (60% - Aggressive)
        best_match = None
        best_score = 0
        
        # We search through known IDs to find a name that is close
        # This is expensive but requested "Maximum Accuracy"
        # To optimize, we check exact Jaccard overlap
        
        input_tokens = StringUtils.tokenize(name)
        if len(input_tokens) > 0:
            # Check against a sample of keys (full scan is too slow? No, 2000 is fine)
            for key, entry in self.intel.name_map.items():
                if not entry[0]: continue
                
                # Jaccard
                score = StringUtils.jaccard_similarity(name, entry[1])
                
                # Bonus for substring
                if StringUtils.normalize(entry[1]) in norm_name or norm_name in StringUtils.normalize(entry[1]):
                    score += 0.3
                
                if score > best_score:
                    best_score = score
                    best_match = entry

        if best_score > 0.55: # Low threshold for aggressive matching
            return best_match

        # 5. Fallback
        final_name = name
        if match and isinstance(match[1], str): final_name = match[1]
        
        return (StringUtils.java_hash(final_name), final_name)

class LazarusProber:
    def __init__(self, intel):
        self.intel = intel
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

    def resurrect(self, items):
        print(f"[Lazarus] Attempting to resurrect {len(items)} dead links...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
            future_to_item = {ex.submit(self._probe, i['url']): i for i in items}
            for fut in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[fut]
                try:
                    res = fut.result()
                    if res:
                        self.intel.domain_map[StringUtils.clean_domain(item['url'])] = res
                        self.intel.name_map[StringUtils.normalize(item['source'])] = res
                except: pass

    def _probe(self, url):
        if not url: return None
        try:
            # Just HEAD first
            r = self.session.head(url, allow_redirects=True, timeout=5)
            final_url = r.url
            d = StringUtils.clean_domain(final_url)
            match = self.intel.domain_map.get(d)
            if match and match[0]: return match
            
            # If HEAD failed to identify, try GET (slower)
            if r.status_code >= 400:
                r = self.session.get(url, allow_redirects=True, timeout=8, stream=True)
                r.close()
                d = StringUtils.clean_domain(r.url)
                match = self.intel.domain_map.get(d)
                if match and match[0]: return match
                
        except: return None
        return None

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

    # 1. Init
    intel = IntelligenceAgency()
    intel.initialize()
    engine = NeuralMatcher(intel)
    prober = LazarusProber(intel)

    # 2. Read
    print("[System] Reading backup...")
    try:
        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
            if not f_file: raise Exception("No favourites.")
            with z.open(f_file) as f:
                data = json.load(f)
    except Exception as e:
        print(f"❌ Read Error: {e}")
        return

    # 3. Probe Unknowns (Lazarus Protocol)
    unknowns = []
    for x in data:
        m = x.get('manga', {})
        sid, _ = engine.match(m.get('source', ''), m.get('url', ''))
        if sid not in intel.known_ids:
            unknowns.append({'source': m.get('source', ''), 'url': m.get('url', '')})
    
    if unknowns: prober.resurrect(unknowns)

    # 4. Migrate
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
‎        
‎        st = (m.get('state') or '').upper()
‎        if st == 'ONGOING': bm.status = 1
‎        elif st in ['FINISHED', 'COMPLETED']: bm.status = 2
‎        else: bm.status = 0
‎        
‎        for t in m.get('tags', []):
‎            if t: bm.genre.append(str(t))
‎
‎    # 5. Export
‎    out_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
‎    with gzip.open(out_path, 'wb') as f:
‎        f.write(backup.SerializeToString())
‎
‎    print("="*50)
‎    print(f"MIGRATION COMPLETE (v6.9.0)")
‎    print(f"Total:      {len(data)}")
‎    print(f"Official:   {stats['official']} (Architect Match)")
‎    print(f"Fallback:   {stats['fallback']}")
‎    print(f"Output:     {out_path}")
‎    print("="*50)
‎
‎if __name__ == "__main__":
‎    main()
‎
