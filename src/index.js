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
    
    // Manual Overrides for common mismatches
    NAME_TO_ID['mangadex'] = '2499283573021220255';
    NAME_TO_ID['mangakakalot'] = '2528986671771677900';
    NAME_TO_ID['manganelo'] = '1024627298672457456';
    NAME_TO_ID['manganato'] = '1024627298672457456';
    NAME_TO_ID['local'] = '0';
}

function getSourceId(sourceName) {
  if (!sourceName) return "0";
  const lower = sourceName.toLowerCase();
  
  if (NAME_TO_ID[lower]) return NAME_TO_ID[lower];

  // Deterministic Hash Fallback
  // Matches Tachiyomi's logic for unknown sources
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

function safeDate(val) {
  if (!val) return Date.now();
  if (typeof val === 'string') return new Date(val).getTime();
  return Number(val);
}

// Status Mappings
function mapKotatsuStatus(kStatus) {
    if (!kStatus) return 0;
    const s = kStatus.toUpperCase();
    if (s === 'ONGOING') return 1;
    if (s === 'COMPLETED') return 2;
    if (s === 'LICENSED') return 3;
    if (s === 'PUBLISHING_FINISHED') return 4;
    if (s === 'CANCELLED') return 5;
    if (s === 'ON_HIATUS') return 6;
    return 1; // Default to Ongoing
}

function mapTachiStatus(tStatus) {
    switch(tStatus) {
        case 1: return 'ONGOING';
        case 2: return 'COMPLETED';
        case 3: return 'LICENSED';
        case 4: return 'PUBLISHING_FINISHED';
        case 5: return 'CANCELLED';
        case 6: return 'ON_HIATUS';
        default: return 'UNKNOWN';
    }
}

// --- Main Logic ---

async function main() {
  console.log('📦 Initializing Migration Kit (v5.0.0)...');
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

  // 1. Scan ZIP for key files
  for (const entry of zipEntries) {
      if (entry.isDirectory) continue;
      const name = entry.entryName;
      
      try {
          // Kotatsu: 'favourites' (The Manga Library)
          if (name === 'favourites' || name === 'favourites.json') {
              favouritesData = JSON.parse(entry.getData().toString('utf8'));
              console.log(`✅ Found Library: ${name}`);
          }
          // Kotatsu: 'categories'
          else if (name === 'categories' || name === 'categories.json') {
              categoriesData = JSON.parse(entry.getData().toString('utf8'));
              console.log(`✅ Found Categories: ${name}`);
          }
          // Kotatsu: 'history' (Last Read Timestamps)
          else if (name === 'history' || name === 'history.json') {
              historyData = JSON.parse(entry.getData().toString('utf8'));
              console.log(`✅ Found History: ${name}`);
          }
      } catch(e) {}
  }

  // Fallback scan if filename matching failed
  if (!favouritesData) {
      console.log("⚠️ Precise file match failed. Scanning all files for library data...");
      for (const entry of zipEntries) {
          try {
              const str = entry.getData().toString('utf8');
              if (str.startsWith('[')) {
                  const json = JSON.parse(str);
                  // Check signature of a Kotatsu Manga object
                  if (Array.isArray(json) && json.length > 0 && json[0].title && json[0].url) {
                      favouritesData = json;
                      console.log(`✅ Found Library in: ${entry.entryName}`);
                      break;
                  }
              }
          } catch(e) {}
      }
  }

  if (!favouritesData) throw new Error("Could not identify Kotatsu library data.");

  // 2. Process Categories
  // Mihon uses 'order' (index) to sort categories.
  // We map Kotatsu ID -> Mihon Order.
  const catIdToOrder = new Map(); 
  const backupCategories = [];
  
  if (categoriesData && Array.isArray(categoriesData)) {
      categoriesData.forEach((cat, index) => {
          // Tachi Categories: { name, order, flags }
          backupCategories.push({
              name: cat.name,
              order: cat.sortKey || index, 
              flags: 0 
          });
          catIdToOrder.set(cat.id, cat.sortKey || index); 
      });
  }

  // 3. Process History Map
  // Kotatsu history.json: [{ mangaId: 123, ... }]
  // We map Kotatsu Manga ID -> History Entry
  const historyMap = new Map();
  if (historyData && Array.isArray(historyData)) {
      historyData.forEach(h => {
          if (h.mangaId) historyMap.set(h.mangaId, h);
      });
  }

  const backupManga = [];
  const backupSources = [];
  const sourceSet = new Set();

  console.log(`📚 Processing ${favouritesData.length} manga entries...`);

  favouritesData.forEach((kManga) => {
      // A. Source Handling
      const sId = getSourceId(kManga.source);
      if (!sourceSet.has(sId)) {
          sourceSet.add(sId);
          backupSources.push({ sourceId: sId, name: kManga.source });
      }

      // B. Chapters
      const chapters = (kManga.chapters || []).map(ch => ({
          url: ch.url || '',
          name: ch.name || '',
          scanlator: ch.scanlator || null,
          read: !!ch.read,
          bookmark: 0,
          dateFetch: safeDate(ch.date),
          dateUpload: safeDate(ch.date),
          chapterNumber: ch.number ? parseFloat(ch.number) : -1,
          sourceOrder: 0
      }));

      // C. Categories
      // Mihon 'categories' field is a list of integers representing the ORDER of the categories it belongs to.
      const categories = [];
      if (kManga.categoryId !== undefined && catIdToOrder.has(kManga.categoryId)) {
          categories.push(catIdToOrder.get(kManga.categoryId));
      }

      // D. History
      const historyList = [];
      // Attempt to link via Kotatsu internal ID
      if (kManga.id && historyMap.has(kManga.id)) {
          const hEntry = historyMap.get(kManga.id);
          // Mihon History object
          historyList.push({
              url: kManga.url, // History is linked by URL in Tachi
              lastRead: safeDate(hEntry.updatedAt || hEntry.date),
              readDuration: 0
          });
      }

      // E. Build Manga Object
      backupManga.push({
          source: sId, // String passed to int64 field (handled by protobuf.js permissive create)
          url: kManga.url || '',
          title: kManga.title || '',
          artist: kManga.artist || '',
          author: kManga.author || '',
          description: kManga.description || '',
          genre: Array.isArray(kManga.genre) ? kManga.genre : [],
          status: mapKotatsuStatus(kManga.status),
          thumbnailUrl: kManga.thumbnailUrl || '',
          dateAdded: safeDate(kManga.dateAdded),
          chapters: chapters,
          categories: categories,
          history: historyList
      });
  });

  const payload = { 
      backupManga, 
      backupCategories, 
      backupSources 
  };

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

  const favourites = [];
  const categories = [];
  const history = [];

  // 1. Categories
  // We must generate numeric IDs for Kotatsu
  if (tachiData.backupCategories) {
      tachiData.backupCategories.forEach((cat, idx) => {
          categories.push({
              id: idx + 1, // 1-based ID
              name: cat.name,
              sortKey: cat.order,
              showInLibrary: true
          });
      });
  }

  const mangaList = tachiData.backupManga || [];
  console.log(`📚 Processing ${mangaList.length} manga...`);

  mangaList.forEach((tm, idx) => {
      const kotatsuId = idx + 1000; // Generate stable ID
      
      let sourceName = getSourceName(tm.source);
      if (tachiData.backupSources) {
          const bs = tachiData.backupSources.find(s => String(s.sourceId) === String(tm.source));
          if (bs && bs.name) sourceName = bs.name;
      }

      // Map Chapters
      const kChapters = (tm.chapters || []).map(ch => ({
         url: ch.url,
         name: ch.name,
         number: ch.chapterNumber,
         read: ch.read,
         date: ch.dateUpload || Date.now(),
         scanlator: ch.scanlator
      }));

      // Map Category
      // Kotatsu uses single Category ID. We take the first one from Tachi.
      let catId = 0; // 0 = Default
      if (tm.categories && tm.categories.length > 0) {
          // Tachi 'categories' are order indices. 
          // Our Kotatsu IDs are index + 1.
          catId = tm.categories[0] + 1;
      }

      // Extract History (for recents)
      // Tachi stores recent history in 'history' list inside manga
      if (tm.history && tm.history.length > 0) {
          const lastH = tm.history[0]; // Usually sorted
          history.push({
              mangaId: kotatsuId,
              date: lastH.lastRead,
              updatedAt: lastH.lastRead
          });
      }

      favourites.push({
          id: kotatsuId,
          title: tm.title,
          url: tm.url,
          source: sourceName,
          author: tm.author,
          artist: tm.artist,
          description: tm.description,
          genre: tm.genre || [],
          status: mapTachiStatus(tm.status),
          thumbnailUrl: tm.thumbnailUrl,
          chapters: kChapters,
          categoryId: catId, 
          newChapters: 0
      });
  });

  const zip = new AdmZip();
  // Kotatsu file structure (no extensions)
  zip.addFile("favourites", Buffer.from(JSON.stringify(favourites), "utf8"));
  zip.addFile("categories", Buffer.from(JSON.stringify(categories), "utf8"));
  zip.addFile("history", Buffer.from(JSON.stringify(history), "utf8"));
  zip.addFile("settings", Buffer.from("{}", "utf8"));
  
  const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
  zip.writeZip(outFile);
  console.log(`✅ Success! Created: ${outFile}`);
}

main().catch(err => {
  console.error('❌ FATAL ERROR:', err);
  process.exit(1);
});
