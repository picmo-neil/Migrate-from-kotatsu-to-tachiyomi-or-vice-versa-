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

const NAME_TO_ID = {};
const ID_TO_NAME = {};
const ID_SEED = 1125899906842597n; // Kotatsu ID Seed

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
        h = (31n * h + BigInt(str.charCodeAt(i)));
        h = BigInt.asIntN(64, h); // Simulate int64 signed wrapping
    }
    return h;
}

// --- Logic from convert/core.py ---
function toKotatsuSource(tySource) {
    if (!tySource) return "";
    if (tySource === "Mangakakalot") return "MANGAKAKALOTTV";
    if (tySource === "Comick") return "COMICK_FUN";
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

function stringifyWithBigInt(obj) {
    const placeholderPrefix = "BIGINT::";
    const json = JSON.stringify(obj, (key, value) => {
        if (typeof value === 'bigint') {
            return placeholderPrefix + value.toString();
        }
        return value;
    });
    return json.replace(new RegExp(`"${placeholderPrefix}(-?\\d+)"`, 'g'), '$1');
}

// --- Safety Helper ---
const cleanStr = (s) => (s && (typeof s === 'string' || typeof s === 'number')) ? String(s) : "";

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

async function kotatsuToTachiyomi(BackupMessage) {
    console.log('🔄 Mode: Kotatsu -> Tachiyomi');
    
    const zip = new AdmZip(KOTATSU_INPUT);
    const zipEntries = zip.getEntries();
    
    let favouritesData = null;
    let categoriesData = null;
    let historyData = null;

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
             historyMap.set(h.mangaId, h);
        });
    }

    console.log(`📚 Processing ${favouritesData.length} favorites...`);

    favouritesData.forEach(fav => {
        const kManga = fav.manga;
        if (!kManga) return;

        let tSourceId = "0";
        const sourceName = cleanStr(kManga.source);
        if (NAME_TO_ID[sourceName.toLowerCase()]) {
            tSourceId = NAME_TO_ID[sourceName.toLowerCase()];
        } else {
            tSourceId = getSourceId(sourceName); 
        }

        if (!sourceSet.has(tSourceId)) {
            sourceSet.add(tSourceId);
            backupSources.push({ sourceId: tSourceId, name: sourceName });
        }

        const historyList = [];
        if (historyMap.has(kManga.id)) {
            const h = historyMap.get(kManga.id);
            historyList.push({
                url: cleanStr(kManga.url),
                lastRead: Number(h.updated_at || h.created_at) || Date.now(),
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

    const getSrcName = (id) => {
        if (tachiData.backupSources) {
            const s = tachiData.backupSources.find(x => String(x.sourceId) === String(id));
            if (s) return s.name;
        }
        return getSourceName(id);
    };

    const mangaList = tachiData.backupManga || [];
    console.log(`📚 Processing ${mangaList.length} manga...`);

    mangaList.forEach((tm, i) => {
        const tySource = cleanStr(getSrcName(tm.source));
        const kSource = toKotatsuSource(tySource);
        const kUrl = toKotatsuUrl(tySource, cleanStr(tm.url));
        const kId = getKotatsuId(kSource + kUrl); 
        const kPublicUrl = toKotatsuPublicUrl(tySource, kUrl);
        const kStatus = toKotatsuStatus(tm.status);

        const kManga = {
            id: kId,
            title: cleanStr(tm.title),
            alt_title: null,
            url: kUrl,
            public_url: kPublicUrl,
            rating: -1.0,
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

        if (tm.chapters && tm.chapters.length > 0) {
            let latest = null;
            let newest = null;
            tm.chapters.forEach(ch => {
                if (ch.read) {
                    if (!latest || ch.chapterNumber > latest.chapterNumber) latest = ch;
                }
                if (!newest || ch.chapterNumber > newest.chapterNumber) newest = ch;
            });

            if (latest) {
                const chUrl = toKotatsuChapterUrl(tySource, cleanStr(latest.url));
                const chId = getKotatsuId(kSource + chUrl);
                const percent = (newest && newest.chapterNumber > 0) 
                    ? (latest.chapterNumber / newest.chapterNumber) 
                    : 0;

                const kHist = {
                    manga_id: kId,
                    created_at: Number(tm.dateAdded),
                    updated_at: Number(tm.dateAdded),
                    chapter_id: chId,
                    page: latest.lastPageRead || 0,
                    scroll: 0,
                    percent: percent,
                    manga: kManga
                };
                history.push(kHist);
            }
        }
    });

    const zip = new AdmZip();
    const favJson = stringifyWithBigInt(favorites);
    const histJson = stringifyWithBigInt(history);

    zip.addFile("favourites", Buffer.from(favJson, "utf8"));
    zip.addFile("history", Buffer.from(histJson, "utf8"));
    
    const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
    zip.writeZip(outFile);
    console.log(`✅ Success! Created: ${outFile}`);
}

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
