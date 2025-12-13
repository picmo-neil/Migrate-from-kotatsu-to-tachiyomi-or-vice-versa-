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
const KEIYOUSHI_URL = 'https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json';

if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// ==========================================
// 🧠 REPO BRIDGE ARCHITECTURE (v13.0)
// ==========================================

// [REGISTRY 1] KOTATSU / DOKI
// Maps [Kotatsu Internal Key] -> [Canonical Domain]
const KOTATSU_REGISTRY = {
    "MANGADEX": "mangadex.org",
    "MANGA_SEE": "mangasee123.com",
    "MANGA_LIFE": "mangalife.us",
    "BATO_TO": "bato.to",
    "WEBTOONS": "webtoons.com",
    
    // Manganato Network
    "MANGANATO": "manganato.com",
    "READMANGANATO": "readmanganato.com",
    "CHAPMANGANATO": "chapmanganato.to",
    "MANGAKAKALOTTV": "mangakakalot.com",

    // Asura / Flame
    "ASURA_SCANS": "asuratoon.com",
    "ASURA_SCANS_NET": "asuracomic.net",
    "FLAME_COMICS": "flamecomics.com",
    "FLAME_SCANS": "flamescans.org",

    // Common Scanlators
    "REAPER_SCANS": "reaperscans.com",
    "TCB_SCANS": "tcbscans.com",
    "DRAKE_SCANS": "drakescans.com",
    "RESET_SCANS": "reset-scans.com",
    "LUMINOUS_SCANS": "luminousscans.com",
    "VOID_SCANS": "hivescans.com",
    "RIAZ_G_MC": "riazgmc.com",
    "COMICK_FUN": "comick.io",
    
    // Manhwa/Manhua/Adult
    "MANHWA_18_CC": "manhwa18.cc",
    "TOONILY": "toonily.com",
    "MANHUA_FAST": "manhuafast.com",
    "HI_PERDEX": "hiperdex.com",
    "ALLPORN_COMIC": "allporncomic.com",
    "MANGA_PARK": "mangapark.net",
    "1ST_KISS_MANGA": "1stkissmanga.io",
    "MANGA_PILL": "mangapill.com",
    "MANHWATOP": "manhwatop.com",
    "ZINMANGA": "zinmanga.com",
    "TRUEMANGA": "truemanga.com",
    "NHENTAI": "nhentai.net"
};

// [REGISTRY 2] KEIYOUSHI / TACHIYOMI
// Maps [Canonical Domain] -> [Tachiyomi Extension ID]
const KEIYOUSHI_REGISTRY = {
    "mangadex.org": "2499283573021220255",
    "mangasee123.com": "2973143899120668045",
    "mangalife.us": "2973143899120668045",
    "bato.to": "8985172093557431221",
    "webtoons.com": "1989436384073367980",
    "mangakakalot.com": "2528986671771677900",
    "manganato.com": "1024627298672457456",
    "chapmanganato.to": "1024627298672457456",
    "readmanganato.com": "1024627298672457456",
    "asuratoon.com": "6335003343669033128",
    "asuracomic.net": "6335003343669033128",
    "flamecomics.com": "7027219105529276946",
    "flamescans.org": "7027219105529276946",
    "reaperscans.com": "5432970425689607116",
    "tcbscans.com": "374242698294247514",
    "drakescans.com": "4440058986712398616",
    "reset-scans.com": "7320022325372333118",
    "luminousscans.com": "7776264560706599723",
    "hivescans.com": "1554415891392671911",
    "comick.io": "8158721336644791464",
    "manhwa18.cc": "5502656519292762717",
    "toonily.com": "6750082404202711318",
    "manhuafast.com": "4088566215115473619",
    "hiperdex.com": "4390997657042630109",
    "allporncomic.com": "3650631607354829018",
    "mangapark.net": "3707293521087813296",
    "1stkissmanga.io": "5870005527666249265",
    "mangapill.com": "5426176527506972412",
    "manhwatop.com": "2504936442654378419",
    "zinmanga.com": "8472477543884267275",
    "truemanga.com": "1055223398939634718",
    "nhentai.net": "1111111111111111111"
};

const TACHI_NAMES = {}; // Map ID -> Readable Name
const ID_SEED = 1125899906842597n; 

// --- Utilities ---

function sanitize(str) {
    if (!str) return "";
    return str.toLowerCase()
        .replace(/\(en\)$/, "")
        .replace(/ english$/, "")
        .replace(/scans?$/, "")
        .replace(/comics?$/, "")
        .replace(/team$/, "")
        .replace(/[^a-z0-9]/g, "") 
        .trim();
}

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

