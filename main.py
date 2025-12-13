import os
import json
import zipfile
import gzip
import struct
import requests
from urllib.parse import urlparse

# Import the compiled protobuf schema
try:
    import tachiyomi_pb2
except ImportError:
    print("❌ Error: tachiyomi_pb2.py not found. The workflow must run 'protoc --python_out=. tachiyomi.proto'")
    exit(1)

# --- CONFIG ---
KOTATSU_INPUT = 'Backup.zip'
TACHI_INPUT = 'Backup.tachibk'
OUTPUT_DIR = 'output'
KEIYOUSHI_URL = "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- 🏆 GOLDEN DATABASE (Verified Canonical IDs) ---
# Use these exact IDs to prevent "Not Installed" errors.
# Formatted as: "domain": (source_id, "Source Name")
GOLDEN_DB = {
    # English Aggregators
    "mangadex.org": (2499283573021220255, "MangaDex"),
    "manganato.com": (1791778683660516, "Manganato"),
    "chapmanganato.com": (1791778683660516, "Manganato"),
    "readmanganato.com": (1791778683660516, "Manganato"),
    "mangakakalot.com": (2229245767045543, "Mangakakalot"),
    "bato.to": (73976367851206, "Bato.to"),
    "battwo.com": (73976367851206, "Bato.to"),
    "mto.to": (73976367851206, "Bato.to"),
    "mangapark.net": (3078776274472836268, "MangaPark"),
    "mangasee123.com": (4440409403861343016, "MangaSee"),
    "manga4life.com": (1705664535359190141, "MangaLife"),
    "tcbscans.com": (3639678122679549925, "TCB Scans"),
    "comick.io": (4689626359218228302, "Comick"),
    "comick.app": (4689626359218228302, "Comick"),
    "nhentai.net": (7670359809983944111, "NHentai"),
    
    # Scanlators (High Traffic)
    "asuratoon.com": (6676140324647343467, "Asura Scans"),
    "asurascans.com": (6676140324647343467, "Asura Scans"),
    "flamecomics.com": (7350700882194883466, "Flame Comics"),
    "flamescans.org": (7350700882194883466, "Flame Comics"),
    "reaperscans.com": (5113063529342730466, "Reaper Scans"),
    "lhtranslation.net": (2927878345167683938, "LHTranslation"),
    "reset-scans.com": (4793836793617132168, "Reset Scans"),
    "drakescan.com": (6662993540226466635, "Drake Scans"),
    
    # Spanish
    "lectormanga.com": (6198642307302302322, "LectorManga"),
    "tumangaonline.com": (6198642307302302322, "TuMangaOnline"),
    "leermanga.net": (6198642307302302322, "LectorManga"), 
    "olympuscans.com": (2539764513689369792, "Olympus Scans"),
    
    # Portuguese
    "mangalivre.net": (5252874288059082351, "Manga Livre"),
    "muitomanga.com": (78946435761, "Muito Manga"), 
    "lermanga.org": (4700947738222384260, "Ler Manga"),
    
    # Indonesian
    "komikcast.com": (6555802271615367624, "KomikCast"),
    "komikcast.cz": (6555802271615367624, "KomikCast"),
    "westmanga.info": (2242173510505199676, "West Manga"),
    "kiryuu.id": (3638407425126134375, "Kiryuu"),
}

# --- UTILS ---

def to_signed_64(val):
    """Encodes an integer as a Java Long (signed 64-bit)."""
    try:
        val = int(val)
        return struct.unpack('q', struct.pack('Q', val & 0xFFFFFFFFFFFFFFFF))[0]
    except:
        return 0

def java_string_hashcode(s):
    """Emulates Java's String.hashCode() to match Tachiyomi's fallback ID generation."""
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
        # Handle 'v1.domain.com'
        if domain.startswith('v') and len(domain) > 2 and domain[1].isdigit() and domain[2] == '.':
            domain = domain[3:]
        return domain.lower()
    except:
        return None

def clean_url(url, domain):
    """
    CRITICAL: Converts Absolute URL -> Relative URL
    Tachiyomi extensions expect '/manga/one-piece', not 'https://mangadex.org/manga/one-piece'
    """
    if not url: return ""
    
    # Logic for specific sources that demand relative paths
    needs_relative = [
        "mangadex", "manganato", "mangakakalot", "bato", "mangapark", 
        "mangasee", "mangalife", "asura", "flame", "reaper"
    ]
    
    # If the domain is in our list of picky sources
    is_picky = any(x in domain for x in needs_relative)
    
    if is_picky and "://" in url:
        try:
            parsed = urlparse(url)
            # Return path + query + fragment
            rel = parsed.path
            if parsed.query: rel += "?" + parsed.query
            return rel
        except:
            return url
            
    return url

