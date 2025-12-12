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

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// ---  KNOWLEDGE BASE ---
// mapping for high-accuracy migration
const SOURCE_DB = [
    // Top Global
    { tId: "2499283573021220255", kName: "MANGADEX", name: "MangaDex", domain: "mangadex.org" },
    { tId: "2973143899120668045", kName: "MANGA_SEE", name: "MangaSee", domain: "mangasee123.com" },
    { tId: "2973143899120668045", kName: "MANGA_LIFE", name: "MangaLife", domain: "mangalife.us" },
    { tId: "8985172093557431221", kName: "BATO_TO", name: "Bato.to", domain: "bato.to" },
    
    // Manganato Family
    { tId: "2528986671771677900", kName: "MANGAKAKALOTTV", name: "Mangakakalot", domain: "mangakakalot.com" },
    { tId: "1024627298672457456", kName: "MANGANATO", name: "Manganato", domain: "manganato.com" },
    { tId: "1024627298672457456", kName: "CHAPMANGANATO", name: "Manganato", domain: "chapmanganato.to" },
    { tId: "1024627298672457456", kName: "READMANGANATO", name: "Manganato", domain: "readmanganato.com" },

    // Asura Family (Many domains)
    { tId: "6335003343669033128", kName: "ASURA_SCANS", name: "Asura Scans", domain: "asuratoon.com" },
    { tId: "6335003343669033128", kName: "ASURA_SCANS_NET", name: "Asura Scans", domain: "asuracomic.net" },
    { tId: "6335003343669033128", kName: "ASURA_SCANS_GG", name: "Asura Scans", domain: "asura.gg" },

    // Top Scanlators
    { tId: "7027219105529276946", kName: "FLAME_COMICS", name: "Flame Comics", domain: "flamecomics.com" },
    { tId: "7027219105529276946", kName: "FLAME_SCANS", name: "Flame Comics", domain: "flamescans.org" },
    { tId: "5432970425689607116", kName: "REAPER_SCANS", name: "Reaper Scans", domain: "reaperscans.com" },
    { tId: "374242698294247514", kName: "TCB_SCANS", name: "TCB Scans", domain: "tcbscans.com" },
    { tId: "3650631607354829018", kName: "ALLPORN_COMIC", name: "AllPornComic", domain: "allporncomic.com" },
    { tId: "8158721336644791464", kName: "COMICK_FUN", name: "Comick", domain: "comick.io" },
    
    // Manhwa/Webtoons
    { tId: "1989436384073367980", kName: "WEBTOONS", name: "Webtoons", domain: "webtoons.com" },
    { tId: "5502656519292762717", kName: "MANHWA_18_CC", name: "Manhwa18.cc", domain: "manhwa18.cc" },
    { tId: "6750082404202711318", kName: "TOONILY", name: "Toonily", domain: "toonily.com" },
    { tId: "4088566215115473619", kName: "MANHUA_FAST", name: "ManhuaFast", domain: "manhuafast.com" },
    { tId: "4390997657042630109", kName: "HI_PERDEX", name: "Hiperdex", domain: "hiperdex.com" },
    { tId: "3707293521087813296", kName: "MANGA_PARK", name: "MangaPark", domain: "mangapark.net" },
    { tId: "5870005527666249265", kName: "1ST_KISS_MANGA", name: "1st Kiss", domain: "1stkissmanga.io" },
    { tId: "5426176527506972412", kName: "MANGA_PILL", name: "MangaPill", domain: "mangapill.com" },
    
    // Problematic Sources / Fallbacks
    { tId: "1055223398939634718", kName: "TRUEMANGA", name: "TrueManga", domain: "truemanga.com" },
    { tId: "0", kName: "LOCAL", name: "Local", domain: "" }
];

// Global Maps
const NAME_TO_ID = {};     
const SANITIZED_TO_ID = {}; 
const DOMAIN_TO_ID = {};
const KNOWN_SOURCES = [];
const ID_TO_NAME = {};
const KOTATSU_TO_TACHI_MAP = {};
const ID_SEED = 1125899906842597n; 

