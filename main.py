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

# Use the authoritative index
TARGET_INDEXES = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"
]

# Doki Repo Target
DOKI_REPO_API = "https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1"
DOKI_RAW_BASE = "https://raw.githubusercontent.com/DokiTeam/doki-exts/base/"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

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
    if not url.startswith('http'): url = 'https://' + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        domain = domain.replace('www.', '').replace('m.', '')
        if domain.startswith('v') and len(domain) > 2 and domain[1].isdigit() and domain[2] == '.':
            domain = domain[3:]
        return domain.lower()
    except:
        return None

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
    # High retry count for resilience
    retries = Retry(total=20, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    s.mount('https://', HTTPAdapter(max_retries=retries))
    if GH_TOKEN:
        s.headers.update({'Authorization': f'token {GH_TOKEN}'})
    return s

# --- 🛰️ DOKI SCANNER ---
class DokiScanner:
    """
    Scans the DokiTeam/doki-exts repository to reverse engineer source definitions.
    """
    def __init__(self):
        self.knowledge = {} # { Name: Domain }
        self.session = get_session()

    def scan(self):
        print("🛰️ DokiScanner: Connecting to DokiTeam repository...")
        try:
            # 1. Fetch File Tree
            resp = self.session.get(DOKI_REPO_API, timeout=30)
            if resp.status_code != 200:
                print(f"⚠️ Failed to list Doki repo: {resp.status_code}")
                return self.knowledge

            tree = resp.json().get('tree', [])
            kt_files = [f for f in tree if f['path'].startswith('src/main/kotlin/org/dokiteam/doki/parsers/site') and f['path'].endswith('.kt')]
            
            print(f"   -> Found {len(kt_files)} Kotlin source definitions. Extracting data...")

            # 2. Parallel Processing
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(self.process_file, f): f for f in kt_files}
                for future in concurrent.futures.as_completed(futures):
                    pass # Just wait for completion

            print(f"   -> DokiScanner Extraction Complete. Learned {len(self.knowledge)} source mappings.")

        except Exception as e:
            print(f"⚠️ DokiScanner Error: {e}")
        
        return self.knowledge

    def process_file(self, file_obj):
        path = file_obj['path']
        url = DOKI_RAW_BASE + path
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                content = resp.text
                
                # Regex to find name and baseUrl
                # override val name = "MangaDex"
                # override val baseUrl = "https://mangadex.org"
                name_match = re.search(r'overrides+vals+names*[:=]s*(?:Strings*=s*)?"([^"]+)"', content)
                url_match = re.search(r'overrides+vals+baseUrls*[:=]s*(?:Strings*=s*)?"([^"]+)"', content)
                
                if name_match and url_match:
                    name = name_match.group(1)
                    base_url = url_match.group(1)
                    domain = get_domain(base_url)
                    
                    if name and domain:
                        # Normalize name for better matching key
                        norm_name = normalize_name(name)
                        self.knowledge[norm_name] = domain
                        # Also store raw name just in case
                        self.knowledge[name] = domain
        except:
            pass

