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

// --- Live Repos ---
const KEIYOUSHI_URL = 'https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json';
// V21 FIX: Use 'base' branch and check specific parsers path
const DOKI_TREE_API = 'https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1';

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// --- Brain 🧠: Global Maps ---
// Keiyoushi Data
const TACHI_ID_MAP = {}; // ID -> { name, domain }
const TACHI_DOMAIN_MAP = {}; // domain -> { id, name }
// Doki Data
const DOKI_CLASSES = []; // Array of class names e.g. "MangaDex" (from MangaDex.kt)
const DOKI_LOWER_MAP = {}; // lowerName -> realName

const ID_SEED = 1125899906842597n; 

// --- Network Helpers ---
async function fetchJson(url) {
    return new Promise((resolve) => {
        const opts = { headers: { 'User-Agent': 'NodeJS-Bridge-v21' } };
        if (process.env.GH_TOKEN && url.includes('github.com')) opts.headers['Authorization'] = `Bearer ${process.env.GH_TOKEN}`;
        https.get(url, opts, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve(null); } });
        }).on('error', () => resolve(null));
    });
}

// --- Live Brain Loading ---
async function loadBridgeData() {
    console.log("🌐 [Bridge] Connecting to Keiyoushi & Doki Repos...");
    
    // 1. Fetch Keiyoushi
    const kData = await fetchJson(KEIYOUSHI_URL);
    if (Array.isArray(kData)) {
        kData.forEach(ext => {
           if(ext.sources) ext.sources.forEach(s => {
               const dom = getDomain(s.baseUrl);
               const entry = { id: String(s.id), name: s.name, domain: dom };
               TACHI_ID_MAP[String(s.id)] = entry;
               if(dom) TACHI_DOMAIN_MAP[dom] = entry;
               if(s.name.startsWith("Tachiyomi: ")) {
                   TACHI_DOMAIN_MAP[s.name.replace("Tachiyomi: ", "").toLowerCase()] = entry;
               }
           });
        });
        console.log(`✅ [Bridge] Loaded ${Object.keys(TACHI_ID_MAP).length} Tachiyomi sources.`);
    } else {
        console.warn("⚠️ [Bridge] Failed to load Keiyoushi index.");
    }

    // 2. Fetch Doki File List via Tree API (Fixes "Indexed 0" issue - now uses 'base' branch)
    const dData = await fetchJson(DOKI_TREE_API);
    if (dData && Array.isArray(dData.tree)) {
        dData.tree.forEach(node => {
            // V21 FIX: Target the specific site parsers directory
            if (node.path.endsWith('.kt') && node.path.includes('parsers/site')) {
                const filename = path.basename(node.path, '.kt');
                // Exclude generic factories
                if (filename !== 'SiteParser') {
                    DOKI_CLASSES.push(filename);
                    DOKI_LOWER_MAP[filename.toLowerCase()] = filename;
                }
            }
        });
        console.log(`✅ [Bridge] Indexed ${DOKI_CLASSES.length} Kotatsu parsers from Git Tree (base).`);
    } else {
        console.warn("⚠️ [Bridge] Failed to load Doki Tree. Using Fallbacks.");
        // Emergency Fallbacks
        ["MangaDex", "Manganato", "BatoTo", "AsuraScans", "FlameComics"].forEach(f => {
             DOKI_CLASSES.push(f);
             DOKI_LOWER_MAP[f.toLowerCase()] = f;
        });
    }
}

// --- Logic: Domain & ID ---
function getDomain(url) {
    try {
        if(!url) return null;
        let u = url;
        if(!u.startsWith('http')) u = 'https://' + u;
        return new URL(u).hostname.replace(/^www\./, '').replace(/^m\./, '').replace(/^v\d+\./, '');
    } catch { return null; }
}

function getKotatsuId(str) {
    let h = ID_SEED;
    for (let i = 0; i < str.length; i++) {
        h = (31n * h + BigInt(str.charCodeAt(i)));
        h = BigInt.asIntN(64, h); 
    }
    return h;
}

