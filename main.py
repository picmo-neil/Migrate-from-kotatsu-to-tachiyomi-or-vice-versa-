import os
import json
import zipfile
import gzip
import struct
import requests
from urllib.parse import urlparse

# Import the compiled protobuf schema
# This requires 'tachiyomi.proto' to be compiled to 'tachiyomi_pb2.py'
try:
    import tachiyomi_pb2
except ImportError:
    print("❌ Error: tachiyomi_pb2.py not found. The workflow must run 'protoc --python_out=. tachiyomi.proto'")
    # Debug aid
    print("Current directory files:", os.listdir('.'))
    exit(1)

# --- CONFIG ---
KOTATSU_INPUT = 'Backup.zip'
TACHI_INPUT = 'Backup.tachibk'
OUTPUT_DIR = 'output'
KEIYOUSHI_URL = "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- 🏆 GOLDEN DATABASE (High Priority) ---
GOLDEN_DB = {
    "mangadex.org": (2499283573021220255, "MangaDex"),
    "manganato.com": (1791778683660516, "Manganato"),
    "chapmanganato.com": (1791778683660516, "Manganato"),
    "readmanganato.com": (1791778683660516, "Manganato"),
    "mangakakalot.com": (2229245767045543, "Mangakakalot"),
    "bato.to": (73976367851206, "Bato.to"),
    "battwo.com": (73976367851206, "Bato.to"),
    "mto.to": (73976367851206, "Bato.to"),
    "asuratoon.com": (6676140324647343467, "Asura Scans"),
    "asurascans.com": (6676140324647343467, "Asura Scans"),
    "flamecomics.com": (7350700882194883466, "Flame Comics"),
    "flamescans.org": (7350700882194883466, "Flame Comics"),
    "reaperscans.com": (5113063529342730466, "Reaper Scans"),
    "comick.io": (4689626359218228302, "Comick"),
    "comick.app": (4689626359218228302, "Comick"),
    "nhentai.net": (7670359809983944111, "NHentai"),
    "mangapark.net": (3078776274472836268, "MangaPark"),
    "mangasee123.com": (4440409403861343016, "MangaSee"),
    "manga4life.com": (1705664535359190141, "MangaLife"),
    "tcbscans.com": (3639678122679549925, "TCB Scans"),
}

# --- KOTATSU MAPPING RESTORED ---
KOTATSU_OVERRIDES = {
    # English Aggregators
    "MANGADEX": "MANGADEX",
    "MANGANATO": "MANGANATO",
    "BATOTO": "BATOTO",
    "MANGAKAKALOT": "MANGAKAKALOT",
    "MANGAPARK": "MANGAPARK",
    "MANGATX": "MANGATX",
    "MANGASEE": "MANGASEE",
    "MANGALIFE": "MANGALIFE",
    "READMANGANATO": "MANGANATO",
    "CHAPMANGANATO": "MANGANATO",
    "COMICK": "COMICK",
    
    # Scanlators
    "ASURA_SCANS": "ASURA_SCANS",
    "FLAME_COMICS": "FLAME_COMICS",
    "REAPER_SCANS": "REAPER_SCANS",
    "TCB_SCANS": "TCB_SCANS",
    "LH_TRANSLATION": "LH_TRANSLATION",
    "DRAKE_SCANS": "DRAKE_SCANS",
    "RESET_SCANS": "RESET_SCANS",
    "COSMIC_SCANS": "COSMIC_SCANS",
    
    # Spanish
    "TU_MANGA_ONLINE": "TU_MANGA_ONLINE",
    "LECTOR_MANGA": "LECTOR_MANGA",
    "MANGAS_ORIGINAL": "MANGAS_ORIGINAL",
    "OLYMPUS_SCANS": "OLYMPUS_SCANS",
    
    # Portuguese
    "MUITO_MANGA": "MUITO_MANGA",
    "LER_MANGA": "LER_MANGA",
    "MANGA_HOST": "MANGA_HOST",
    "NEOX_SCANS": "NEOX_SCANS",
    "GEKKOU_SCANS": "GEKKOU_SCANS",
    
    # Indonesian
    "KIRYU_REV": "KIRYU_REV",
    "WEST_MANGA": "WEST_MANGA",
    "KOMIKCAST": "KOMIKCAST",
}

# --- GLOBAL LIVE MAP ---
LIVE_DOMAIN_MAP = {} # populated at runtime

# --- UTILS ---

def get_domain(url):
    if not url: return None
    if not url.startswith('http'): url = 'https://' + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        domain = domain.replace('www.', '').replace('m.', '')
        if domain.startswith('v') and domain[1].isdigit() and domain[2] == '.':
            domain = domain[3:]
        return domain
    except:
        return None

def to_signed_64(val):
    """Ensures a value is treated as a signed 64-bit integer."""
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

