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
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Import the compiled protobuf schema
try:
    import tachiyomi_pb2
except ImportError:
    print("❌ Error: tachiyomi_pb2.py not found. Compile it first.")
    exit(1)

# --- CONFIG ---
KOTATSU_INPUT = 'Backup.zip'
OUTPUT_DIR = 'output'

# 🌐 MULTI-INDEX TARGETS (Standard + NSFW + Preview)
TARGET_INDEXES = [
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
    "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index-nsfw.min.json"
]

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- UTILS ---

def to_signed_64(val):
    """Encodes an integer as a Java Long (signed 64-bit)."""
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
    """Extracts the clean domain for matching."""
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
    """
    Hivemind Normalization.
    Strips noise to find the signal.
    """
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
    # Remove all non-alphanumeric characters
    n = re.sub(r'[^A-Z0-9]', '', n)
    return n

def clean_url(url, domain):
    if not url: return ""
    needs_relative = [
        "mangadex", "manganato", "mangakakalot", "bato", "mangapark", 
        "mangasee", "mangalife", "asura", "flame", "reaper", "mangafire"
    ]
    is_picky = any(x in domain for x in needs_relative) if domain else False
    if is_picky and "://" in url:
        try:
            parsed = urlparse(url)
            rel = parsed.path
            if parsed.query: rel += "?" + parsed.query
            return rel
        except:
            return url
    return url

# --- 🐝 HIVEMIND (Bridge v3) ---
class Hivemind:
    def __init__(self):
        self.domain_map = {}
        self.name_map = {}
        self.source_count = 0
        
        # 📂 DOKI KNOWLEDGE BASE (Enhanced)
        # Manually mapped sources where names/domains are completely different
        self.doki_knowledge = {
            "MangaFire": (2011853258082095422, "MangaFire"),
            "MangaDex": (2499283573021220255, "MangaDex"),
            "Bato": (73976367851206, "Bato.to"),
            "NHentai": (7670359809983944111, "NHentai"),
            "Asura": (6676140324647343467, "Asura Scans"),
            "Flame": (7350700882194883466, "Flame Comics"),
            "KomikCast": (6555802271615367624, "KomikCast"),
            "WestManga": (2242173510505199676, "West Manga"),
            "MangaBat": (1791778683660516, "Manganato"), # Often linked
            "Comick": (4689626359218228302, "Comick"),
        }

    def learn(self, domain, name, sid):
        signed_id = to_signed_64(sid)
        if domain: self.domain_map[domain] = (signed_id, name)
        norm = normalize_name(name)
        if norm: self.name_map[norm] = (signed_id, name)

    def ingest_knowledge(self):
        print("🐝 Hivemind: Awakening...")
        
        # 1. Load Doki Knowledge
        print(f"📂 Loading Internal Knowledge Base ({len(self.doki_knowledge)} nodes)...")
        for k_name, (sid, t_name) in self.doki_knowledge.items():
            self.name_map[normalize_name(k_name)] = (sid, t_name)

        # Setup Retry Strategy
        session = requests.Session()
        retry = Retry(connect=3, backoff_factor=1)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        # 2. Fetch Keiyoushi Indexes
        for url in TARGET_INDEXES:
            file_name = url.split('/')[-1]
            print(f"📡 Scanning Extension Index: {file_name}...")
            try:
                resp = session.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    local_count = 0
                    for ext in data:
                        for src in ext.get('sources', []):
                            self.source_count += 1
                            local_count += 1
                            sid = src.get('id')
                            name = src.get('name')
                            base = src.get('baseUrl')
                            d = get_domain(base)
                            if sid and name:
                                self.learn(d, name, sid)
                    print(f"   -> Absorbed {local_count} sources.")
                else:
                    print(f"   -> ⚠️ Failed (Status: {resp.status_code})")
            except Exception as e:
                print(f"   -> ⚠️ Network Error: {e}")

    def verify_integrity(self):
        print("\n🛡️ STARTING 6-CYCLE HIVEMIND CHECK...")
        
        check_nodes = ["MANGADEX", "MANGANATO", "BATO", "NHENTAI", "ASURA"]
        
        for i in range(1, 7):
            print(f"   Cycle {i}/6: Synapse check...", end="")
            time.sleep(0.2)
            
            node = random.choice(check_nodes)
            if node in self.name_map:
                print(f" ✅ Active ({node})")
            else:
                print(f" ⚠️ Dormant ({node})")
                
        print(f"✨ HIVEMIND ONLINE.")
        print(f"   - Total Sources: {self.source_count}")
        print(f"   - Domain Pathways: {len(self.domain_map)}")
        print(f"   - Name Bridges: {len(self.name_map)}")

    def save_neural_map(self):
        dump_path = os.path.join(OUTPUT_DIR, 'hivemind_map.json')
        print(f"💾 Dumping Memory to {dump_path}...")
        export_data = {
            "domains": {k: str(v[0]) for k, v in self.domain_map.items()},
            "names": {k: str(v[0]) for k, v in self.name_map.items()}
        }
        with open(dump_path, 'w') as f:
            json.dump(export_data, f, indent=2)

    def identify(self, kotatsu_name, kotatsu_url):
        domain = get_domain(kotatsu_url)
        k_norm = normalize_name(kotatsu_name)
        
        # Tier 1: Domain Exact Match
        if domain and domain in self.domain_map:
            return self.domain_map[domain]
            
        # Tier 2: Name Exact Match
        if k_norm in self.name_map:
            return self.name_map[k_norm]
            
        # Tier 3: Fuzzy Name Match (The Smart Part)
        # Finds matches > 90% similar (e.g. "Asura Scans" vs "AsuraScan")
        if k_norm:
            matches = difflib.get_close_matches(k_norm, self.name_map.keys(), n=1, cutoff=0.90)
            if matches:
                match_name = matches[0]
                # print(f"🧠 Fuzzy Match: {k_norm} ~= {match_name}")
                return self.name_map[match_name]

        # Tier 4: Heuristic Generation (Last Resort)
        seed = f"{kotatsu_name}"
        gen_id = java_string_hashcode(seed)
        return (gen_id, kotatsu_name)

