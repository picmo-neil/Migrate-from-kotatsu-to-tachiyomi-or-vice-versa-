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

# Cortex B Target
TARGET_INDEXES = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"
]

# Cortex A Target
DOKI_REPO_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- DATABASE (1000+ FALLBACK) ---
# A consolidated list of the most popular sources to ensure connectivity.
STATIC_WISDOM = {
    # Aggregators & Giants
    "MANGADEX": "mangadex.org", "MANGANATO": "manganato.com", "MANGAKAKALOT": "mangakakalot.com",
    "BATO": "bato.to", "BATOTO": "bato.to", "NHENTAI": "nhentai.net", "VIZ": "viz.com",
    "WEBTOONS": "webtoons.com", "TAPAS": "tapas.io", "BILIBILI": "bilibilicomics.com",
    "MANGASEE": "mangasee123.com", "MANGALIFE": "manga4life.com", "MANGAPARK": "mangapark.net",
    "KISSMANGA": "kissmanga.org", "MANGAFIRE": "mangafire.to", "MANGATOWN": "mangatown.com",
    "READM": "readm.org", "NINEMANGA": "ninemanga.com", "MANGATUBE": "mangatube.site",
    "MANGAHUB": "mangahub.io", "MANGABOX": "mangabox.me", "MANGAEDEN": "mangaeden.com",
    "MANGAHERE": "mangahere.cc", "MANGAFOX": "fanfox.net", "MANGAPANDA": "mangapanda.com",
    "MANGAREADER": "mangareader.to", "READMANGA": "readmanga.me", "MINTMANGA": "mintmanga.com",
    
    # Scanlation Groups
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
    "WORLD": "manhwaworld.com", "MARTIAL": "martialscans.com", "MARTIALSCANS": "martialscans.com",
    "MERAKI": "merakiscans.com", "MERAKISCANS": "merakiscans.com", "METHOD": "methodscans.com",
    "METHODSCANS": "methodscans.com", "MNGDOOM": "mngdoom.com", "MOODY": "moodyscans.com",
    "MOODYSCANS": "moodyscans.com", "MOON": "moonwitch.fr", "MOONWITCH": "moonwitch.fr",
    "NEOX": "neoxscans.net", "NEOXSCANS": "neoxscans.net", "NIGHT": "nightscans.net",
    "NIGHTSCANS": "nightscans.net", "NIGHTCOMIC": "nightcomic.com", "NIGHTCOMICS": "nightcomic.com",
    "NONSTOP": "nonstopscans.com", "NONSTOPSCANS": "nonstopscans.com", "NOVA": "novascans.com",
    "NOVASCANS": "novascans.com", "OLYMPUS": "olympusscans.com", "OLYMPUSSCANS": "olympusscans.com",
    "PAIRS": "pairscans.com", "PAIRSCANS": "pairscans.com", "PHANTOM": "phantomscans.com",
    "PHANTOMSCANS": "phantomscans.com", "PHOENIX": "phoenixscans.com", "PHOENIXSCANS": "phoenixscans.com",
    "POCKET": "pocketcomics.com", "POCKETCOMICS": "pocketcomics.com", "PROJECT": "projectscan.com",
    "PROJECTSCAN": "projectscan.com", "RAVEN": "ravenscans.com", "RAVENSCANS": "ravenscans.com",
    "REALM": "realmscans.com", "REALMSCANS": "realmscans.com", "REAPER": "reaperscans.com",
    "REAPERSCANS": "reaperscans.com", "RED": "redribbon.site", "REDRIBBON": "redribbon.site",
    "RISING": "risingscans.com", "RISINGSCANS": "risingscans.com", "S2MANGA": "s2manga.com",
    "S2SCANS": "s2scans.com", "SAMURAI": "samuraiscan.com", "SAMURAISCAN": "samuraiscan.com",
    "SECRET": "secretscans.co", "SECRETSCANS": "secretscans.co", "SENSEI": "senseiscan.com",
    "SENSEISCAN": "senseiscan.com", "SHOUJO": "shoujopower.com", "SHOUJOPOWER": "shoujopower.com",
    "SIERRA": "sierramanga.com", "SIERRAMANGA": "sierramanga.com", "SILENT": "silentsky-scans.net",
    "SILENTSKY": "silentsky-scans.net", "SK": "skscans.com", "SKSCANS": "skscans.com",
    "SKY": "skymanga.co", "SKYMANGA": "skymanga.co", "SLEEPY": "sleepypanda.co",
    "SLEEPYPANDA": "sleepypanda.co", "SOLO": "sololeveling.net", "SOLOLEVELING": "sololeveling.net",
    "STAGE": "stagescans.com", "STAGESCANS": "stagescans.com", "STAR": "starboundscans.com",
    "STARBOUND": "starboundscans.com", "SUGAR": "sugarbbscan.com", "SUGARBB": "sugarbbscan.com",
    "SUN": "sunrisemanga.com", "SUNRISE": "sunrisemanga.com", "SUSHI": "sushiscan.su",
    "SUSHISCAN": "sushiscan.su", "SWORD": "swordmanga.com", "SWORDMANGA": "swordmanga.com",
    "TEAMS": "team1x1.com", "TEAM1X1": "team1x1.com", "TECB": "tecno-scan.com",
    "TECNOSCAN": "tecno-scan.com", "TEMPEST": "tempestscans.com", "TEMPESTSCANS": "tempestscans.com",
    "THEGUILD": "theguildscans.com", "GUILD": "theguildscans.com", "THENONAMES": "thenonames.com",
    "NONAMES": "thenonames.com", "THREE": "threesqueens.com", "THREESQUEENS": "threesqueens.com",
    "TIMELESS": "timelessleaf.com", "TIMELESSLEAF": "timelessleaf.com", "TITAN": "titanscans.com",
    "TITANSCANS": "titanscans.com", "TOKYO": "tokyoghoul.site", "TOKYOGHOUL": "tokyoghoul.site",
    "TRITINIA": "tritiniascans.ml", "TRITINIASCANS": "tritiniascans.ml", "TU": "tumangaonline.com",
    "TUMANGAONLINE": "tumangaonline.com", "TMO": "tumangaonline.com", "TWILIGHT": "twilightscans.com",
    "TWILIGHTSCANS": "twilightscans.com", "TWISTED": "twistedhelscans.com", "TWISTEDHEL": "twistedhelscans.com",
    "VALHALLA": "valhallascans.com", "VALHALLASCANS": "valhallascans.com", "VORTEX": "vortexscans.org",
    "VORTEXSCANS": "vortexscans.org", "WEBTOON": "webtoon.xyz", "WEBTOONXYZ": "webtoon.xyz",
    "WEST": "westmanga.info", "WESTMANGA": "westmanga.info", "WHIM": "whimsubs.xyz",
    "WHIMSUBS": "whimsubs.xyz", "WHITE": "whitecloudpavilion.com", "WHITECLOUD": "whitecloudpavilion.com",
    "WINTER": "winterscan.com", "WINTERSCAN": "winterscan.com", "WITCH": "witchscans.com",
    "WITCHSCANS": "witchscans.com", "WOLF": "wolfscans.com", "WOLFSCANS": "wolfscans.com",
    "WORLD": "worldthree.com", "WORLDTHREE": "worldthree.com", "XIAN": "xianxia.com",
    "XIANXIA": "xianxia.com", "YAOI": "yaoi.mobi", "YAOIMOBI": "yaoi.mobi",
    "YGEN": "ygenscans.com", "YGENSCANS": "ygenscans.com", "YOKAI": "yokai.com",
    "YOKAIJUMP": "yokai.com", "YOMANGA": "yomanga.info", "YOSH": "yosh.xyz",
    "YOSHIKU": "yosh.xyz", "ZERO": "zeroscans.com", "ZEROSCANS": "zeroscans.com",
    "ZIN": "zinmanga.com", "ZINMANGA": "zinmanga.com", "ZOO": "zooscans.com",
    "ZOOSCANS": "zooscans.com"
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

def tokenize_name(name):
    """Breaks 'Asura Scans' into {'ASURA', 'SCANS'} for fuzzy set matching"""
    return set(re.findall(r'[A-Z0-9]+', name.upper()))

def get_session():
    s = requests.Session()
    retries = Retry(total=20, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retries))
    if GH_TOKEN:
        s.headers.update({'Authorization': f'token {GH_TOKEN}'})
    return s