def load_live_data():
    """Fetches the Keiyoushi index to populate unknown sources."""
    print("🌐 Fetching Live Extension Index...")
    try:
        resp = requests.get(KEIYOUSHI_URL, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            count = 0
            for ext in data:
                for src in ext.get('sources', []):
                    d = get_domain(src.get('baseUrl'))
                    if d:
                        LIVE_DOMAIN_MAP[d] = (to_signed_64(src.get('id')), src.get('name'))
                        count += 1
            print(f"✅ Loaded {count} live sources.")
        else:
            print("⚠️ Live fetch failed, using internal DB only.")
    except Exception as e:
        print(f"⚠️ Live fetch error: {e}")

# --- SOURCE REGISTRY ---
class SourceRegistry:
    def __init__(self):
        self.sources = {} # ID -> Name

    def register(self, source_id, name):
        sid = to_signed_64(source_id)
        if sid not in self.sources:
            self.sources[sid] = name
        return sid

    def get_list(self):
        lst = []
        for sid, name in self.sources.items():
            s = tachiyomi_pb2.BackupSource()
            s.sourceId = sid
            s.name = name
            lst.append(s)
        return lst

# --- CONVERTERS ---

def kotatsu_to_tachiyomi():
    print("🔄 Converting Kotatsu -> Tachiyomi")
    load_live_data()
    
    with zipfile.ZipFile(KOTATSU_INPUT, 'r') as z:
        fav_file = next((n for n in z.namelist() if 'favourites' in n), None)
        if not fav_file: raise Exception("No favourites found in zip")
        fav_data = json.loads(z.read(fav_file))

    registry = SourceRegistry()
    backup = tachiyomi_pb2.Backup()

    for item in fav_data:
        manga_data = item.get('manga', {})
        url = manga_data.get('url', '') or manga_data.get('public_url', '')
        title = manga_data.get('title', '')
        k_source = manga_data.get('source', '')
        
        domain = get_domain(url)
        
        # ID LOGIC PRIORITY:
        # 1. Golden DB (Hardcoded)
        # 2. Live DB (Keiyoushi)
        # 3. Fallback Hash
        
        final_id = 0
        final_name = k_source

        if domain in GOLDEN_DB:
            final_id, final_name = GOLDEN_DB[domain]
        elif domain in LIVE_DOMAIN_MAP:
            final_id, final_name = LIVE_DOMAIN_MAP[domain]
        else:
            # Fallback
            seed = f"{k_source}{domain}"
            final_id = java_string_hashcode(seed)
            final_name = f"{k_source} ({domain})" if domain else k_source

        final_id = registry.register(final_id, final_name)

        bm = backup.backupManga.add()
        bm.source = final_id
        bm.url = url
        bm.title = title
        bm.artist = manga_data.get('artist', '') or ''
        bm.author = manga_data.get('author', '') or ''
        bm.description = manga_data.get('description', '') or ''
        bm.status = 1 if manga_data.get('state') == 'ONGOING' else 2
        bm.thumbnailUrl = manga_data.get('cover_url', '') or ''
        bm.dateAdded = int(item.get('created_at', 0))
        
        # FIX: Defensive Tag Handling (v53.0)
        # manga_data.get('tags') can be None, or contain non-strings
        raw_tags = manga_data.get('tags', [])
        if raw_tags is None: raw_tags = []
        for tag in raw_tags:
            if tag:
                try:
                    bm.genre.append(str(tag))
                except Exception:
                    pass # skip bad tags

    backup.backupSources.extend(registry.get_list())

    out_path = os.path.join(OUTPUT_DIR, 'Backup.tachibk')
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())
    
    print(f"✅ Created {out_path} with {len(backup.backupManga)} entries.")

def tachiyomi_to_kotatsu():
    print("🔄 Converting Tachiyomi -> Kotatsu")
    
    with gzip.open(TACHI_INPUT, 'rb') as f:
        backup = tachiyomi_pb2.Backup()
        backup.ParseFromString(f.read())

    source_map = {s.sourceId: s.name for s in backup.backupSources}
    favorites = []
    
    for tm in backup.backupManga:
        s_name = source_map.get(tm.source, "Unknown")
        domain = get_domain(tm.url)
        
        k_key = "MANGADEX"
        upper_name = s_name.upper().replace(" ", "_")
        
        if upper_name in KOTATSU_OVERRIDES:
            k_key = KOTATSU_OVERRIDES[upper_name]
        elif domain == "mangadex.org": k_key = "MANGADEX"
        elif domain == "manganato.com": k_key = "MANGANATO"
        elif domain == "bato.to": k_key = "BATOTO"
        else:
            # Clean common suffixes
            k_key = upper_name.replace("_SCANS", "").replace("_COMICS", "").replace("_ORG", "")

        seed = f"{k_key}{tm.url}"
        kid = str(java_string_hashcode(seed))

        favorites.append({
            "manga_id": kid,
            "category_id": 0,
            "sort_key": 0,
            "created_at": tm.dateAdded,
            "manga": {
                "id": kid,
                "title": tm.title,
                "url": tm.url,
                "public_url": None,
                "source": k_key,
                "state": "FINISHED" if tm.status == 2 else "ONGOING",
                "cover_url": tm.thumbnailUrl,
                "tags": list(tm.genre),
                "author": tm.author
            }
        })

    out_path = os.path.join(OUTPUT_DIR, 'Backup.zip')
    with zipfile.ZipFile(out_path, 'w') as z:
        z.writestr("favourites", json.dumps(favorites))
        z.writestr("history", "[]")
        z.writestr("categories", "[]")
        z.writestr("index", json.dumps({"version": 2, "created_at": 0, "app_version": "52.0"}))
    
    print(f"✅ Created {out_path} with {len(favorites)} entries.")

if __name__ == "__main__":
    if os.path.exists(KOTATSU_INPUT):
        kotatsu_to_tachiyomi()
    elif os.path.exists(TACHI_INPUT):
        tachiyomi_to_kotatsu()
    else:
        print("❌ No backup file found")
        exit(1)