// --- 🌐 Dynamic Repo Fetcher ---

function analyzeKeiyoushiRepo() {
    return new Promise((resolve) => {
        console.log('📡 Accessing Keiyoushi Extension Repository...');
        https.get(KEIYOUSHI_URL, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    const json = JSON.parse(data);
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
                    console.log(`✅ Repo Bridge: Learned ${added} new domains.`);
                    resolve(true);
                } catch (e) {
                    console.warn('⚠️ Offline Mode: Using built-in Knowledge Base.');
                    resolve(false);
                }
            });
        }).on('error', () => {
             console.warn('⚠️ Offline Mode: Using built-in Knowledge Base.');
             resolve(false);
        });
    });
}

// --- 🌉 BRIDGE RESOLVER FUNCTIONS ---

// 1. KOTATSU -> TACHIYOMI
function resolveKotatsuToTachiyomi(kotatsuName, publicUrl) {
    let domain = null;
    if (KOTATSU_REGISTRY[kotatsuName]) domain = KOTATSU_REGISTRY[kotatsuName];
    else if (publicUrl) domain = getDomain(publicUrl);

    if (!domain) {
        console.warn(`⚠️ Unknown Source: ${kotatsuName}. Using Hash ID.`);
        return { id: getKotatsuId(kotatsuName).toString(), name: kotatsuName };
    }

    if (KEIYOUSHI_REGISTRY[domain]) {
        const tId = KEIYOUSHI_REGISTRY[domain];
        const tName = TACHI_NAMES[tId] || kotatsuName;
        // console.log(`🌉 Bridged: ${kotatsuName} -> ${domain} -> ${tName}`);
        return { id: tId, name: tName };
    }

    // Domain exists but no ID found
    return { id: getKotatsuId(kotatsuName).toString(), name: kotatsuName };
}

// 2. TACHIYOMI -> KOTATSU
function resolveTachiyomiToKotatsu(tachiId, tachiName, url) {
    const tId = String(tachiId);
    let domain = null;

    // A. Reverse Lookup Domain
    for (const [dom, id] of Object.entries(KEIYOUSHI_REGISTRY)) {
        if (id === tId) {
            domain = dom;
            break;
        }
    }

    if (!domain && url) domain = getDomain(url);

    // B. Map Domain to Kotatsu Key
    if (domain) {
        for (const [kName, domVal] of Object.entries(KOTATSU_REGISTRY)) {
            if (domVal === domain) return kName;
        }
        
        // Smart Reconstruction: Generate a valid-looking Kotatsu Key from Domain
        // e.g. "mangafire.to" -> "MANGAFIRE"
        // This ensures the user can see which source it is, even if Kotatsu doesn't officially support it yet.
        return domain.split('.')[0].toUpperCase().replace(/[^A-Z0-9]/g, "_");
    }

    // C. Name Fallback
    return tachiName.toUpperCase().replace(/[^A-Z0-9]/g, "_");
}

// --- MAIN PROCESS ---

async function main() {
    console.log('📦 Initializing Repo Bridge Engine (v13.0)...');
    await analyzeKeiyoushiRepo(); 

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

    if(!favouritesData) throw new Error("Invalid Kotatsu Backup (missing favourites)");

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
        else if (tm.url) domain = getDomain(tm.url); // Use URL from backup if registry fail

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

        // Convert History
        // Kotatsu needs specific chapter IDs. Since we don't have Kotatsu chapter IDs,
        // we synthesize one using the logic: Hash(Source + ChapterURL). 
        // We find the last read chapter from Tachi history/chapters.
        if (tm.chapters) {
             let lastReadChap = null;
             // Find chapter with highest number that is marked read
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
                     percent: 0, // Tachi doesn't store percent, default to 0
                     scroll: 0
                 });
             }
        }
    });

    const zip = new AdmZip();
    zip.addFile("favourites.json", Buffer.from(JSON.stringify(favorites), "utf8"));
    zip.addFile("history.json", Buffer.from(JSON.stringify(history), "utf8"));
    
    // Legacy folder support
    zip.addFile("favourites", Buffer.from(JSON.stringify(favorites), "utf8"));
    zip.addFile("history", Buffer.from(JSON.stringify(history), "utf8"));

    zip.writeZip(path.join(OUTPUT_DIR, 'converted_kotatsu.zip'));
    console.log('✅ Success! Created converted_kotatsu.zip');
}

main().catch(err => {
    console.error("❌ Fatal Error:", err);
    process.exit(1);
});
    