# --- 🛰️ CORTEX A: DOKI POLYGLOT SCANNER ---
class DokiCortex:
    def __init__(self):
        self.knowledge = {} # { Key: Domain }
        self.session = get_session()

    def scan(self):
        print("🛰️ Cortex A: Scanning DokiTeam Repo (Polyglot Mode)...")
        try:
            resp = self.session.get(DOKI_REPO_API, timeout=30)
            if resp.status_code != 200:
                print(f"⚠️ Repo API blocked: {resp.status_code}. Using Omni-Database.")
                return self.knowledge

            tree = resp.json().get('tree', [])
            kt_files = [f for f in tree if f['path'].endswith('.kt')]
            
            print(f"   -> Found {len(kt_files)} files. Extracting domain DNA...")

            with concurrent.futures.ThreadPoolExecutor(max_workers=60) as executor:
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
        """
        Polyglot Parsing: Looks for String Literals that resemble domains.
        """
        potential_domains = set()
        
        # Regex for string literals containing dots, no spaces, length > 4
        raw_strings = re.findall(r'"([^"s]+.[^"s]+)"', content)
        
        for s in raw_strings:
            if '/' in s and not s.startswith('http'): continue
            if s.endswith('.kt') or s.endswith('.json'): continue
            
            d = get_domain(s)
            if d: potential_domains.add(d)

        potential_ids = set(re.findall(r'"([A-Z0-9_]{3,})"', content))

        if potential_domains:
            best_domain = sorted(list(potential_domains), key=len)[0]
            self.knowledge[normalize_name(filename)] = best_domain
            self.knowledge[filename] = best_domain
            for pid in potential_ids:
                self.knowledge[normalize_name(pid)] = best_domain
                self.knowledge[pid] = best_domain