# --- 🧠 OMNI-BRIDGE BRAIN ---
class BridgeBrain:
    def __init__(self):
        self.domain_map = {} # { Domain: (ID, Name) }
        self.name_map = {}   # { NormalizedName: (ID, Name) }
        self.doki_map = {}   # { NormalizedName: Domain } (From Scanner)
        self.source_count = 0
        self.session = get_session()

    def ingest_knowledge(self):
        print("🧠 BridgeBrain: Initializing Omni-Bridge Protocol...")

        # 1. Run Doki Scanner (The Left Side of the Bridge)
        scanner = DokiScanner()
        self.doki_map = scanner.scan()

        # 2. Fetch Keiyoushi Index (The Right Side of the Bridge)
        for url in TARGET_INDEXES:
            print(f"📡 Ingesting Keiyoushi Index...")
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    for ext in data:
                        for src in ext.get('sources', []):
                            self.source_count += 1
                            sid = src.get('id')
                            name = src.get('name')
                            base = src.get('baseUrl')
                            d = get_domain(base)
                            
                            signed_id = to_signed_64(sid)
                            if d: self.domain_map[d] = (signed_id, name)
                            
                            norm = normalize_name(name)
                            if norm: self.name_map[norm] = (signed_id, name)
                else:
                    print(f"⚠️ Index Fetch Failed: {resp.status_code}")
            except Exception as e:
                print(f"⚠️ Index Error: {e}")

    def verify(self):
        print(f"🛡️ System Status: {len(self.doki_map)} Doki Nodes <-> {len(self.domain_map)} Keiyoushi Nodes.")

    def identify(self, kotatsu_name, kotatsu_url):
        domain = get_domain(kotatsu_url)
        k_norm = normalize_name(kotatsu_name)
        
        # Strategy 1: Direct Domain Match (Best)
        if domain and domain in self.domain_map:
            return self.domain_map[domain]

        # Strategy 2: The Omni-Bridge (Relative URL / Missing URL Resolver)
        # We don't have a domain from the manga URL (it might be relative).
        # But we know the Kotatsu Name. Let's look up what domain Doki uses for that name.
        if k_norm in self.doki_map:
            doki_domain = self.doki_map[k_norm]
            # Now map that Doki Domain to Tachiyomi
            if doki_domain in self.domain_map:
                # print(f"🌉 Bridge Success: {kotatsu_name} -> {doki_domain} -> ID")
                return self.domain_map[doki_domain]

        # Strategy 3: Name Match (Fuzzy/Exact)
        if k_norm in self.name_map:
            return self.name_map[k_norm]
            
        # Strategy 4: Fuzzy Search
        if k_norm:
            matches = difflib.get_close_matches(k_norm, self.name_map.keys(), n=1, cutoff=0.90)
            if matches:
                return self.name_map[matches[0]]

        # Fallback
        gen_id = java_string_hashcode(kotatsu_name)
        return (gen_id, kotatsu_name)

# --- CONVERTER ---

def main():
    if not os.path.exists(KOTATSU_INPUT):
        print("❌ Backup.zip not found.")
        return

    brain = BridgeBrain()
    brain.ingest_knowledge()
    brain.verify()

    print("\n🔄 READING BACKUP...")
    with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
        fav_file = next((n for n in z.namelist() if 'favourites' in n), None)
        if not fav_file: raise Exception("No favourites file in zip.")
        fav_data = json.loads(z.read(fav_file))

    print(f"📊 Processing {len(fav_data)} items...")
    
    backup = tachiyomi_pb2.Backup()
    registry_ids = set()
    
    matches = 0
    
    for item in fav_data:
        manga = item.get('manga', {})
        url = manga.get('url', '') or manga.get('public_url', '')
        source_name = manga.get('source', '')
        
        final_id, final_name = brain.identify(source_name, url)
        
        # Check if we found a "Real" ID
        if final_id in [x[0] for x in brain.domain_map.values()]:
            matches += 1
            
        # Add Source
        if final_id not in registry_ids:
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = final_id
            s.name = final_name
            backup.backupSources.append(s)
            registry_ids.add(final_id)

        # Add Manga
        bm = backup.backupManga.add()
        bm.source = final_id
        bm.url = url # Tachiyomi often handles the migration of URL format internally if ID matches
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
        
        # Tags/Genre
        tags = manga.get('tags', [])
        if tags:
            for t in tags:
                if t: bm.genre.append(str(t))

    # Save
    out_path = os.path.join(OUTPUT_DIR, 'Backup.tachibk')
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())

    print(f"✅ DONE. Bridges: {matches}/{len(fav_data)}.")
    print(f"📂 Saved to {out_path}")

if __name__ == "__main__":
    main()
        