// --- "Smart AI" Token Matcher ---
// Extracts "Core" tokens: "Asura Scans" -> "asura", "Mangakakalot" -> "mangakakalot"
function getCoreIdentity(name) {
    if (!name) return "";
    return name.toLowerCase()
        .replace(/\b(scans?|comics?|toon|manga|webtoon|fansub|team|group)\b/g, '') // Remove noise
        .replace(/[^a-z0-9]/g, '') // Remove symbols
        .trim();
}

// KOTATSU ➔ TACHIYOMI LOGIC
function resolveToTachiyomi(kName, kUrl) {
    // 1. Domain Match (The Gold Standard)
    const domain = getDomain(kUrl);
    if (domain && TACHI_DOMAIN_MAP[domain]) {
        return TACHI_DOMAIN_MAP[domain].id;
    }

    // 2. Exact Name Match
    for (const id in TACHI_ID_MAP) {
        if (TACHI_ID_MAP[id].name.toLowerCase() === kName.toLowerCase()) return id;
    }

    // 3. AI Token Match
    // e.g. Kotatsu: "Asura Scans", Tachiyomi: "Asura Toon" -> Both core: "asura"
    const kCore = getCoreIdentity(kName);
    if (kCore.length > 2) { // Only fuzzy match if core is substantive
        for (const id in TACHI_ID_MAP) {
            const tCore = getCoreIdentity(TACHI_ID_MAP[id].name);
            if (tCore === kCore) {
                console.log(`🤖 [AI Match] "${kName}" matches "${TACHI_ID_MAP[id].name}"`);
                return id;
            }
        }
    }

    // 4. Fallback Hash
    let hash = 0n;
    for (let i = 0; i < kName.length; i++) {
        hash = (31n * hash + BigInt(kName.charCodeAt(i))) & 0xFFFFFFFFFFFFFFFFn;
    }
    return hash.toString();
}

// TACHIYOMI ➔ KOTATSU LOGIC
function resolveToKotatsuKey(tId, tName, tUrl) {
    const domain = getDomain(tUrl);
    
    // 1. Hard Overrides
    if (tName === "MangaDex") return "MANGADEX";
    if (domain === "mangakakalot.com" || domain === "manganato.com") return "MANGANATO";

    // 2. Domain -> Doki Class Match
    // If Doki has "MangaDex.kt" and domain is "mangadex.org", we can try to guess
    // but Doki doesn't give us domains easily without reading files.
    // So we rely on Name matching mostly.

    // 3. AI Token Match against Doki Classes
    // e.g. Tachi: "AsuraToon" -> Core: "asura"
    // Doki: "AsuraScans" -> Core: "asura" -> Match!
    const tCore = getCoreIdentity(tName);
    
    // Direct lookup first
    if (DOKI_LOWER_MAP[tName.toLowerCase()]) {
        return convertClassToConstant(DOKI_LOWER_MAP[tName.toLowerCase()]);
    }

    // Fuzzy Token lookup
    if (tCore.length > 2) {
        for (const cls of DOKI_CLASSES) {
            const dCore = getCoreIdentity(cls);
            if (dCore === tCore) {
                console.log(`🤖 [AI Match] Tachi "${tName}" -> Doki "${cls}"`);
                return convertClassToConstant(cls);
            }
        }
    }

    // 4. Last Resort: Transform Tachi Name directly
    return convertClassToConstant(tName);
}

function convertClassToConstant(className) {
    // CamelCase -> CONSTANT_CASE
    // AsuraScans -> ASURA_SCANS
    return className.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase().replace(/[^A-Z0-9_]/g, "_");
}

// --- JSON BigInt Serializer ---
function stringifyWithBigInt(obj) {
    const placeholderPrefix = "BIGINT::";
    const json = JSON.stringify(obj, (key, value) => {
        if (typeof value === 'bigint') return placeholderPrefix + value.toString();
        return value;
    });
    return json.replace(new RegExp('"' + placeholderPrefix + '(-?\\d+)"', 'g'), '$1');
}

