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
const DOKI_REPO_API = 'https://api.github.com/repos/DokiTeam/doki-exts/contents/src/main/kotlin/org/dokiteam/doki/parsers/site';

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// --- Brain 🧠: Global Maps ---
// Keiyoushi Data
const TACHI_ID_MAP = {}; // ID -> { name, domain }
const TACHI_DOMAIN_MAP = {}; // domain -> { id, name }
// Doki Data
const DOKI_FILES = []; // Array of filenames e.g. "MangaDex.kt"

const ID_SEED = 1125899906842597n; 

// --- "AI" Levenshtein Implementation (Pure JS) ---
function levenshtein(a, b) {
  if (a.length === 0) return b.length; 
  if (b.length === 0) return a.length; 
  const matrix = [];
  for (let i = 0; i <= b.length; i++) { matrix[i] = [i]; }
  for (let j = 0; j <= a.length; j++) { matrix[0][j] = j; }
  for (let i = 1; i <= b.length; i++) {
    for (let j = 1; j <= a.length; j++) {
      if (b.charAt(i - 1) === a.charAt(j - 1)) {
        matrix[i][j] = matrix[i - 1][j - 1];
      } else {
        matrix[i][j] = Math.min(matrix[i - 1][j - 1] + 1, Math.min(matrix[i][j - 1] + 1, matrix[i - 1][j] + 1));
      }
    }
  }
  return matrix[b.length][a.length];
}

// --- Network Helpers ---
async function fetchJson(url) {
    return new Promise((resolve) => {
        const opts = { headers: { 'User-Agent': 'NodeJS-Bridge' } };
        if (process.env.GH_TOKEN && url.includes('github.com')) opts.headers['Authorization'] = `Bearer ${process.env.GH_TOKEN}`;
        https.get(url, opts, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => { try { resolve(JSON.parse(data)); } catch { resolve([]); } });
        }).on('error', () => resolve([]));
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
               // Handle "Tachiyomi: Name"
               if(s.name.startsWith("Tachiyomi: ")) {
                   TACHI_DOMAIN_MAP[s.name.replace("Tachiyomi: ", "").toLowerCase()] = entry;
               }
           });
        });
        console.log(`✅ [Bridge] Loaded ${Object.keys(TACHI_ID_MAP).length} Tachiyomi sources.`);
    }

    // 2. Fetch Doki File List (Lightweight scan)
    const dData = await fetchJson(DOKI_REPO_API);
    if (Array.isArray(dData)) {
        dData.forEach(f => {
            if(f.name.endsWith(".kt")) DOKI_FILES.push(f.name.replace(".kt", ""));
        });
        console.log(`✅ [Bridge] Indexed ${DOKI_FILES.length} Kotatsu parsers.`);
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

// --- "AI" Matching Logic ---

// K -> T
function findTachiyomiId(kotatsuName, mangaUrl) {
    // 1. Domain Match (Strongest)
    const domain = getDomain(mangaUrl);
    if (domain && TACHI_DOMAIN_MAP[domain]) {
        return TACHI_DOMAIN_MAP[domain].id;
    }

    // 2. Name Match (Exact)
    for (const id in TACHI_ID_MAP) {
        if (TACHI_ID_MAP[id].name.toLowerCase() === kotatsuName.toLowerCase()) return id;
    }

    // 3. AI Fuzzy Match
    let bestId = null;
    let minDist = 999;
    for (const id in TACHI_ID_MAP) {
        const dist = levenshtein(kotatsuName.toLowerCase(), TACHI_ID_MAP[id].name.toLowerCase());
        if (dist < minDist) {
            minDist = dist;
            bestId = id;
        }
    }
    // Only accept if very close (e.g. diff <= 3 chars)
    if (bestId && minDist <= 3) {
        console.log(`🤖 [AI Match] ${kotatsuName} -> ${TACHI_ID_MAP[bestId].name}`);
        return bestId;
    }

    // 4. Fallback Hash
    let hash = 0n;
    for (let i = 0; i < kotatsuName.length; i++) {
        hash = (31n * hash + BigInt(kotatsuName.charCodeAt(i))) & 0xFFFFFFFFFFFFFFFFn;
    }
    return hash.toString();
}

// T -> K
function findKotatsuKey(tachiId, tachiName, mangaUrl) {
    // 1. Domain Map to Doki File
    const domain = getDomain(mangaUrl);
    
    // Manual Overrides
    if (tachiName === "MangaDex") return "MANGADEX";
    if (domain === "mangakakalot.com" || domain === "manganato.com") return "MANGANATO";

    // 2. Try to match Domain to Doki Files
    // e.g. asuratoon.com -> AsuraScans.kt ??
    // Not perfect, so we rely on heuristic naming.
    
    // 3. AI Name Match against Doki Files
    let bestFile = null;
    let minDist = 999;
    const target = tachiName.replace(/s+/g, "");
    
    for (const f of DOKI_FILES) {
        const dist = levenshtein(target.toLowerCase(), f.toLowerCase());
        if (dist < minDist) {
            minDist = dist;
            bestFile = f;
        }
    }

    if (bestFile && minDist <= 3) {
        // Convert PascalCase/File to CONSTANT_CASE
        // e.g. AsuraScans -> ASURA_SCANS
        return bestFile.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase();
    }

    // 4. Default Fallback
    return tachiName.toUpperCase().replace(/\s+/g, '_').replace(/[^A-Z0-9_]/g, "");
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
    console.log('📦 Initializing Migration Kit (v19.0 Hybrid Bridge)...');
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
        const tSourceId = findTachiyomiId(kManga.source, kManga.url || kManga.public_url);
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
        const kSourceKey = findKotatsuKey(String(tm.source), tName, tm.url);
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
            public_url: null, // Let Kotatsu resolve
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
                 // Chapter ID Hash: Source + URL
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
                   