# --- LIVE DATA ---
LIVE_DOMAIN_MAP = {}

def load_live_data():
    """Fetches the Keiyoushi index to map unknown sources."""
    print("🌐 Fetching Live Extension Index (Keiyoushi)...")
    try:
        resp = requests.get(KEIYOUSHI_URL, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            count = 0
            for ext in data:
                # Iterate over all sources in this extension
                for src in ext.get('sources', []):
                    base = src.get('baseUrl')
                    d = get_domain(base)
                    sid = src.get('id')
                    name = src.get('name')
                    
                    if d and sid:
                        LIVE_DOMAIN_MAP[d] = (to_signed_64(sid), name)
                        count += 1
            print(f"✅ Loaded {count} live sources from index.")
        else:
            print(f"⚠️ Live fetch failed ({resp.status_code}). Using GOLDEN_DB only.")
    except Exception as e:
        print(f"⚠️ Live fetch error: {e}")

# --- CONVERTERS ---

def kotatsu_to_tachiyomi():
    print("🔄 STARTING MIGRATION: Kotatsu -> Tachiyomi")
    load_live_data()
    
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
    
    print(f"📊 Processing {len(fav_data)} manga entries (No Limit)...")
    
    success_count = 0
    
    for item in fav_data:
        manga_data = item.get('manga', {})
        
        # 1. Extract Details
        raw_url = manga_data.get('url', '') or manga_data.get('public_url', '')
        title = manga_data.get('title', '')
        k_source = manga_data.get('source', '') # Kotatsu source name
        
        domain = get_domain(raw_url)
        
        # 2. Determine Source ID (The "Bridge" Logic)
        final_id = 0
        final_name = k_source
        
        if domain in GOLDEN_DB:
            # Tier 1: Verified Hardcoded ID
            final_id, final_name = GOLDEN_DB[domain]
        elif domain in LIVE_DOMAIN_MAP:
            # Tier 2: Live Index ID
            final_id, final_name = LIVE_DOMAIN_MAP[domain]
        else:
            # Tier 3: Fallback (Legacy Hash)
            # Attempt to generate ID based on Kotatsu source name or domain
            seed = f"{k_source}" 
            final_id = java_string_hashcode(seed)
            final_name = k_source
            print(f"⚠️ Unknown Source: {k_source} ({domain}) -> Generated ID: {final_id}")

        # 3. Register Source
        register_source(final_id, final_name)
        
        # 4. Clean URL (Critical for "Installed" status)
        final_url = clean_url(raw_url, domain)

        # 5. Create Protobuf Object
        bm = backup.backupManga.add()
        bm.source = final_id
        bm.url = final_url
        bm.title = title
        bm.artist = manga_data.get('artist', '') or ''
        bm.author = manga_data.get('author', '') or ''
        bm.description = manga_data.get('description', '') or ''
        
        # Status Mapping: Kotatsu uses string, Tachiyomi uses int
        # 1 = Ongoing, 2 = Completed, 3 = Licensed, 4 = Publishing finished, 5 = Cancelled, 6 = On hiatus
        state = manga_data.get('state', '').upper()
        if state == 'ONGOING': bm.status = 1
        elif state == 'FINISHED': bm.status = 2
        elif state == 'COMPLETED': bm.status = 2
        else: bm.status = 0 # Unknown
        
        bm.thumbnailUrl = manga_data.get('cover_url', '') or ''
        bm.dateAdded = int(item.get('created_at', 0))
        
        # Safe Tag Handling
        raw_tags = manga_data.get('tags', [])
        if raw_tags:
            for tag in raw_tags:
                if tag:
                    try: bm.genre.append(str(tag))
                    except: pass
        
        success_count += 1

    # Add sources to backup
    backup.backupSources.extend(registry_list)

    # Save
    out_path = os.path.join(OUTPUT_DIR, 'Backup.tachibk')
    with gzip.open(out_path, 'wb') as f:
        f.write(backup.SerializeToString())
    
    print(f"✅ SUCCESS: Converted {success_count} manga.")
    print(f"📂 Output saved to {out_path}")

if __name__ == "__main__":
    if os.path.exists(KOTATSU_INPUT):
        kotatsu_to_tachiyomi()
    else:
        print("❌ Backup.zip not found! Please upload your Kotatsu backup.")
        exit(1)