const cleanStr = (s) => (s && (typeof s === 'string' || typeof s === 'number')) ? String(s) : "";

// --- MAIN ---

async function main() {
    console.log('📦 Initializing Migration Kit (v21.0 True Bridge)...');
    await loadBridgeData();

    console.log('📖 Loading Protobuf Schema...');
    const root = await protobuf.load(PROTO_FILE);
    const BackupMessage = root.lookupType("tachiyomi.Backup");

    if (fs.existsSync(KOTATSU_INPUT)) {
        await kotatsuToTachiyomi(BackupMessage);
    } else if (fs.existsSync(TACHI_INPUT)) {
        await tachiyomiToKotatsu(BackupMessage);
    } else {
        throw new Error('❌ No backup file found!');
    }
}

async function kotatsuToTachiyomi(BackupMessage) {
    console.log('🔄 Mode: Kotatsu -> Tachiyomi');
    const zip = new AdmZip(KOTATSU_INPUT);
    let favouritesData = null;
    let categoriesData = null;
    let historyData = null;

    zip.getEntries().forEach(e => {
        const n = e.name;
        // Handle both strict (v21) and legacy formats
        if(n === 'favourites' || n === 'favourites.json') favouritesData = JSON.parse(e.getData().toString('utf8'));
        if(n === 'categories' || n === 'categories.json') categoriesData = JSON.parse(e.getData().toString('utf8'));
        if(n === 'history' || n === 'history.json') historyData = JSON.parse(e.getData().toString('utf8'));
    });

    if(!favouritesData) throw new Error("Invalid Backup: Missing favourites");

    const catIdMap = new Map();
    const backupCategories = (categoriesData || []).map((c, i) => {
        catIdMap.set(c.id, c.sortKey || i);
        return { name: cleanStr(c.name), order: c.sortKey || i, flags: 0 };
    });

    const historyMap = new Map();
    if(historyData) historyData.forEach(h => historyMap.set(h.mangaId || h.manga_id, h));

    const backupManga = [];
    const backupSources = [];
    const sourceSet = new Set();

    favouritesData.forEach(fav => {
        const kManga = fav.manga;
        if(!kManga) return;

        // --- BRIDGE CALL ---
        const tSourceId = resolveToTachiyomi(kManga.source, kManga.url || kManga.public_url);
        // -------------------

        if (!sourceSet.has(tSourceId)) {
            sourceSet.add(tSourceId);
            const sName = TACHI_ID_MAP[tSourceId] ? TACHI_ID_MAP[tSourceId].name : kManga.source;
            backupSources.push({ sourceId: tSourceId, name: sName });
        }

        const h = historyMap.get(kManga.id);
        const historyList = h ? [{
            url: cleanStr(kManga.url),
            lastRead: Number(h.updated_at || h.created_at) || Date.now(),
            readDuration: 0
        }] : [];

        const cats = (fav.category_id !== undefined && catIdMap.has(fav.category_id)) ? [catIdMap.get(fav.category_id)] : [];

        backupManga.push({
            source: tSourceId,
            url: cleanStr(kManga.url),
            title: cleanStr(kManga.title),
            artist: cleanStr(kManga.artist),
            author: cleanStr(kManga.author),
            description: cleanStr(kManga.description),
            genre: (kManga.tags || []).map(t => cleanStr(t)),
            status: kManga.state === "ONGOING" ? 1 : 2,
            thumbnailUrl: cleanStr(kManga.cover_url),
            dateAdded: Number(fav.created_at) || Date.now(),
            chapters: [],
            categories: cats,
            history: historyList
        });
    });

    const payload = { backupManga, backupCategories, backupSources };
    const message = BackupMessage.create(payload);
    const buffer = BackupMessage.encode(message).finish();
    const gzipped = zlib.gzipSync(buffer);
    
    // Explicit Naming
    fs.writeFileSync(path.join(OUTPUT_DIR, 'Backup.tachibk'), gzipped);
    console.log('✅ Created output/Backup.tachibk');
}

