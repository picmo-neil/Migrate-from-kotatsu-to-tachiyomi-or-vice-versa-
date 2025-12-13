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
// Using 'base' branch and strict path filter
const DOKI_TREE_API = 'https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1';

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// --- Brain 🧠: Global Maps ---
const TACHI_ID_MAP = {}; // ID (string) -> { name, domain }
const TACHI_DOMAIN_MAP = {}; // domain -> { id (string), name }
const DOKI_CLASSES = []; // "MangaDex", "AsuraScans"
const DOKI_LOWER_MAP = {}; // "mangadex" -> "MangaDex"

const ID_SEED = 1125899906842597n; 

// --- Overrides ---
const KOTATSU_OVERRIDES = {
    "MANGADEX": "MANGADEX",
    "MANGANATO": "MANGANATO",
    "BATOTO": "BATOTO",
    "BATO_TO": "BATOTO",
    "ASURA_SCANS": "ASURA_SCANS",
    "MANGAKAKALOT": "MANGAKAKALOT"
};

// --- Network Helpers ---
async function fetchJson(url, isKeiyoushi = false) {
    return new Promise((resolve) => {
        const opts = { headers: { 'User-Agent': 'NodeJS-Bridge-v24' } };
        // Correctly escaped template literal for GH Token
        if (process.env.GH_TOKEN && url.includes('github.com')) opts.headers['Authorization'] = `Bearer ${process.env.GH_TOKEN}`;
        https.get(url, opts, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => { 
                try { 
                    if (isKeiyoushi) {
                        // 💎 V24: JSON BigInt Patcher
                        // Prevents ID corruption: "id": 123 -> "id": "123"
                        const patchedData = data.replace(/"id":\s*([0-9]{15,})/g, '"id": "$1"');
                        resolve(JSON.parse(patchedData));
                    } else {
                        resolve(JSON.parse(data));
                    }
                } catch { resolve(null); } 
            });
        }).on('error', () => resolve(null));
    });
}

// --- Live Brain Loading ---
async function loadBridgeData() {
    console.log("🌐 [Bridge] Connecting to Keiyoushi & Doki Repos...");
    
    // 1. Fetch Keiyoushi
    const kData = await fetchJson(KEIYOUSHI_URL, true);
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

    // 2. Fetch Doki File List
    const dData = await fetchJson(DOKI_TREE_API, false);
    if (dData && Array.isArray(dData.tree)) {
        dData.tree.forEach(node => {
            if (node.path.endsWith('.kt') && node.path.includes('parsers/site')) {
                const filename = path.basename(node.path, '.kt');
                if (filename !== 'SiteParser') {
                    DOKI_CLASSES.push(filename);
                    DOKI_LOWER_MAP[filename.toLowerCase()] = filename;
                }
            }
        });
        console.log(`✅ [Bridge] Indexed ${DOKI_CLASSES.length} Kotatsu parsers.`);
    } else {
        console.warn("⚠️ [Bridge] Failed to load Doki Tree.");
    }
}

