const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');
const protobuf = require('protobufjs');
const zlib = require('zlib');
const https = require('https');

// --- Configuration ---
const KOTATSU_INPUT = 'Backup.zip';
const TACHI_INPUT = 'Backup.tachibk';
const OUTPUT_DIR = 'output';
const PROTO_FILE = path.join(__dirname, 'schema.proto');
const EXTENSIONS_URL = 'https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json';

// Ensure output dir exists
if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// Maps
const NAME_TO_ID = {};
const ID_TO_NAME = {};

// --- REVERSE ENGINEERED CONSTANTS ---
const ID_SEED = 1125899906842597n; // from kotatsu.helpers

// --- Helper: Fetch Extension Data ---
function fetchExtensions() {
    return new Promise((resolve) => {
        console.log('🌐 Fetching latest extension index from Keiyoushi...');
        https.get(EXTENSIONS_URL, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);
                    processExtensionData(json);
                    resolve(true);
                } catch (e) {
                    console.warn('⚠️ Failed to parse extension index. Using fallback mapping.');
                    resolve(false);
                }
            });
        }).on('error', (err) => {
            console.warn('⚠️ Failed to fetch extensions:', err.message);
            resolve(false);
        });
    });
}

function processExtensionData(data) {
    let count = 0;
    data.forEach(ext => {
        if (ext.sources) {
            ext.sources.forEach(source => {
                const idStr = String(source.id);
                ID_TO_NAME[idStr] = source.name;
                NAME_TO_ID[source.name.toLowerCase()] = idStr;
                
                // Helper for "Tachiyomi: Name" -> "Name"
                if (ext.name.startsWith("Tachiyomi: ")) {
                    const cleanName = ext.name.replace("Tachiyomi: ", "");
                    if (!NAME_TO_ID[cleanName.toLowerCase()]) {
                        NAME_TO_ID[cleanName.toLowerCase()] = idStr;
                    }
                }
                count++;
            });
        }
    });
    console.log(`✅ Loaded ${count} sources into memory.`);
    
    // Manual Overrides
    NAME_TO_ID['mangadex'] = '2499283573021220255';
    NAME_TO_ID['mangakakalot'] = '2528986671771677900';
    NAME_TO_ID['manganelo'] = '1024627298672457456';
    NAME_TO_ID['manganato'] = '1024627298672457456';
    NAME_TO_ID['local'] = '0';
}

// --- Logic from kotatsu/helpers.py ---
function getKotatsuId(str) {
    let h = ID_SEED;
    for (let i = 0; i < str.length; i++) {
        // h = np.add(np.multiply(np.int64(31), h), np.int64(ord(c)))
        h = (31n * h + BigInt(str.charCodeAt(i)));
        // Simulate int64 signed wrapping
        h = BigInt.asIntN(64, h);
    }
    return h; // Returns BigInt
}

// --- Logic from convert/core.py ---

function toKotatsuSource(tySource) {
    if (!tySource) return "";
    if (tySource === "Mangakakalot") return "MANGAKAKALOTTV";
    if (tySource === "Comick") return "COMICK_FUN";
    // Python: return ty_source.upper()
    return tySource.toUpperCase(); 
}

function toKotatsuUrl(tySource, tyUrl) {
    if (tySource === "MangaDex") return tyUrl.replace("/manga/", "").replace("/title/", "");
    if (tySource === "Mangakakalot") return tyUrl.replace("https://chapmanganato.to/", "/manga/");
    if (tySource === "Comick") return tyUrl.replace("/comic/", "");
    return tyUrl;
}

function toKotatsuChapterUrl(tySource, tyUrl) {
    if (tySource === "MangaDex") return tyUrl.replace("/chapter/", "");
    if (tySource === "Mangakakalot") return tyUrl.replace("https://chapmanganato.to/", "/chapter/");
    if (tySource === "Comick") return tyUrl.replace("/comic/", "");
    return tyUrl;
}

function toKotatsuPublicUrl(tySource, ktUrl) {
    if (tySource === "MangaDex") return "https://mangadex.org/title/" + ktUrl;
    if (tySource === "Mangakakalot") return "https://ww7.mangakakalot.tv" + ktUrl;
    if (tySource === "Comick") return "https://comick.cc/comic/" + ktUrl;
    return ktUrl;
}

function toKotatsuStatus(tyStatus) {
    if (tyStatus === 1) return "ONGOING";
    if (tyStatus === 2 || tyStatus === 4) return "FINISHED";
    if (tyStatus === 5) return "ABANDONED";
    if (tyStatus === 6) return "PAUSED";
    return "";
}

// --- Helper: BigInt JSON Serializer ---
// Kotatsu expects raw numbers for IDs in JSON (even if 64-bit).
// JS JSON.stringify fails on BigInt. We must output raw number tokens.
function stringifyWithBigInt(obj) {
    const placeholderPrefix = "BIGINT::";
    const json = JSON.stringify(obj, (key, value) => {
        if (typeof value === 'bigint') {
            return placeholderPrefix + value.toString();
        }
        return value;
    });
    // Remove quotes around BigInt placeholders
    return json.replace(new RegExp(`"${placeholderPrefix}(-?\\d+)"`, 'g'), '$1');
}