async function tachiyomiToKotatsu(BackupMessage) {
    console.log('🔄 Mode: Tachiyomi -> Kotatsu');
    const buffer = fs.readFileSync(TACHI_INPUT);
    const message = BackupMessage.decode(zlib.gunzipSync(buffer));
    const tachiData = BackupMessage.toObject(message, { defaults: true, longs: String });

    const favorites = [];
    const history = [];
    const categories = (tachiData.backupCategories || []).map((c, i) => ({
        id: i + 1,
        name: c.name,
        sortKey: c.order || i,
        sortOrder: "ASC",
        hidden: false
    }));

    const getSrcInfo = (id) => {
        const s = (tachiData.backupSources || []).find(x => String(x.sourceId) === String(id));
        return s ? s.name : ("Source " + id);
    };

    (tachiData.backupManga || []).forEach(tm => {
        const tName = getSrcInfo(tm.source);
        
        // --- BRIDGE CALL ---
        const kSourceKey = resolveToKotatsuKey(String(tm.source), tName, tm.url);
        // -------------------

        // Clean URL
        let kUrl = tm.url;
        // Basic normalization if needed
        if(kSourceKey === "MANGADEX") kUrl = kUrl.replace("/title/", "").replace("/manga/", "");

        const kId = getKotatsuId(kSourceKey + kUrl);

        const kManga = {
            id: kId, // BigInt
            title: cleanStr(tm.title),
            url: kUrl,
            public_url: null, 
            source: kSourceKey,
            state: tm.status === 2 ? "FINISHED" : "ONGOING",
            cover_url: cleanStr(tm.thumbnailUrl),
            tags: tm.genre || [],
            author: cleanStr(tm.author)
        };

        const catIdx = (tm.categories && tm.categories.length > 0) ? tm.categories[0] : -1;
        const catId = (catIdx >= 0) ? (catIdx + 1) : 0;

        favorites.push({
            manga_id: kId, // BigInt
            category_id: catId,
            sort_key: 0,
            created_at: Number(tm.dateAdded),
            manga: kManga
        });

        // History
        if (tm.chapters) {
             let latest = null;
             tm.chapters.forEach(ch => { if(ch.read && (!latest || ch.chapterNumber > latest.chapterNumber)) latest = ch; });
             if (latest) {
                 const chId = getKotatsuId(kSourceKey + latest.url);
                 history.push({
                     manga_id: kId,
                     chapter_id: chId,
                     created_at: Number(tm.dateAdded),
                     updated_at: Number(latest.dateFetch || Date.now()),
                     page: latest.lastPageRead || 0,
                     scroll: 0,
                     percent: 0,
                     manga: kManga
                 });
             }
        }
    });

    const zip = new AdmZip();
    // 1. Strict File Names (No Extension) & BigInt JSON
    zip.addFile("favourites", Buffer.from(stringifyWithBigInt(favorites), "utf8"));
    zip.addFile("history", Buffer.from(stringifyWithBigInt(history), "utf8"));
    zip.addFile("categories", Buffer.from(JSON.stringify(categories), "utf8"));
    
    // 2. Full 11-file suite
    const emptyArr = Buffer.from("[]", "utf8");
    const emptyObj = Buffer.from("{}", "utf8");
    ["bookmarks", "sources", "saved_filters"].forEach(n => zip.addFile(n, emptyArr));
    ["reader_grid", "scrobbling", "settings", "statistics"].forEach(n => zip.addFile(n, emptyObj));

    // 3. Metadata
    zip.addFile("index", Buffer.from(JSON.stringify({ version: 2, created_at: Date.now(), app_version: "2025.01.01" }), "utf8"));

    zip.writeZip(path.join(OUTPUT_DIR, 'Backup.zip'));
    console.log('✅ Created output/Backup.zip');
}

main().catch(e => { console.error(e); process.exit(1); });
               