# ---  BRIDGE BRAIN ---
class BridgeBrain:
    def __init__(self):
        self.domain_map = {} 
        self.root_domain_map = {}
        self.name_map = {}   
        self.doki_map = {}  
        self.session = get_session()

    def ingest(self):
        print("🧠 BridgeBrain: Initializing The Singularity (v64.0)...")
        
        # 1. LIVE FETCH DOKI (Cortex A)
        doki_cortex = DokiCortex()
        self.doki_map = doki_cortex.scan()

        # 2. INGEST OMNI-DATABASE (Fallback)
        print("📚 Loading Omni-Database (1000+ Entries)...")
        for k, v in STATIC_WISDOM.items():
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
        """Generates domain variants for Hallucination Check"""
        n = normalize_name(name).lower()
        if not n: return []
        
        clean = n.replace("scans", "").replace("scan", "").replace("comics", "").replace("comic", "")
        
        candidates = [
            f"{n}.com", f"{n}.net", f"{n}.org", f"{n}.to", f"{n}.io", f"{n}.gg", f"{n}.cc", f"{n}.me",
            f"read{n}.com", f"{n}scans.com", f"{n}-scans.com",
            f"{clean}.com", f"{clean}.to", f"{clean}.io", f"read{clean}.com", f"{clean}.net", f"{clean}.org"
        ]
        return candidates

    def fuzzy_match(self, name):
        if not name: return None
        tokens = tokenize_name(name)
        if not tokens: return None

        best_score = 0
        best_match = None

        for k_name, (sid, sname) in self.name_map.items():
            k_tokens = tokenize_name(k_name)
            if not k_tokens: continue
            common = tokens.intersection(k_tokens)
            if not common: continue
            score = len(common) / max(len(tokens), len(k_tokens))
            if score > best_score:
                best_score = score
                best_match = (sid, sname)
        
        if best_score >= 0.6: return best_match
        return None

    def identify(self, kotatsu_name, kotatsu_url):
        # STAGE 1: THE GOD LINK (Reverse Engineering)
        manga_domain = get_domain(kotatsu_url)
        if manga_domain:
            if manga_domain in self.domain_map:
                return self.domain_map[manga_domain]
            root = get_root_domain(manga_domain)
            if root and root in self.root_domain_map:
                return self.root_domain_map[root]

        # STAGE 2: CORTEX A (Polyglot)
        k_norm = normalize_name(kotatsu_name)
        learned_domain = self.doki_map.get(k_norm) or self.doki_map.get(kotatsu_name)
        
        if learned_domain:
            if learned_domain in self.domain_map:
                return self.domain_map[learned_domain]
            learned_root = get_root_domain(learned_domain)
            if learned_root and learned_root in self.root_domain_map:
                return self.root_domain_map[learned_root]

        # STAGE 3: DIRECT NAME
        if k_norm in self.name_map:
            return self.name_map[k_norm]

        # STAGE 4: QUANTUM PERMUTATION (Hallucination Check)
        for candidate in self.synthesize_permutations(kotatsu_name):
            cand_domain = get_domain(candidate)
            if cand_domain in self.domain_map:
                return self.domain_map[cand_domain]
            cand_root = get_root_domain(cand_domain)
            if cand_root 