// --- Main Logic ---

async function main() {
  console.log('📦 Initializing Migration Kit (Reverse Engineered v6.0)...');
  await fetchExtensions();

  console.log('📖 Loading Protobuf Schema...');
  const root = await protobuf.load(PROTO_FILE);
  const BackupMessage = root.lookupType("tachiyomi.Backup");

  if (fs.existsSync(KOTATSU_INPUT)) {
    await kotatsuToTachiyomi(BackupMessage);
  } else if (fs.existsSync(TACHI_INPUT)) {
    await tachiyomiToKotatsu(BackupMessage);
  } else {
    throw new Error('❌ No backup file found! Please add Backup.zip or Backup.tachibk to the root.');
  }
}

// --- Converters ---

async function kotatsuToTachiyomi(BackupMessage) {
    console.log('🔄 Mode: Kotatsu -> Tachiyomi');
    
    const zip = new AdmZip(KOTATSU_INPUT);
    const zipEntries = zip.getEntries();
    
    let favouritesData = null;
    let categoriesData = null;
    let historyData = null;

    // Scan for files (Kotatsu has no extension for internal files)
    for (const entry of zipEntries) {
        if (entry.isDirectory) continue;
        const name = entry.entryName;
        
        try {
            if (name === 'favourites' || name === 'favourites.json') {
                favouritesData = JSON.parse(entry.getData().toString('utf8'));
                console.log(`✅ Found Library: ${name}`);
            }
            else if (name === 'categories' || name === 'categories.json') {
                categoriesData = JSON.parse(entry.getData().toString('utf8'));
            }
            else if (name === 'history' || name === 'history.json') {
                historyData = JSON.parse(entry.getData().toString('utf8'));
            }
        } catch(e) {}
    }

    if (!favouritesData) throw new Error("Could not find favourites data in Kotatsu backup.");

    // Map Categories
    const catIdMap = new Map();
    const backupCategories = [];
    if (categoriesData) {
        categoriesData.forEach((cat, idx) => {
            backupCategories.push({ name: cat.name, order: cat.sortKey || idx, flags: 0 });
            catIdMap.set(cat.id, cat.sortKey || idx);
        });
    }

    const backupManga = [];
    const backupSources = [];
    const sourceSet = new Set();

    console.log(`📚 Processing ${favouritesData.length} favorites...`);

    // Also map History
    // Kotatsu history is a list of HistoryRecord
    const historyMap = new Map(); // Kotatsu ID -> History Object
    if (historyData) {
        historyData.forEach(h => {
             // h.mangaId matches the manga's generated ID
             historyMap.set(h.mangaId, h);
        });
    }

    favouritesData.forEach(fav => {
        // Kotatsu 7+ structure: favorites contains 'manga' object
        const kManga = fav.manga;
        if (!kManga) return;

        // Reverse map Source ID (if possible)
        // Since we only have NAME_TO_ID (name -> id), we try to find it.
        // Kotatsu source names are UPPERCASE (MANGADEX).
        // We will try to match casing if possible, otherwise hash.
        let tSourceId = "0";
        if (NAME_TO_ID[kManga.source.toLowerCase()]) {
            tSourceId = NAME_TO_ID[kManga.source.toLowerCase()];
        } else {
            // Fallback hash if source unknown
            tSourceId = getSourceId(kManga.source); 
        }

        if (!sourceSet.has(tSourceId)) {
            sourceSet.add(tSourceId);
            backupSources.push({ sourceId: tSourceId, name: kManga.source });
        }

        // Convert History
        const historyList = [];
        if (historyMap.has(kManga.id)) {
            const h = historyMap.get(kManga.id);
            historyList.push({
                url: kManga.url,
                lastRead: h.updated_at || h.created_at,
                readDuration: 0
            });
        }

        // Convert Categories
        const cats = [];
        if (fav.category_id !== undefined && catIdMap.has(fav.category_id)) {
            cats.push(catIdMap.get(fav.category_id));
        }

        backupManga.push({
            source: tSourceId,
            url: kManga.url,
            title: kManga.title,
            artist: "",
            author: kManga.author || "",
            description: "",
            genre: kManga.tags || [],
            status: kManga.state === "ONGOING" ? 1 : 2, // Basic map
            thumbnailUrl: kManga.cover_url || "",
            dateAdded: fav.created_at || Date.now(),
            // Kotatsu backup "favourites.json" typically does not include the chapter list.
            // Tachiyomi will fetch chapters upon refresh.
            chapters: [], 
            categories: cats,
            history: historyList
        });
    });

    const payload = { backupManga, backupCategories, backupSources };
    const message = BackupMessage.create(payload);
    const buffer = BackupMessage.encode(message).finish();
    const gzipped = zlib.gzipSync(buffer);
    
    const outFile = path.join(OUTPUT_DIR, 'converted_tachiyomi.tachibk');
    fs.writeFileSync(outFile, gzipped);
    console.log(`✅ Success! Created: ${outFile}`);
}

