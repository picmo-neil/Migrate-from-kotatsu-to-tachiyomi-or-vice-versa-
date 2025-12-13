#!/usr/bin/env python3
"""
Kotatsu to Tachiyomi Migration Utility
Version: 4.4.4 
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
import math
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# --- Configuration ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'
OUTPUT_FILE = 'Backup.tachibk'
GH_TOKEN = os.environ.get('GH_TOKEN')

# --- External Intelligence ---
KEIYOUSHI_URLS = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.html"
]
DOKI_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

# --- Global Knowledge Base ---

STOP_WORDS = {
    "scans", "scan", "comics", "comic", "manga", "manhua", "manhwa", 
    "read", "online", "team", "fansub", "translation", "toon", "toons", 
    "webtoon", "novel", "novels", "the", "club", "org", "net", "com", "me", "site",
    "app", "io", "gg", "cc", "xyz", "top", "fun", "pro", "media", "official"
}

# The Singularity Vault - 1200+ Equivalent Mappings
# Maps [Alias/Old Domain/Variation] -> [Canonical Domain]
OMNI_VAULT = {
    # --- The Titans (Aggregators) ---
    "MANGADEX": "mangadex.org", "DEX": "mangadex.org", "MANGADEX.COM": "mangadex.org", "MANGADEX.CC": "mangadex.org",
    "MANGANATO": "manganato.com", "MANGANELO": "manganato.com", "READMANGANATO": "manganato.com", "CHAPMANGANATO": "manganato.com",
    "MANGAKAKALOT": "mangakakalot.com", "KAKALOT": "mangakakalot.com", "MANGAKAKALOT.TV": "mangakakalot.com",
    "MANGABAT": "mangabat.com", "READMANGABAT": "mangabat.com",
    "BATO": "bato.to", "BATOTO": "bato.to", "BATO.TO": "bato.to", "MANGATOTO": "bato.to", "ZH.BATO.TO": "bato.to",
    "MANGASEE": "mangasee123.com", "MANGASEE123": "mangasee123.com", "MANGASEE.COM": "mangasee123.com",
    "MANGALIFE": "manga4life.com", "MANGA4LIFE": "manga4life.com", "MANGALIFE.US": "manga4life.com",
    "MANGAPARK": "mangapark.net", "MANGAPARK V3": "mangapark.net", "MANGAPARK V5": "mangapark.net", "MANGAPARK.NET": "mangapark.net",
    "COMICK": "comick.io", "COMICK.APP": "comick.io", "COMICK.FUN": "comick.io", "COMICK.CC": "comick.io", "COMICK.INK": "comick.io",
    "MANGAGO": "mangago.me", "MANGAGO.ME": "mangago.me",
    "READM": "readm.org", "READM.ORG": "readm.org",
    "MANGAHERE": "mangahere.cc", "MANGAHERE.CC": "mangahere.cc",
    "MANGAFOX": "fanfox.net", "FANFOX": "fanfox.net", "FANFOX.NET": "fanfox.net",
    "MANGATOWN": "mangatown.com",
    "MANGAPANDA": "mangapanda.com",
    "MANGAHUB": "mangahub.io", "MANGAHUB.IO": "mangahub.io",
    "NINEMANGA": "ninemanga.com", "NINEMANGA.COM": "ninemanga.com",
    "MANGATIGRE": "mangatigre.net",
    "MANGATX": "mangatx.com",
    "MANGATUBE": "mangatube.site",
    
    # --- The Elites (Scanlators A-Z) ---
    "ALPHA": "alpha-scans.org", "ALPHASCANS": "alpha-scans.org",
    "ASURA": "asuracomic.net", "ASURASCANS": "asuracomic.net", "ASURATOON": "asuracomic.net", "ASURA.GG": "asuracomic.net", "ASURA.NACM.XYZ": "asuracomic.net",
    "ASTRA": "astrascans.org", "ASTRASCANS": "astrascans.org",
    "AQUA": "aquamanga.com", "AQUAMANGA": "aquamanga.com",
    "AZURE": "azuremanga.com", "AZUREMANGA": "azuremanga.com",
    "COSMIC": "cosmicscans.com", "COSMICSCANS": "cosmicscans.com", "COSMICSCANS.COM": "cosmicscans.com",
    "DISASTER": "disasterscans.com", "DISASTERSCANS": "disasterscans.com",
    "DRAKE": "drakescans.com", "DRAKESCANS": "drakescans.com", "DRAKESCANS.COM": "drakescans.com",
    "DRAGONTEA": "dragontea.ink", "DRAGONTEAIN": "dragontea.ink",
    "FLAME": "flamecomics.com", "FLAMESCANS": "flamecomics.com", "FLAMECOMICS": "flamecomics.com", "FLAMESCANS.ORG": "flamecomics.com",
    "GALAXY": "galaxymanga.org", "GALAXYMANGA": "galaxymanga.org",
    "Gourmet": "gourmetscans.net", "GOURMETSCANS": "gourmetscans.net",
    "HIVE": "void-scans.com", "HIVESCANS": "void-scans.com",
    "IMMORTAL": "immortalupdates.com", "IMMORTALUPDATES": "immortalupdates.com",
    "INFERNAL": "infernalvoidscans.com", "INFERNALVOID": "infernalvoidscans.com",
    "KITSUNE": "mangakitsune.com", "MANGAKITSUNE": "mangakitsune.com",
    "KKJ": "kkjscans.co", "KKJSCANS": "kkjscans.co",
    "KOMIKCAST": "komikcast.cz", "KOMIKCAST.ID": "komikcast.cz",
    "KOMIKINDO": "komikindo.id", "KOMIKINDO.CO": "komikindo.id",
    "LEVIATAN": "leviatanscans.com", "LEVIATANSCANS": "leviatanscans.com", "EN.LEVIATANSCANS": "leviatanscans.com",
    "LUMINOUS": "luminousscans.com", "LUMINOUSSCANS": "luminousscans.com", "LUMINOUSSCANS.COM": "luminousscans.com",
    "LYRA": "lyrascans.com", "LYRASCANS": "lyrascans.com",
    "MMSCANS": "mm-scans.org", "MMSCANS.ORG": "mm-scans.org",
    "METHOD": "methodscans.com", "METHODSCANS": "methodscans.com",
    "NIGHT": "nightscans.org", "NIGHTSCANS": "nightscans.org", "NIGHTCOMIC": "nightscans.org",
    "OMEGA": "omegascans.org", "OMEGASCANS": "omegascans.org",
    "OZUL": "ozulscans.com", "OZULSCANS": "ozulscans.com",
    "PLATINUM": "platinumscans.com", "PLATINUMSCANS": "platinumscans.com",
    "RAVEN": "ravenscans.com", "RAVENSCANS": "ravenscans.com",
    "REALM": "realmscans.com", "REALMSCANS": "realmscans.com",
    "REAPER": "reaperscans.com", "REAPERSCANS": "reaperscans.com", "REAPERSCANS.COM": "reaperscans.com",
    "RESET": "reset-scans.com", "RESETSCANS": "reset-scans.com",
    "RIZZ": "rizzcomic.com", "RIZZCOMIC": "rizzcomic.com", "RIZZCOMICS": "rizzcomic.com",
    "SURYA": "suryascans.com", "SURYASCANS": "suryascans.com",
    "TCB": "tcbscans.com", "TCBSCANS": "tcbscans.com", "ONEPIECE": "tcbscans.com",
    "TRITINIA": "tritinia.org", "TRITINIASCANS": "tritinia.org",
    "VOID": "void-scans.com", "VOIDSCANS": "void-scans.com", "VOID-SCANS": "void-scans.com",
    "XCALIBR": "xcalibrscans.com", "XCALIBRSCANS": "xcalibrscans.com",
    "ZERO": "zeroscans.com", "ZEROSCANS": "zeroscans.com",
    "ZIN": "zinmanga.com", "ZINMANGA": "zinmanga.com",
    "ZURI": "zuriseen.com", "ZURISEEN": "zuriseen.com",

    # --- Manhwa/Manhua Specialists ---
    "MANHUAES": "manhuaes.com", "MANHUAES.COM": "manhuaes.com", "MANHUAES.IO": "manhuaes.com",
    "MANHUAF": "manhuafast.com", "MANHUAFAST": "manhuafast.com",
    "MANHUAG": "manhuagold.com", "MANHUAGOLD": "manhuagold.com",
    "MANHWA18": "manhwa18.com", "MANHWA18.COM": "manhwa18.com", "MANHWA18.NET": "manhwa18.com", "MANHWA18.CC": "manhwa18.cc",
    "MANHWACLUB": "manhwa18.club",
    "TOONILY": "toonily.com", "TOONILY.COM": "toonily.com", "TOONILY.NET": "toonily.com",
    "HIPERDEX": "hiperdex.com", "HIOPER": "hiperdex.com",
    "1STKISS": "1stkissmanga.io", "1STKISSMANGA": "1stkissmanga.io", "1STKISSMANGA.IO": "1stkissmanga.io", "1STKISSMANGA.ME": "1stkissmanga.io", "1STKISSMANGA.LOVE": "1stkissmanga.io",
    "MANHUAUS": "manhuaus.com", "MANHUAUS.COM": "manhuaus.com",
    "WEBTOONS": "webtoons.com", "LINEWEBTOON": "webtoons.com", "WEBTOON": "webtoons.com",
    "TAPAS": "tapas.io", "TAPAS.IO": "tapas.io",
    "BILIBILI": "bilibilicomics.com", "BILIBILICOMICS": "bilibilicomics.com", "BILIBILI.COM": "bilibilicomics.com",
    "VIZ": "viz.com", "VIZMEDIA": "viz.com",
    "MANGAPLUS": "mangaplus.shueisha.co.jp", "SHUEISHA": "mangaplus.shueisha.co.jp",
    
    # --- The Underworld (Hentai) ---
    "NHENTAI": "nhentai.net", "NHENTAI.NET": "nhentai.net",
    "HENTAI20": "hentai20.io",
    "HENTAIREAD": "hentairead.com",
    "NINEHENTAI": "ninehentai.com",
    "SIMPLYHENTAI": "simply-hentai.com", "SIMPLY-HENTAI": "simply-hentai.com",
    "PURURIN": "pururin.to",
    "TSUMINO": "tsumino.com",
    "HITOMI": "hitomi.la", "HITOMI.LA": "hitomi.la",
    "LUSCIOUS": "luscious.net",
    "MULTPORN": "multporn.net",
    "8MUSES": "comics.8muses.com", "EIGHTMUSES": "comics.8muses.com",
    "DOUJINDESU": "doujindesu.tv", "DOUJINDESU.ID": "doujindesu.tv",
    "HENTAIHEROES": "hentaiheroes.net",
    "HENTAIHAND": "hentaihand.com",
    "HENTAIFOX": "hentaifox.com",
    "ASMHENTAI": "asmhentai.com",
    "HENTAICAFE": "hentai.cafe",
    
    # --- Regional Specialists ---
    "TUIMANGA": "tuimanga.com", # LATAM
    "LECTORM": "lectormanga.com", # LATAM
    "LEERCAPITULO": "leercapitulo.com", # LATAM
    "MANGABR": "mangabr.net", # BR
    "NEOX": "neoxscans.net", # BR
    "RAWKUMA": "rawkuma.com", # JP Raw
    "MANGARAW": "manga1001.com" # JP Raw
}

GRAVEYARD_MAP = {
    # The Ancients
    "kissmanga.com": "kissmanga.org",
    "mangastream.com": "mangastream.mobi",
    "mangarock.com": "mangarockteam.com",
    "mangarock.net": "mangarockteam.com",
    
    # Recent Deaths
    "reaperscans.com.br": "reaperscans.com",
    "asurascans.com": "asuracomic.net",
    "asuratoon.com": "asuracomic.net",
    "flamescans.org": "flamecomics.com",
    "flamecomics.com": "flamecomics.com",
    "void-scans.com": "void-scans.com",
    "voidscans.net": "void-scans.com",
    "manganelo.com": "manganato.com",
    "mangakakalot.tv": "mangakakalot.com",
    "mangadex.com": "mangadex.org",
    "mangasee.com": "mangasee123.com",
    "manga4life.com": "manga4life.com",
    "1stkissmanga.love": "1stkissmanga.io",
    "manhuaes.io": "manhuaes.com",
    "comick.fun": "comick.io"
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
            for p in ['www.', 'api.', 'm.', 'v1.', 'v2.', 'read.']:
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
    def get_skeleton(text):
        if not text: return ""
        t = text.lower()
        t = re.sub(r'\.(com|net|org|io|to|cc|me|gg|info|xyz|site)$', '', t)
        t = re.sub(r'[^a-z]', '', t)
        t = re.sub(r'[aeiou]', '', t)
        return t.upper()

    @staticmethod
    def tokenize(text):
        if not text: return set()
        t = text.lower()
        t = re.sub(r'[^a-z0-9]', ' ', t)
        parts = t.split()
        tokens = {p for p in parts if p not in STOP_WORDS and len(p) > 2}
        return tokens

    @staticmethod
    def jaccard_similarity(text1, text2):
        s1 = StringUtils.tokenize(text1)
        s2 = StringUtils.tokenize(text2)
        if not s1 or not s2: return 0.0
        return len(s1.intersection(s2)) / len(s1.union(s2))

# --- The Intelligence Agency ---

class IntelligenceAgency:
    def __init__(self):
        self.session = self._create_session()
        self.domain_map = {}   # domain -> (id, name)
        self.name_map = {}     # normalized_name -> (id, name)
        self.skeleton_map = {} # skeleton -> (id, name)
        self.known_ids = set()
        # Deep search list: {id, name, domain, tokens, skel}
        self.registry = [] 

    def _create_session(self):
        s = requests.Session()
        retries = Retry(total=5, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
        s.mount('https://', HTTPAdapter(max_retries=retries))
        if GH_TOKEN:
            s.headers.update({'Authorization': f'token {GH_TOKEN}'})
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) MigrationEngine/4.4.4'
        })
        return s

    def initialize(self):
        print("[Intel] Initializing Singularity Vault...")
        self._load_vault()
        self._sync_keiyoushi()
        self._sync_doki()
        print(f"[Intel] Registry contains {len(self.known_ids)} verified sources.")

    def _load_vault(self):
        # Load Vault
        for alias, domain in OMNI_VAULT.items():
            norm = StringUtils.normalize(alias)
            entry = (None, domain)
            self.name_map[norm] = entry
            self.domain_map[domain] = entry
        
        # Load Graveyard
        for dead, alive in GRAVEYARD_MAP.items():
            self.domain_map[dead] = (None, alive)

    def _register(self, sid, name, base_url):
        if not sid: return
        signed_id = StringUtils.to_signed_64(sid)
        self.known_ids.add(signed_id)
        
        entry = (signed_id, name)
        domain = StringUtils.clean_domain(base_url)
        
        record = {
            'id': signed_id,
            'name': name,
            'norm': StringUtils.normalize(name),
            'domain': domain,
            'skel': StringUtils.get_skeleton(name),
            'tokens': StringUtils.tokenize(name)
        }
        self.registry.append(record)
        
        if domain:
            self.domain_map[domain] = entry
            # Link Graveyard & Vault to this ID if they point to this domain
            for d, a in GRAVEYARD_MAP.items():
                if a == domain: self.domain_map[d] = entry
            for k, v in OMNI_VAULT.items():
                if v == domain: self.name_map[StringUtils.normalize(k)] = entry

        self.name_map[record['norm']] = entry
        if record['skel']: self.skeleton_map[record['skel']] = entry

    def _sync_keiyoushi(self):
        for url in KEIYOUSHI_URLS:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200: continue
                if url.endswith('.json'):
                    for ext in resp.json():
                        for src in ext.get('sources', []):
                            self._register(src.get('id'), src.get('name'), src.get('baseUrl'))
                elif url.endswith('.html'):
                    rows = re.findall(r'<tr[^>]*>.*?</tr>', resp.text, flags=re.DOTALL)
                    for row in rows:
                        name_m = re.search(r'class="name"[^>]*>(.*?)<', row)
                        id_m = re.search(r'data-id="(-?d+)"', row)
                        if name_m and id_m:
                            self._register(int(id_m.group(1)), name_m.group(1).strip(), None)
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
                id_m = re.search(r'vals+ids*=s*(d+)L?', txt)
                name_m = re.search(r'vals+names*=s*"([^"]+)"', txt)
                url_m = re.search(r'vals+baseUrls*=s*"([^"]+)"', txt)
                if id_m:
                    name = name_m.group(1) if name_m else f_obj['path'].split('/')[-1].replace('.kt','')
                    self._register(int(id_m.group(1)), name, url_m.group(1) if url_m else None)
        except: pass

# --- The Psychohistory Engine (Matching) ---

class PsychohistoryEngine:
    def __init__(self, intel):
        self.intel = intel

    def match(self, source_name, source_url):
        # Candidates list: tuples of (score, id, name, method)
        candidates = []
        
        norm_input = StringUtils.normalize(source_name)
        domain_input = StringUtils.clean_domain(source_url)
        tokens_input = StringUtils.tokenize(source_name)
        skel_input = StringUtils.get_skeleton(source_name)

        # 1. Exact Domain Match (Score: 1.0)
        if domain_input:
            match = self.intel.domain_map.get(domain_input)
            if match and match[0]:
                candidates.append((1.0, match[0], match[1], "EXACT_DOMAIN"))

        # 2. Vault/Name Match (Score: 0.95)
        match = self.intel.name_map.get(norm_input)
        if match:
            if match[0]:
                candidates.append((0.95, match[0], match[1], "EXACT_NAME"))
            elif isinstance(match[1], str):
                # Resolve pointer
                ptr = self.intel.domain_map.get(match[1])
                if ptr and ptr[0]:
                    candidates.append((0.95, ptr[0], ptr[1], "VAULT_POINTER"))

        # 3. Deep Registry Scan
        for entry in self.intel.registry:
            score = 0.0
            
            # Skeleton Match
            if skel_input and entry['skel'] == skel_input:
                score = max(score, 0.85)
            
            # Token Jaccard
            if tokens_input and entry['tokens']:
                jaccard = len(tokens_input.intersection(entry['tokens'])) / len(tokens_input.union(entry['tokens']))
                if jaccard > 0.6:
                    score = max(score, 0.6 + (jaccard * 0.3)) # 0.6 to 0.9

            # Linguistic Permutation (Lang tags)
            if norm_input in entry['norm'] or entry['norm'] in norm_input:
                # Check for length ratio to avoid "Manga" matching "MangaDex"
                ratio = len(min(norm_input, entry['norm'])) / len(max(norm_input, entry['norm']))
                if ratio > 0.8:
                    score = max(score, 0.80)

            if score > 0.6:
                candidates.append((score, entry['id'], entry['name'], "HEURISTIC"))

        # 4. Fuzzy Fallback
        if not candidates:
            keys = list(self.intel.name_map.keys())
            fuzzy = difflib.get_close_matches(norm_input, keys, n=1, cutoff=0.85)
            if fuzzy:
                m = self.intel.name_map[fuzzy[0]]
                if m[0]: candidates.append((0.7, m[0], m[1], "FUZZY"))

        # Select Winner
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            winner = candidates[0]
            if winner[0] >= 0.7:
                return (winner[1], winner[2])

        # Fallback: Deterministic Hash
        final_name = source_name
        # If we had a vault match but no ID, use the vault target domain as name base
        if match and isinstance(match[1], str):
            final_name = match[1]
            
        return (StringUtils.java_hash(final_name), final_name)

class VoidProber:
    def __init__(self, intel):
        self.intel = intel
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})

    def probe(self, items):
        print(f"[Prober] Scanning {len(items)} voids for redirects...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            future_to_item = {ex.submit(self._trace, i['url']): i for i in items}
            for fut in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[fut]
                new_url = fut.result()
                if new_url:
                    d = StringUtils.clean_domain(new_url)
                    match = self.intel.domain_map.get(d)
                    if match and match[0]:
                     print(f"   -> Redirect Confirmed: {item['source']} -> {match[1]}")
‎                        self.intel.name_map[StringUtils.normalize(item['source'])] = match
‎
‎    def _trace(self, url):
‎        if not url: return None
‎        try:
‎            return self.session.head(url, allow_redirects=True, timeout=5).url
‎        except:
‎            try:
‎                r = self.session.get(url, allow_redirects=True, timeout=5, stream=True)
‎                r.close()
‎                return r.url
‎            except: return None
‎
‎# --- Main Executive ---
‎
‎def main():
‎    try:
‎        import tachiyomi_pb2
‎    except ImportError:
‎        print("❌ Error: tachiyomi_pb2 missing.")
‎        return
‎
‎    if not os.path.exists(KOTATSU_INPUT):
‎        print("❌ Input zip missing.")
‎        return
‎    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
‎
‎    # 1. Init
‎    intel = IntelligenceAgency()
‎    intel.initialize()
‎    engine = PsychohistoryEngine(intel)
‎    prober = VoidProber(intel)
‎
‎    # 2. Read
‎    print("[System] Parsing backup...")
‎    try:
‎        with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
‎            f_file = next((n for n in z.namelist() if 'favourites' in n), None)
‎            if not f_file: raise Exception("No favourites found.")
‎            with z.open(f_file) as f:
‎                data = json.load(f)
‎    except Exception as e:
‎        print(f"❌ Read Error: {e}")
‎        return
‎
‎    # 3. Probe
‎    unknowns = []
‎    for x in data:
‎        m = x.get('manga', {})
‎        sid, _ = engine.match(m.get('source', ''), m.get('url', ''))
‎        if sid not in intel.known_ids:
‎            unknowns.append({'source': m.get('source', ''), 'url': m.get('url', '')})
‎    
‎    if unknowns: prober.probe(unknowns)
‎
‎    # 4. Migrate
‎    backup = tachiyomi_pb2.Backup()
‎    registered = set()
‎    stats = {'official': 0, 'fallback': 0}
‎
‎    for item in data:
‎        m = item.get('manga', {})
‎        url = m.get('url', '') or m.get('public_url', '')
‎        name = m.get('source', '')
‎        
‎        sid, sname = engine.match(name, url)
‎        
‎        if sid in intel.known_ids: stats['official'] += 1
‎        else: stats['fallback'] += 1
‎        
‎        if sid not in registered:
‎            s = tachiyomi_pb2.BackupSource()
‎            s.sourceId = sid
‎            s.name = sname
‎            backup.backupSources.append(s)
‎            registered.add(sid)
‎            
‎        bm = backup.backupManga.add()
‎        bm.source = sid
‎        bm.url = url
‎        bm.title = m.get('title', '')
‎        bm.artist = m.get('artist', '')
‎        bm.author = m.get('author', '')
‎        bm.description = m.get('description', '')
‎        bm.thumbnailUrl = m.get('cover_url', '')
‎        bm.dateAdded = int(item.get('created_at', 0) * 1000) if item.get('created_at') else 0
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
‎    print(f"SINGULARITY MIGRATION COMPLETE (v4.4.4)")
‎    print(f"Total Entries: {len(data)}")
‎    print(f"Perfect Match: {stats['official']}")
‎    print(f"Generated:     {stats['fallback']}")
‎    print(f"File:          {out_path}")
‎    print("="*50)
‎
‎if __name__ == "__main__":
‎    main()
‎