// Initialize Knowledge Base
SOURCE_DB.forEach(entry => {
    // Bidirectional Maps
    KOTATSU_TO_TACHI_MAP[entry.kName] = entry.tId;
    KOTATSU_TO_TACHI_MAP[entry.name.toUpperCase().replace(/ /g, '_')] = entry.tId;
    
    if (entry.domain) {
        DOMAIN_TO_ID[entry.domain] = entry.tId;
    }

    // Advanced Search Lists
    NAME_TO_ID[entry.name.toLowerCase()] = entry.tId;
    
    const san = sanitize(entry.name);
    SANITIZED_TO_ID[san] = entry.tId;
    
    ID_TO_NAME[entry.tId] = entry.name;
    KNOWN_SOURCES.push({ name: entry.name, id: entry.tId, sanitized: san });
});

// --- 🧠 Helper: Sanitize & Score ---
function sanitize(str) {
    if (!str) return "";
    return str.toLowerCase()
        .replace(/[^a-z0-9]/g, "") // Remove special chars
        .replace(/scans?$/, "")    // Remove 'scan' or 'scans' suffix
        .replace(/comics?$/, "")   // Remove 'comic' or 'comics' suffix
        .replace(/fansub$/, "")
        .replace(/team$/, "")
        .replace(/no$/, "")        // e.g. "Scanlation No" -> "Scanlation"
        .trim();
}

function levenshtein(s, t) {
    if (!s) return t.length;
    if (!t) return s.length;
    const d = [];
    for (let i = 0; i <= s.length; i++) d[i] = [i];
    for (let j = 0; j <= t.length; j++) d[0][j] = j;
    for (let i = 1; i <= s.length; i++) {
        for (let j = 1; j <= t.length; j++) {
            const cost = s[i - 1] === t[j - 1] ? 0 : 1;
            d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
        }
    }
    return d[s.length][t.length];
}

// --- Helper: Fetch Extension Data ---
function fetchExtensions() {
    return new Promise((resolve) => {
        console.log('🌐 Fetching Keiyoushi Extension Index...');
        https.get(EXTENSIONS_URL, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);
                    processExtensionData(json);
                    resolve(true);
                } catch (e) {
                    console.warn('⚠️ Failed to parse extension index. Using offline database only.');
                    resolve(false);
                }
            });
        }).on('error', (err) => {
            console.warn('⚠️ Connection error (Offline Mode):', err.message);
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
                const name = source.name;
                const san = sanitize(name);

                ID_TO_NAME[idStr] = name;
                if (!NAME_TO_ID[name.toLowerCase()]) NAME_TO_ID[name.toLowerCase()] = idStr;
                if (!SANITIZED_TO_ID[san]) SANITIZED_TO_ID[san] = idStr;
                
                KNOWN_SOURCES.push({ name, id: idStr, sanitized: san });
                
                // Tachiyomi specific prefix handling
                if (ext.name.startsWith("Tachiyomi: ")) {
                    const cleanName = ext.name.replace("Tachiyomi: ", "");
                    const cleanSan = sanitize(cleanName);
                    NAME_TO_ID[cleanName.toLowerCase()] = idStr;
                    SANITIZED_TO_ID[cleanSan] = idStr;
                    KNOWN_SOURCES.push({ name: cleanName, id: idStr, sanitized: cleanSan });
                }
                count++;
            });
        }
    });
    console.log(`✅ Knowledge Base Expanded: ${count} extensions loaded.`);
}

// --- Logic from kotatsu/helpers.py ---
function getKotatsuId(str) {
    let h = ID_SEED;
    for (let i = 0; i < str.length; i++) {
        h = (31n * h + BigInt(str.charCodeAt(i)));
        h = BigInt.asIntN(64, h); 
    }
    return h;
}

// --- Smart Bidirectional Converters ---

// Tachi Source -> Kotatsu Source
function predictKotatsuSourceName(tachiName, tachiId, url) {
    // 1. Check DB
    const dbMatch = SOURCE_DB.find(x => x.tId === String(tachiId));
    if (dbMatch) return dbMatch.kName;

    // 2. Heuristic from Name
    if (tachiName) {
        let clean = tachiName.trim();
        // Specific Fixes
        if (clean.toLowerCase() === "manganato") return "MANGANATO"; // Default
        
        return clean.replace(/\s+/g, '_').replace(/-/g, '_').replace(/\./g, '_').toUpperCase();
    }
    
    return "UNKNOWN_SOURCE";
}