async function tachiyomiToKotatsu(BackupMessage) {
    console.log('🔄 Mode: Tachiyomi -> Kotatsu (Reverse Engineered Logic)');
    
    const buffer = fs.readFileSync(TACHI_INPUT);
    const unzipped = zlib.gunzipSync(buffer);
    const message = BackupMessage.decode(unzipped);
    const tachiData = BackupMessage.toObject(message, { defaults: true, longs: String });

    const favorites = [];
    const history = [];

    // Helper: Find Source Name
    const getSrcName = (id) => {
        if (tachiData.backupSources) {
            const s = tachiData.backupSources.find(x => String(x.sourceId) === String(id));
            if (s) return s.name;
        }
        return getSourceName(id); // Fallback to ID map
    };

    const mangaList = tachiData.backupManga || [];
    console.log(`📚 Processing ${mangaList.length} manga...`);

    mangaList.forEach((tm, i) => {
        const tySource = getSrcName(tm.source);
        const kSource = toKotatsuSource(tySource);
        
        const kUrl = toKotatsuUrl(tySource, tm.url);
        const kId = getKotatsuId(kSource + kUrl); // Logic: source + url -> hash
        
        const kPublicUrl = toKotatsuPublicUrl(tySource, kUrl);
        const kStatus = toKotatsuStatus(tm.status);

        // Build Kotatsu Manga Object
        const kManga = {
            id: kId,
            title: tm.title,
            alt_title: null,
            url: kUrl,
            public_url: kPublicUrl,
            rating: -1.0,
            nsfw: false, // Default
            cover_url: tm.thumbnailUrl || "",
            large_cover_url: null,
            state: kStatus,
            author: tm.author || "",
            source: kSource,
            tags: tm.genre || []
        };

        // Build Favorites Entry
        // category_id: default to 0 if none
        const kFav = {
            manga_id: kId,
            category_id: (tm.categories && tm.categories.length > 0) ? (tm.categories[0] + 1) : 0,
            sort_key: 0,
            created_at: Number(tm.dateAdded),
            deleted_at: 0,
            manga: kManga // EMBEDDED MANGA
        };
        favorites.push(kFav);

        // Build History Record
        if (tm.chapters && tm.chapters.length > 0) {
            // Find read chapters
            let latest = null;
            let newest = null;
            
            tm.chapters.forEach(ch => {
                if (ch.read) {
                    if (!latest || ch.chapterNumber > latest.chapterNumber) latest = ch;
                }
                if (!newest || ch.chapterNumber > newest.chapterNumber) newest = ch;
            });

            if (latest) {
                const chUrl = toKotatsuChapterUrl(tySource, latest.url);
                const chId = getKotatsuId(kSource + chUrl);
                
                const percent = (newest && newest.chapterNumber > 0) 
                    ? (latest.chapterNumber / newest.chapterNumber) 
                    : 0;

                const kHist = {
                    manga_id: kId,
                    created_at: Number(tm.dateAdded),
                    updated_at: Number(tm.dateAdded), // or read date
                    chapter_id: chId,
                    page: latest.lastPageRead || 0,
                    scroll: 0,
                    percent: percent,
                    manga: kManga // EMBEDDED MANGA
                };
                history.push(kHist);
            }
        }
    });

    const zip = new AdmZip();
    
    // Kotatsu uses files named 'favourites' and 'history' WITHOUT .json extension
    // And it uses raw numbers for BigInts
    const favJson = stringifyWithBigInt(favorites);
    const histJson = stringifyWithBigInt(history);

    zip.addFile("favourites", Buffer.from(favJson, "utf8"));
    zip.addFile("history", Buffer.from(histJson, "utf8"));
    
    // Note: 'categories' file is not strictly required for restore if IDs match existing or default
    
    const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
    zip.writeZip(outFile);
    console.log(`✅ Success! Created: ${outFile}`);
}

// Helper needed for reverse map if missing
function getSourceId(sourceName) {
  if (!sourceName) return "0";
  const lower = sourceName.toLowerCase();
  if (NAME_TO_ID[lower]) return NAME_TO_ID[lower];
  let hash = 0n;
  for (let i = 0; i < sourceName.length; i++) {
    hash = (31n * hash + BigInt(sourceName.charCodeAt(i))) & 0xFFFFFFFFFFFFFFFFn;
  }
  return hash.toString();
}

function getSourceName(sourceId) {
    const idStr = String(sourceId);
    if (idStr === "0") return "Local";
    if (ID_TO_NAME[idStr]) return ID_TO_NAME[idStr];
    return `Source ${idStr}`;
}

main().catch(err => {
  console.error('❌ FATAL ERROR:', err);
  process.exit(1);
});