// --- Logic ---
function getDomain(url) {
    try {
        if(!url) return null;
        let u = url;
        if(!u.startsWith('http')) u = 'https://' + u;
        // Aggressive domain cleaning: removes www, m, v*, and trailing dots
        return new URL(u).hostname
            .replace(/^www\./, '')
            .replace(/^m\./, '')
            .replace(/^v\d+\./, '')
            .replace(/\.$/, '');
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

function getCoreIdentity(name) {
    if (!name) return "";
    return name.toLowerCase()
        .replace(/\b(scans?|comics?|toon|manga|webtoon|fansub|team|group)\b/g, '')
        .replace(/[^a-z0-9]/g, '')
        .trim();
}

// KOTATSU ➔ TACHIYOMI
function resolveToTachiyomi(kName, kUrl) {
    // 1. Strict Domain Match
    const domain = getDomain(kUrl);
    if (domain && TACHI_DOMAIN_MAP[domain]) {
        // We found an exact domain match.
        // We return this ID so we can strictly RENAME the source later.
        return TACHI_DOMAIN_MAP[domain].id;
    }

    // 2. Exact Name Match
    for (const id in TACHI_ID_MAP) {
        if (TACHI_ID_MAP[id].name.toLowerCase() === kName.toLowerCase()) return id;
    }

    // 3. AI Token Match
    const kCore = getCoreIdentity(kName);
    if (kCore.length > 2) { 
        for (const id in TACHI_ID_MAP) {
            const tCore = getCoreIdentity(TACHI_ID_MAP[id].name);
            if (tCore === kCore) {
                console.log(`🤖 [AI Match] "${kName}" -> "${TACHI_ID_MAP[id].name}"`);
                return id;
            }
        }
    }

    // Fallback Hash
    let hash = 0n;
    for (let i = 0; i < kName.length; i++) {
        hash = (31n * hash + BigInt(kName.charCodeAt(i))) & 0xFFFFFFFFFFFFFFFFn;
    }
    return hash.toString();
}

// TACHIYOMI ➔ KOTATSU
function resolveToKotatsuKey(tId, tName, tUrl) {
    if (tName === "MangaDex") return "MANGADEX";
    const domain = getDomain(tUrl);
    if (domain === "mangakakalot.com" || domain === "manganato.com") return "MANGANATO";
    if (domain === "bato.to") return "BATOTO";

    if (DOKI_LOWER_MAP[tName.toLowerCase()]) {
        return convertClassToConstant(DOKI_LOWER_MAP[tName.toLowerCase()]);
    }

    const tCore = getCoreIdentity(tName);
    if (tCore.length > 2) {
        for (const cls of DOKI_CLASSES) {
            const dCore = getCoreIdentity(cls);
            if (dCore === tCore) {
                console.log(`🤖 [AI Match] Tachi "${tName}" -> Doki "${cls}"`);
                return convertClassToConstant(cls);
            }
        }
    }
    return convertClassToConstant(tName);
}

function convertClassToConstant(className) {
    let snake = className.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase().replace(/[^A-Z0-9_]/g, "_");
    if (KOTATSU_OVERRIDES[snake]) return KOTATSU_OVERRIDES[snake];
    return snake;
}

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
    console.log('📦 Initializing Migration Kit (v24.0 Precision + Rename)...');
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
    
    zip.getEntries().forEach(e => {
        const n = e.name;
        if(n === 'favourites' || n === 'favourites.json') favouritesData = JSON.parse(e.getData().toString('utf8'));
    });

    if(!favouritesData) throw new Error("Invalid Backup: Missing favourites");

    const backupManga = [];
    const backupSources = [];
    const sourceSet = new Set();

    favouritesData.forEach(fav => {
        const kManga = fav.manga;
        if(!kManga) return;

        // 1. Resolve ID (String)
        const tSourceId = resolveToTachiyomi(kManga.source, kManga.url || kManga.public_url);
        
        // 2. Strict Renaming Logic
        // If we found a valid ID in our map, we MUST use the official name associated with that ID.
        // This ensures Tachiyomi recognizes the source even if the extension isn't installed.
        let sName = kManga.source;
        if (TACHI_ID_MAP[tSourceId]) {
            sName = TACHI_ID_MAP[tSourceId].name; // <--- The Fix: Use Official Name
        }

        if (!sourceSet.has(tSourceId)) {
            sourceSet.add(tSourceId);
            backupSources.push({ sourceId: tSourceId, name: sName });
        }

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
            categories: [], 
            history: []
        });
    });

    const payload = { backupManga, backupCategories: [], backupSources };
    const message = BackupMessage.create(payload);
    const buffer = BackupMessage.encode(message).finish();
    const gzipped = zlib.gzipSync(buffer);
    
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

    const getSrcInfo = (id) => {
        const s = (tachiData.backupSources || []).find(x => String(x.sourceId) === String(id));
        return s ? s.name : ("Source " + id);
    };

    (tachiData.backupManga || []).forEach(tm => {
        const tName = getSrcInfo(tm.source);
        const kSourceKey = resolveToKotatsuKey(String(tm.source), tName, tm.url);
        
        let kUrl = tm.url;
        if(kSourceKey === "MANGADEX") kUrl = kUrl.replace("/title/", "").replace("/manga/", "");
        const kId = getKotatsuId(kSourceKey + kUrl);

        const kManga = {
            id: kId, 
            title: cleanStr(tm.title),
            url: kUrl,
            public_url: null, 
            source: kSourceKey,
            state: tm.status === 2 ? "FINISHED" : "ONGOING",
            cover_url: cleanStr(tm.thumbnailUrl),
            tags: tm.genre || [],
            author: cleanStr(tm.author)
        };

        favorites.push({
            manga_id: kId, 
            category_id: 0,
            sort_key: 0,
            created_at: Number(tm.dateAdded),
            manga: kManga
        });
    });

    const zip = new AdmZip();
    zip.addFile("favourites", Buffer.from(stringifyWithBigInt(favorites), "utf8"));
    zip.addFile("history", Buffer.from("[]", "utf8")); 
    zip.addFile("categories", Buffer.from("[]", "utf8"));
    
    ["bookmarks", "sources", "saved_filters"].forEach(n => zip.addFile(n, Buffer.from("[]", "utf8")));
    ["reader_grid", "scrobbling", "settings", "statistics"].forEach(n => zip.addFile(n, Buffer.from("{}", "utf8")));
    zip.addFile("index", Buffer.from(JSON.stringify({ version: 2, created_at: Date.now(), app_version: "2025.01.01" }), "utf8"));

    zip.writeZip(path.join(OUTPUT_DIR, 'Backup.zip'));
    console.log('✅ Created output/Backup.zip');
}

main().catch(e => { console.error(e); process.exit(1); });
                  
