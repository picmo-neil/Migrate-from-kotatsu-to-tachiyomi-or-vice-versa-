const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');
const protobuf = require('protobufjs');
const zlib = require('zlib');

// --- Configuration ---
const KOTATSU_INPUT = 'Backup.zip';
const TACHI_INPUT = 'Backup.tachibk';
const OUTPUT_DIR = 'output';
const PROTO_FILE = path.join(__dirname, 'schema.proto');

// API ENDPOINTS
const KEIYOUSHI_URL = 'https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json';
const KOTATSU_REPO_API = 'https://api.github.com/repos/DokiTeam/doki-exts/contents/src/main/kotlin/org/dokiteam/doki/parsers/site';

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// ==========================================
// 🧠 REPO BRIDGE ARCHITECTURE (v17.0)
// ==========================================

// [REGISTRY 1] KOTATSU / DOKI
// Populated via Live GitHub Fetch + Static Fallback
const KOTATSU_REGISTRY = {
    // Static Fallbacks for Critical Sources (in case fetching fails)
    "MANGADEX": "mangadex.org",
    "MANGA_SEE": "mangasee123.com",
    "MANGA_LIFE": "mangalife.us",
    "BATO_TO": "bato.to",
    "WEBTOONS": "webtoons.com",
    "MANGANATO": "manganato.com",
    "MANGAKAKALOTTV": "mangakakalot.com",
    "ASURA_SCANS": "asuratoon.com",
    "FLAME_COMICS": "flamecomics.com",
    "REAPER_SCANS": "reaperscans.com",
    "TCB_SCANS": "tcbscans.com"
};

// [REGISTRY 2] KEIYOUSHI / TACHIYOMI
// Populated via Live JSON Fetch + Static Fallback
const KEIYOUSHI_REGISTRY = {
    "mangadex.org": "2499283573021220255",
    "mangasee123.com": "2973143899120668045",
    "bato.to": "8985172093557431221",
    "manganato.com": "1024627298672457456",
    "asuratoon.com": "6335003343669033128"
};

const TACHI_NAMES = {}; // Map ID -> Readable Name
const ID_SEED = 1125899906842597n; 

// --- Utilities ---

function getDomain(url) {
    try {
        let u = url;
        if (!u || typeof u !== 'string') return null;
        if (!u.startsWith('http')) u = 'https://' + u;
        return new URL(u).hostname.replace(/^www\./, '').replace(/^m\./, '').replace(/^v\d+\./, '');
    } catch(e) { return null; }
}

function getKotatsuId(str) {
    let h = ID_SEED;
    for (let i = 0; i < str.length; i++) {
        h = (31n * h + BigInt(str.charCodeAt(i)));
        h = BigInt.asIntN(64, h); 
    }
    return h;
}

const cleanStr = (s) => (s && (typeof s === 'string' || typeof s === 'number')) ? String(s) : "";