function toKotatsuUrl(tySource, tyUrl) {
    // Common URL cleanups for Kotatsu format
    if (tySource === "MangaDex") return tyUrl.replace("/manga/", "").replace("/title/", "");
    if (tySource === "Mangakakalot") return tyUrl.replace("https://chapmanganato.to/", "/manga/");
    if (tySource === "Comick") return tyUrl.replace("/comic/", "");
    if (tySource === "Bato.to") return tyUrl.replace("/series/", "").replace("/title/", "");
    return tyUrl;
}

const cleanStr = (s) => (s && (typeof s === 'string' || typeof s === 'number')) ? String(s) : "";

// --- 🧠 AI MATCHING ENGINE ---
function findTachiyomiSourceId(kotatsuSource, mangaUrl) {
    const raw = cleanStr(kotatsuSource);
    if (!raw && !mangaUrl) return { id: "0", name: "Local" };
    
    // 1. Direct Knowledge Base Check (Enum Match)
    if (KOTATSU_TO_TACHI_MAP[raw]) {
        const id = KOTATSU_TO_TACHI_MAP[raw];
        return { id, name: ID_TO_NAME[id] || raw };
    }

    // 2. Domain Extraction (The "Silver Bullet")
    if (mangaUrl) {
        try {
            const hostname = new URL(mangaUrl).hostname.replace("www.", "");
            // Exact Domain Match
            if (DOMAIN_TO_ID[hostname]) {
                const id = DOMAIN_TO_ID[hostname];
                console.log(`🌐 Domain Match: ${hostname} -> ${ID_TO_NAME[id]}`);
                return { id, name: ID_TO_NAME[id] };
            }
            // Subdomain/Partial fuzzy check
            for (const [key, val] of Object.entries(DOMAIN_TO_ID)) {
                if (hostname.includes(key)) {
                    console.log(`🌐 Sub-Domain Match: ${hostname} -> ${ID_TO_NAME[val]}`);
                    return { id: val, name: ID_TO_NAME[val] };
                }
            }
        } catch (e) { /* Invalid URL, ignore */ }
    }

    const rawSan = sanitize(raw);

    // 3. Sanitized Name Match (strips 'scans', 'comics', etc)
    if (SANITIZED_TO_ID[rawSan]) {
        const id = SANITIZED_TO_ID[rawSan];
        console.log(`✨ Sanitized Match: ${raw} -> ${ID_TO_NAME[id]}`);
        return { id, name: ID_TO_NAME[id] };
    }

    // 4. Fuzzy Match (Weighted Levenshtein)
    let bestMatch = null;
    let maxScore = 0;
    
    for (const src of KNOWN_SOURCES) {
        let score = 0;
        const srcSan = src.sanitized;
        
        if (srcSan === rawSan) score += 100;
        else if (srcSan.includes(rawSan) || rawSan.includes(srcSan)) score += 30;
        
        const dist = levenshtein(rawSan, srcSan);
        const maxLen = Math.max(rawSan.length, srcSan.length);
        const sim = 1 - (dist / maxLen);
        score += sim * 70; 
        
        if (score > maxScore) {
            maxScore = score;
            bestMatch = src;
        }
    }

    if (bestMatch && maxScore > 65) {
        console.log(`🤖 AI Fuzzy Match: ${raw} -> ${bestMatch.name} (${maxScore.toFixed(0)}%)`);
        return { id: bestMatch.id, name: bestMatch.name };
    }

    console.warn(`⚠️ Unknown Source: ${raw} (URL: ${mangaUrl}). Using Hash Fallback.`);
    return { id: getSourceId(raw), name: raw };
}

