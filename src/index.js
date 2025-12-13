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

// API ENDPOINTS
const KEIYOUSHI_URL = 'https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json';
const KOTATSU_REPO_API = 'https://api.github.com/repos/DokiTeam/doki-exts/contents/src/main/kotlin/org/dokiteam/doki/parsers/site';

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// ==========================================
// 🧠 REPO BRIDGE ARCHITECTURE (v14.0)
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

function fetchUrl(url, isJson = true) {
    return new Promise((resolve, reject) => {
        const headers = { 'User-Agent': 'Node.js-Script' };
        if (process.env.GH_TOKEN && url.includes('api.github.com')) {
            headers['Authorization'] = `Bearer ${process.env.GH_TOKEN}`;
        }

        https.get(url, { headers }, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                if (res.statusCode >= 200 && res.statusCode < 300) {
                    try {
                        resolve(isJson ? JSON.parse(data) : data);
                    } catch (e) { reject(e); }
                } else {
                    reject(new Error(`Status ${res.statusCode}`));
                }
            });
        }).on('error', reject);
    });
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
        
        for (let i = 0; i < files.length; i += batchSize) {
            const batch = files.slice(i, i + batchSize);
            await Promise.all(batch.map(async (file) => {
                if (!file.name.endsWith('.kt')) return;
                try {
                    // Fetch Raw Kotlin Content
                    const code = await fetchUrl(file.download_url, false);
                    
                    // 3. Regex Scraper
                    // Pattern A: class Name : Parent("Name", "Url", ...)
                    // Pattern B: override val name = "Name" ... override val baseUrl = "Url"
                    
                    let name = null;
                    let url = null;

                    // Try extraction
                    const nameMatch = code.match(/override\s+val\s+name\s*=s*"([^"]+)"/) || code.match(/super\(\s*"([^"]+)"/);
                    const urlMatch = code.match(/override\s+val\s+baseUrl\s*=s*"([^"]+)"/) || code.match(/"(https?://[^"]+)"/);

                    if (nameMatch) name = nameMatch[1];
                    if (urlMatch) url = urlMatch[1];

                    if (name && url) {
                        const domain = getDomain(url);
                        // Clean Name for internal key (Kotatsu often uses UPPER_CASE keys or simple names)
                        // Heuristic: The file name usually corresponds to the key logic
                        // But we map [Name] -> [Domain]
                        if (domain) {
                            // Map the raw name from code
                            KOTATSU_REGISTRY[name] = domain;
                            // Map the upper-snake-case version (common in backups)
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
    // Try Live Registry first
    if (KOTATSU_REGISTRY[kotatsuName]) domain = KOTATSU_REGISTRY[kotatsuName];
    // Fallback to URL in backup
    else if (publicUrl) domain = getDomain(publicUrl);

    if (!domain) return { id: getKotatsuId(kotatsuName).toString(), name: kotatsuName };

    // Bridge Crossing
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
            if (domVal === domain) return kName; // Found exact match from live scrape
        }
        
        // Smart Reconstruction (Safety Net)
        // If live scrape missed it (or new source), generate a valid-looking key
        return domain.split('.')[0].toUpperCase().replace(/[^A-Z0-9]/g, "_");
    }

    return tachiName.toUpperCase().replace(/[^A-Z0-9]/g, "_");
}

// --- MAIN PROCESS ---

async function main() {
    console.log('📦 Initializing Repo Bridge Engine (v14.0)...');
    
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
        if(e.name.includes('favourites')) favouritesData = JSON.parse(e.getData().toString('utf8'));
        if(e.name.includes('categories')) categoriesData = JSON.parse(e.getData().toString('utf8'));
        if(e.name.includes('history')) historyData = JSON.parse(e.getData().toString('utf8'));
    });

    if(!favouritesData) throw new Error("Invalid Kotatsu Backup");

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

        favorites.push({
            manga_id: kId,
            category_id: 0,
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
                tags: tm.genre || []
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
    zip.addFile("favourites.json", Buffer.from(JSON.stringify(favorites), "utf8"));
    zip.addFile("history.json", Buffer.from(JSON.stringify(history), "utf8"));
    zip.addFile("favourites", Buffer.from(JSON.stringify(favorites), "utf8"));
    zip.addFile("history", Buffer.from(JSON.stringify(history), "utf8"));

    zip.writeZip(path.join(OUTPUT_DIR, 'converted_kotatsu.zip'));
    console.log('✅ Success! Created converted_kotatsu.zip');
}

main().catch(err => {
    console.error("❌ Fatal Error:", err);
    process.exit(1);
});
        