// Wrapper for Node 20 Native Fetch
async function fetchUrl(url, isJson = true) {
    const headers = { 'User-Agent': 'Node.js-Script' };
    if (process.env.GH_TOKEN && url.includes('api.github.com')) {
        headers['Authorization'] = `Bearer ${process.env.GH_TOKEN}`;
    }

    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.statusText}`);
    return isJson ? await res.json() : await res.text();
}

// --- 🌐 LIVE REPO ANALYZERS ---

async function analyzeKotatsuRepo() {
    console.log('📡 Accessing Doki/Kotatsu GitHub Repository...');
    try {
        // 1. Fetch File List
        const files = await fetchUrl(KOTATSU_REPO_API, true);
        if (!Array.isArray(files)) throw new Error("Invalid API response");

        console.log(`🔍 Found ${files.length} parsers in Doki Repo. Scanning contents...`);
        
        // 2. Scan Files (Batch processing to be polite)
        let scanned = 0;
        const batchSize = 10;
        
        // Use RegExp constructor to avoid slash escaping issues in generated code
        // Triple/Quadruple escape is needed here because this string is inside another string.
        const nameRegex = new RegExp('override\\s+val\\s+name\\s*=\\s*"([^"]+)"');
        const urlRegex = new RegExp('override\\s+val\\s+baseUrl\\s*=\\s*"([^"]+)"');
        const superRegex = new RegExp('super\\(\\s*"([^"]+)"');
        const simpleUrlRegex = new RegExp('"(https?://[^"]+)"');

        for (let i = 0; i < files.length; i += batchSize) {
            const batch = files.slice(i, i + batchSize);
            await Promise.all(batch.map(async (file) => {
                if (!file.name.endsWith('.kt')) return;
                try {
                    // Fetch Raw Kotlin Content
                    const code = await fetchUrl(file.download_url, false);
                    
                    let name = null;
                    let url = null;

                    const nameMatch = code.match(nameRegex) || code.match(superRegex);
                    const urlMatch = code.match(urlRegex) || code.match(simpleUrlRegex);

                    if (nameMatch) name = nameMatch[1];
                    if (urlMatch) url = urlMatch[1];

                    if (name && url) {
                        const domain = getDomain(url);
                        if (domain) {
                            KOTATSU_REGISTRY[name] = domain;
                            // Add UPPER_CASE_KEY variant for safety
                            const key = name.toUpperCase().replace(/[^A-Z0-9]/g, "_");
                            KOTATSU_REGISTRY[key] = domain;
                            scanned++;
                        }
                    }
                } catch (e) { /* Ignore individual file errors */ }
            }));
        }
        console.log(`✅ Kotatsu Bridge: Learned ${scanned} sources from Live Source Code.`);
    } catch (e) {
        console.warn('⚠️ Kotatsu Live Fetch Failed (Rate Limit/Offline). Using Static Fallback.', e.message);
    }
}

async function analyzeKeiyoushiRepo() {
    console.log('📡 Accessing Keiyoushi Extension Index...');
    try {
        const json = await fetchUrl(KEIYOUSHI_URL, true);
        let added = 0;
        json.forEach(ext => {
            if (ext.lang !== "en" && ext.lang !== "all") return;
            if (!ext.sources) return;
            ext.sources.forEach(src => {
                const id = String(src.id);
                TACHI_NAMES[id] = src.name;
                if (src.baseUrl) {
                    const dom = getDomain(src.baseUrl);
                    if (dom) {
                        KEIYOUSHI_REGISTRY[dom] = id;
                        added++;
                    }
                }
            });
        });
        console.log(`✅ Tachiyomi Bridge: Learned ${added} domains from Live Index.`);
    } catch (e) {
        console.warn('⚠️ Tachiyomi Live Fetch Failed. Using Static Fallback.');
    }
}

// --- 🌉 BRIDGE LOGIC ---

// 1. KOTATSU -> TACHIYOMI
function resolveKotatsuToTachiyomi(kotatsuName, publicUrl) {
    let domain = null;
    if (KOTATSU_REGISTRY[kotatsuName]) domain = KOTATSU_REGISTRY[kotatsuName];
    else if (publicUrl) domain = getDomain(publicUrl);

    if (!domain) return { id: getKotatsuId(kotatsuName).toString(), name: kotatsuName };

    if (KEIYOUSHI_REGISTRY[domain]) {
        const tId = KEIYOUSHI_REGISTRY[domain];
        const tName = TACHI_NAMES[tId] || kotatsuName;
        return { id: tId, name: tName };
    }

    return { id: getKotatsuId(kotatsuName).toString(), name: kotatsuName };
}

// 2. TACHIYOMI -> KOTATSU
function resolveTachiyomiToKotatsu(tachiId, tachiName, url) {
    const tId = String(tachiId);
    let domain = null;

    // A. Reverse Lookup Domain via Keiyoushi Registry
    for (const [dom, id] of Object.entries(KEIYOUSHI_REGISTRY)) {
        if (id === tId) {
            domain = dom;
            break;
        }
    }
    if (!domain && url) domain = getDomain(url);

    // B. Bridge Crossing to Kotatsu
    if (domain) {
        // Search Kotatsu Registry for this domain
        for (const [kName, domVal] of Object.entries(KOTATSU_REGISTRY)) {
            if (domVal === domain) return kName; 
        }
        
        // Smart Reconstruction: Generate valid key if not found in scraper
        return domain.split('.')[0].toUpperCase().replace(/[^A-Z0-9]/g, "_");
    }

    return tachiName.toUpperCase().replace(/[^A-Z0-9]/g, "_");
}

// --- MAIN PROCESS ---

async function main() {
    console.log('📦 Initializing Repo Bridge Engine (v17.0)...');
    
    // Parallel Repo Analysis
    await Promise.all([analyzeKeiyoushiRepo(), analyzeKotatsuRepo()]);

    console.log('📖 Loading Protobuf Schema...');
    const root = await protobuf.load(PROTO_FILE);
    const BackupMessage = root.lookupType("tachiyomi.Backup");

    if (fs.existsSync(KOTATSU_INPUT)) {
        await kotatsuToTachiyomi(BackupMessage);
    } else if (fs.existsSync(TACHI_INPUT)) {
        await tachiyomiToKotatsu(BackupMessage);
    } else {
        throw new Error('❌ No backup file found! Please add Backup.zip or Backup.tachibk.');
    }
}

async function kotatsuToTachiyomi(BackupMessage) {
    console.log('🔄 Direction: Kotatsu -> Tachiyomi');
    const zip = new AdmZip(KOTATSU_INPUT);
    
    let favouritesData = null, categoriesData = null, historyData = null;
    zip.getEntries().forEach(e => {
        // Strict but backward compatible check for Kotatsu filenames
        if(e.name === 'favourites' || e.name === 'favourites.json') favouritesData = JSON.parse(e.getData().toString('utf8'));
        if(e.name === 'categories' || e.name === 'categories.json') categoriesData = JSON.parse(e.getData().toString('utf8'));
        if(e.name === 'history' || e.name === 'history.json') historyData = JSON.parse(e.getData().toString('utf8'));
    });

    if(!favouritesData) throw new Error("Invalid Kotatsu Backup: Missing favourites data");

    const backupCategories = (categoriesData || []).map((c, i) => ({
        name: c.name, order: c.sortKey || i, flags: 0
    }));

    const backupManga = [];
    const backupSources = [];
    const sourceSet = new Set();
    const historyMap = new Map();
    
    if(historyData) historyData.forEach(h => {
        if(!historyMap.has(h.manga_id)) historyMap.set(h.manga_id, []);
        historyMap.get(h.manga_id).push(h);
    });

    favouritesData.forEach(fav => {
        const kManga = fav.manga;
        if (!kManga) return;

        const match = resolveKotatsuToTachiyomi(kManga.source, kManga.public_url || kManga.url);
        
        if (!sourceSet.has(match.id)) {
            sourceSet.add(match.id);
            backupSources.push({ sourceId: match.id, name: match.name });
        }

        const tachiChapters = (kManga.chapters || []).map(ch => ({
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
        }));

        let lastRead = 0;
        const hList = historyMap.get(kManga.id) || [];
        hList.forEach(h => {
            const t = Number(h.updated_at || h.created_at);
            if(t > lastRead) lastRead = t;
        });

        backupManga.push({
            source: match.id,
            url: cleanStr(kManga.url),
            title: cleanStr(kManga.title),
            artist: cleanStr(kManga.artist),
            author: cleanStr(kManga.author),
            description: cleanStr(kManga.description),
            genre: (kManga.tags || []).map(t => cleanStr(t)),
            status: kManga.state === "ONGOING" ? 1 : 2,
            thumbnailUrl: cleanStr(kManga.cover_url),
            dateAdded: Number(fav.created_at),
            chapters: tachiChapters,
            categories: fav.category_id ? [fav.category_id] : [],
            history: lastRead ? [{ url: cleanStr(kManga.url), lastRead, readDuration: 0 }] : []
        });
    });

    const payload = { backupManga, backupCategories, backupSources };
    const message = BackupMessage.create(payload);
    const buffer = BackupMessage.encode(message).finish();
    const gzipped = zlib.gzipSync(buffer);
    fs.writeFileSync(path.join(OUTPUT_DIR, 'converted_tachiyomi.tachibk'), gzipped);
    console.log('✅ Success! Created converted_tachiyomi.tachibk');
}

async function tachiyomiToKotatsu(BackupMessage) {
    console.log('🔄 Direction: Tachiyomi -> Kotatsu');
    const buffer = fs.readFileSync(TACHI_INPUT);
    const message = BackupMessage.decode(zlib.gunzipSync(buffer));
    const tachiData = BackupMessage.toObject(message, { defaults: true, longs: String });

    const favorites = [];
    const history = [];
    const categories = [];

    // Map Categories
    if (tachiData.backupCategories) {
        tachiData.backupCategories.forEach((c, idx) => {
            categories.push({
                id: idx + 1, // Kotatsu categories need IDs
                name: c.name,
                sortKey: c.order || idx,
                sortOrder: "ASC",
                hidden: false
            });
        });
    }

    (tachiData.backupManga || []).forEach(tm => {
        let name = "Source";
        if (tachiData.backupSources) {
            const s = tachiData.backupSources.find(x => String(x.sourceId) === String(tm.source));
            if (s) name = s.name;
        }

        const kSource = resolveTachiyomiToKotatsu(tm.source, name, tm.url);
        const kUrl = cleanStr(tm.url); 
        const kId = getKotatsuId(kSource + kUrl);
        
        let domain = null;
        if (KOTATSU_REGISTRY[kSource]) domain = KOTATSU_REGISTRY[kSource];
        else if (tm.url) domain = getDomain(tm.url);

        const publicUrl = domain ? `https://${domain}${kUrl}` : null;

        // Map Category ID
        let catId = 0;
        if (tm.categories && tm.categories.length > 0 && categories.length > 0) {
            catId = 0; // Defaulting to Uncategorized if complexity matches fail
        }

        favorites.push({
            manga_id: kId,
            category_id: catId,
            sort_key: 0,
            created_at: Number(tm.dateAdded),
            manga: {
                id: kId,
                title: cleanStr(tm.title),
                url: kUrl,
                public_url: publicUrl,
                source: kSource,
                state: tm.status === 2 ? "FINISHED" : "ONGOING",
                cover_url: cleanStr(tm.thumbnailUrl),
                tags: tm.genre || [],
                chapters: [] 
            }
        });

        if (tm.chapters) {
             let lastReadChap = null;
             tm.chapters.forEach(ch => {
                 if (ch.read) {
                    if (!lastReadChap || (ch.chapterNumber > lastReadChap.chapterNumber)) {
                        lastReadChap = ch;
                    }
                 }
             });

             if (lastReadChap) {
                 const chapId = getKotatsuId(kSource + lastReadChap.url);
                 history.push({
                     manga_id: kId,
                     created_at: Number(tm.dateAdded),
                     updated_at: Number(lastReadChap.dateFetch || Date.now()),
                     chapter_id: chapId, 
                     page: lastReadChap.lastPageRead || 0,
                     percent: 0,
                     scroll: 0
                 });
             }
        }
    });

    const zip = new AdmZip();
    
    // --- 1. Core Data (NO EXTENSIONS as per Kotatsu spec) ---
    zip.addFile("favourites", Buffer.from(JSON.stringify(favorites), "utf8"));
    zip.addFile("history", Buffer.from(JSON.stringify(history), "utf8"));
    zip.addFile("categories", Buffer.from(JSON.stringify(categories), "utf8"));
    
    // --- 2. Required Empty/Default Files ---
    zip.addFile("bookmarks", Buffer.from("[]", "utf8"));
    zip.addFile("reader_grid", Buffer.from("{}", "utf8"));
    zip.addFile("scrobbling", Buffer.from("{}", "utf8"));
    zip.addFile("settings", Buffer.from("{}", "utf8"));
    zip.addFile("sources", Buffer.from("[]", "utf8"));
    zip.addFile("statistics", Buffer.from("{}", "utf8"));
    zip.addFile("saved_filters", Buffer.from("[]", "utf8"));

    // --- 3. Index Metadata ---
    const indexData = {
        version: 2,
        created_at: Date.now(),
        app_version: "2025.01.01"
    };
    zip.addFile("index", Buffer.from(JSON.stringify(indexData), "utf8"));

    zip.writeZip(path.join(OUTPUT_DIR, 'converted_kotatsu.zip'));
    console.log('✅ Success! Created converted_kotatsu.zip with strict file structure (no .json extensions).');
}

main().catch(err => {
    console.error("❌ Fatal Error:", err);
    process.exit(1);
});
            