// --- FALLBACK HELPERS ---
function getSourceId(sourceName) {
    if (!sourceName) return "0";
    const lower = sourceName.toLowerCase();
    if (NAME_TO_ID[lower]) return NAME_TO_ID[lower];
    
    // Generate deterministic hash for fallback
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

// --- Main Logic ---

async function main() {
  console.log('📦 Initializing Migration Kit (v8.2.0 Ultra-Stable)...');
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

async function kotatsuToTachiyomi(BackupMessage) {
    console.log('🔄 Mode: Kotatsu -> Tachiyomi');
    
    const zip = new AdmZip(KOTATSU_INPUT);
    const zipEntries = zip.getEntries();
    
    let favouritesData = null;
    let categoriesData = null;
    let historyData = null;

    // unzip logic
    for (const entry of zipEntries) {
        if (entry.isDirectory) continue;
        const name = entry.entryName;
        try {
            if (name.includes('favourites')) favouritesData = JSON.parse(entry.getData().toString('utf8'));
            else if (name.includes('categories')) categoriesData = JSON.parse(entry.getData().toString('utf8'));
            else if (name.includes('history')) historyData = JSON.parse(entry.getData().toString('utf8'));
        } catch(e) {}
    }

    if (!favouritesData) throw new Error("Invalid Kotatsu backup: Missing 'favourites' file.");

    const catIdMap = new Map();
    const backupCategories = [];
    if (categoriesData) {
        categoriesData.forEach((cat, idx) => {
            const name = cleanStr(cat.name);
            backupCategories.push({ name: name, order: cat.sortKey || idx, flags: 0 });
            catIdMap.set(cat.id, cat.sortKey || idx);
        });
    }

    const backupManga = [];
    const backupSources = [];
    const sourceSet = new Set();
    
    const historyMap = new Map(); 
    if (historyData) {
        historyData.forEach(h => {
             if(!historyMap.has(h.manga_id)) historyMap.set(h.manga_id, []);
             historyMap.get(h.manga_id).push(h);
        });
    }

    console.log(`📚 Processing ${favouritesData.length} favorites...`);

    favouritesData.forEach(fav => {
        const kManga = fav.manga;
        if (!kManga) return;

        // Use Source Name AND URL for matching
        const match = findTachiyomiSourceId(kManga.source, kManga.url || kManga.public_url);
        const tSourceId = match.id;
        const prettySourceName = match.name;

        if (!sourceSet.has(tSourceId)) {
            sourceSet.add(tSourceId);
            backupSources.push({ sourceId: tSourceId, name: prettySourceName });
        }

        const tachiChapters = [];
        if (kManga.chapters && Array.isArray(kManga.chapters)) {
             kManga.chapters.forEach(ch => {
                 tachiChapters.push({
                     url: cleanStr(ch.url),
                     name: cleanStr(ch.title || ch.name),
                     scanlator: "",
                     read: ch.read || false,
                     bookmark: 0,
                     lastPageRead: 0,
                     dateFetch: Date.now(),
                     dateUpload: ch.uploaded_at ? Number(ch.uploaded_at) : Date.now(),
                     chapterNumber: parseFloat(ch.number) || -1.0,
                     sourceOrder: 0
                 });
             });
        }
        
        const mangaHistory = historyMap.get(kManga.id) || [];
        let lastReadTime = 0;
        if (mangaHistory.length > 0) {
            mangaHistory.forEach(h => {
                const ts = Number(h.updated_at || h.created_at);
                if (ts > lastReadTime) lastReadTime = ts;
            });
        }
        
        const backupHistory = [];
        if (lastReadTime > 0) {
            backupHistory.push({
                url: cleanStr(kManga.url),
                lastRead: lastReadTime,
                readDuration: 0
            });
        }

        const cats = [];
        if (fav.category_id !== undefined && catIdMap.has(fav.category_id)) {
            cats.push(catIdMap.get(fav.category_id));
        }

        backupManga.push({
            source: tSourceId,
            url: cleanStr(kManga.url),
            title: cleanStr(kManga.title),
            artist: cleanStr(kManga.artist),
            author: cleanStr(kManga.author),
            description: cleanStr(kManga.description),
            genre: (Array.isArray(kManga.tags) ? kManga.tags : []).map(t => cleanStr(t)),
            status: kManga.state === "ONGOING" ? 1 : 2,
            thumbnailUrl: cleanStr(kManga.cover_url),
            dateAdded: Number(fav.created_at) || Date.now(),
            viewer: 0,
            chapters: tachiChapters,
            categories: cats,
            history: backupHistory
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
    console.log('🔄 Mode: Tachiyomi -> Kotatsu');
    
    const buffer = fs.readFileSync(TACHI_INPUT);
    const unzipped = zlib.gunzipSync(buffer);
    const message = BackupMessage.decode(unzipped);
    const tachiData = BackupMessage.toObject(message, { defaults: true, longs: String });

    const favorites = [];
    const history = [];

    const getSrcName = (id) => {
        if (tachiData.backupSources) {
            const s = tachiData.backupSources.find(x => String(x.sourceId) === String(id));
            if (s) return s.name;
        }
        const db = SOURCE_DB.find(x => x.tId === String(id));
        if (db) return db.name;
        return `Source ${id}`;
    };

    const mangaList = tachiData.backupManga || [];
    console.log(`📚 Processing ${mangaList.length} manga...`);

    mangaList.forEach((tm, i) => {
        const tySource = cleanStr(getSrcName(tm.source));
        // Use URL for prediction as well
        const kSource = predictKotatsuSourceName(tySource, tm.source, tm.url);
        
        const kUrl = toKotatsuUrl(tySource, cleanStr(tm.url));
        const kId = getKotatsuId(kSource + kUrl); 
        const kPublicUrl = "https://google.com/search?q=" + encodeURIComponent(tm.title); 
        
        let kStatus = "ONGOING";
        if (tm.status === 2) kStatus = "FINISHED";

        const kManga = {
            id: kId,
            title: cleanStr(tm.title),
            alt_title: null,
            url: kUrl,
            public_url: kPublicUrl,
            rating: 0.0,
            nsfw: false,
            cover_url: cleanStr(tm.thumbnailUrl),
            large_cover_url: null,
            state: kStatus,
            author: cleanStr(tm.author),
            source: kSource,
            tags: (tm.genre || []).map(t => cleanStr(t))
        };

        const kFav = {
            manga_id: kId,
            category_id: (tm.categories && tm.categories.length > 0) ? (tm.categories[0] + 1) : 0,
            sort_key: 0,
            created_at: Number(tm.dateAdded),
            deleted_at: 0,
            manga: kManga
        };
        favorites.push(kFav);

        // HISTORY MIGRATION
        if (tm.chapters && tm.chapters.length > 0) {
            let latestRead = null;
            let maxChapNum = 0;
            
            tm.chapters.forEach(ch => {
               if (ch.chapterNumber > maxChapNum) maxChapNum = ch.chapterNumber;
               if (ch.read && (!latestRead || ch.chapterNumber > latestRead.chapterNumber)) {
                   latestRead = ch;
               }
            });

            if (latestRead) {
                const percent = (maxChapNum > 0) ? (latestRead.chapterNumber / maxChapNum) : 0;
                
                history.push({
                    manga_id: kId,
                    created_at: Number(tm.dateAdded),
                    updated_at: Number(latestRead.dateFetch || Date.now()),
                    chapter_id: getKotatsuId(kSource + latestRead.url), 
                    page: latestRead.lastPageRead || 0,
                    scroll: 0,
                    percent: percent > 1 ? 1 : percent,
                    manga: kManga
                });
            }
        }
    });

    const zip = new AdmZip();
    const favJson = JSON.stringify(favorites); 
    const histJson = JSON.stringify(history);

    zip.addFile("favourites.json", Buffer.from(favJson, "utf8"));
    zip.addFile("history.json", Buffer.from(histJson, "utf8"));
    // Legacy support
    zip.addFile("favourites", Buffer.from(favJson, "utf8"));
    zip.addFile("history", Buffer.from(histJson, "utf8"));
    
    const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
    zip.writeZip(outFile);
    console.log(`✅ Success! Created: ${outFile}`);
}

main().catch(err => {
  console.error('❌ FATAL ERROR:', err);
  process.exit(1);
});