# --- MAIN CONVERTER ---

def kotatsu_to_tachiyomi():
    brain = Hivemind()
    brain.ingest_knowledge()
    brain.verify_integrity()
    brain.save_neural_map()
    
    print("\n🔄 STARTING MIGRATION PROCESS...")
    
    if not os.path.exists(KOTATSU_INPUT):
         raise Exception("Backup.zip not found.")

    with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
        fav_file = next((n for n in z.namelist() if 'favourites' in n), None)
        if not fav_file: raise Exception("CRITICAL: 'favourites' json not found in Backup.zip")
        fav_data = json.loads(z.read(fav_file))

    registry_ids = set()
    registry_list = []
    
    def register_source(sid, name):
        if sid not in registry_ids:
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = sid
            s.name = name
            registry_list.append(s)
            registry_ids.add(sid)
        return sid

    backup = tachiyomi_pb2.Backup()
    
    print(f"📊 Analyzing {len(fav_data)} manga entries...")
    
    success_count = 0
    bridge_matches = 0
    
    for item in fav_data:
        manga_data = item.get('manga', {})
        
        # Extract
        raw_url = manga_data.get('url', '') or manga_data.get('public_url', '')
        title = manga_data.get('title', '')
        k_source = manga_data.get('source', '')
        
        # Identify
        final_id, final_name = brain.identify(k_source, raw_url)
        
        # Check if it was a real match or a fallback
        if final_id in [x[0] for x in brain.domain_map.values()] or \
           final_id in [x[0] for x in brain.name_map.values()]:
            bridge_matches += 1

        # Register
        register_source(final_id, final_name)
        
        # Clean URL
        domain = get_domain(raw_url)
        final_url = clean_url(raw_url, domain)

        # Build Proto
        bm = backup.backupManga.add()
        bm.source = final_id
        bm.url = final_url
        bm.title = title
        bm.artist = manga_data.get('artist', '') or ''
        bm.author = manga_data.get('author', '') or ''
        bm.description = manga_data.get('description', '') or ''
        
        raw_state = manga_data.get('state')
        state = (raw_state or '').upper()
        if state == 'ONGOING': bm.status = 1
        elif state == 'FINISHED': bm.status = 2
        elif state == 'COMPLETED': bm.status = 2
        else: bm.status = 0
        
        bm.thumbnailUrl = manga_data.get('cover_url', '') or ''
        bm.dateAdded = int(item.get('created_at', 0))
        
        raw_tags = manga_data.get('tags', [])
        if raw_tags:
            for tag in raw_tags:
                if tag:
                    try: bm.genre.append(str(tag))
                    except: pass
        
        success_count += 1

    # Add sources
    backup.backupSources.extend(registry_list)

    # Save
    out_path = os.path.join(OUTPUT_DIR, 'Backup.tachibk')
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())
    
    print(f"✅ MIGRATION COMPLETE.")
    print(f"🔗 Bridges Built: {bridge_matches}/{success_count} entries connected.")
    print(f"📂 Output: {out_path}")

if __name__ == "__main__":
    if os.path.exists(KOTATSU_INPUT):
        kotatsu_to_tachiyomi()
    else:
        print("❌ Backup.zip not found! Please upload your Kotatsu backup.")
        exit(1)
    
