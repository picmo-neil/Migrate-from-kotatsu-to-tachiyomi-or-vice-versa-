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

// Ensure output dir exists
if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);

// Known mappings to Official Tachiyomi Extension IDs
const SOURCE_MAPPINGS = {
  'MangaDex': 2499283573021220255n,
  'Manganato': 7367807421835334005n,
  'Mangakakalot': 2697072491176462740n,
  'Bato.to': 7586203134676161474n,
  'MangaSee': 4462085750100414706n
};

// --- Helpers ---

function getSourceId(sourceName) {
  if (!sourceName) return 0n; // Local source
  if (SOURCE_MAPPINGS[sourceName]) return SOURCE_MAPPINGS[sourceName];
  
  // Fallback: Generate a deterministic hash for unknown sources
  let hash = 0n;
  for (let i = 0; i < sourceName.length; i++) {
    hash = (hash << 5n) - hash + BigInt(sourceName.charCodeAt(i));
    hash |= 0n;
  }
  return hash;
}

function getSourceName(sourceId) {
  // Safe comparison: convert everything to string to match BigInts, Numbers, or Strings
  const targetId = String(sourceId);
  for (const [name, id] of Object.entries(SOURCE_MAPPINGS)) {
    if (String(id) === targetId) return name;
  }
  return `Source_${targetId}`;
}

function safeDate(val) {
  if (!val) return Date.now();
  // Handle if Kotatsu gives an ISO string or a timestamp
  if (typeof val === 'string') return new Date(val).getTime();
  return Number(val);
}

// --- Main Logic ---

async function main() {
  console.log('📦 Loading Protobuf Schema...');
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
  let kotatsuData = null;

  for (const entry of zipEntries) {
    if (entry.entryName.endsWith('.json') && !entry.isDirectory) {
      try {
        const json = JSON.parse(entry.getData().toString('utf8'));
        // Detect Kotatsu format
        if (Array.isArray(json) || json.manga || json.favorites) {
          kotatsuData = json;
          break;
        }
      } catch (e) {
        console.warn('Skipping invalid JSON:', entry.entryName);
      }
    }
  }

  if (!kotatsuData) throw new Error("Invalid Kotatsu backup: No valid JSON found inside zip.");

  const mangaList = Array.isArray(kotatsuData) ? kotatsuData : (kotatsuData.favorites || kotatsuData.manga || []);
  console.log(`found ${mangaList.length} manga entries.`);

  const backupManga = [];
  const backupCategories = [];
  const categoriesMap = new Map();
  const usedSources = new Map(); // ID -> Name mapping for BackupSource

  mangaList.forEach((kManga) => {
    // 1. Process Categories
    const catList = [];
    if (Array.isArray(kManga.categories)) {
      kManga.categories.forEach(catName => {
        if (!categoriesMap.has(catName)) {
          const order = categoriesMap.size + 1; // 1-based index usually
          categoriesMap.set(catName, order);
          backupCategories.push({ name: catName, order: order, flags: 0 });
        }
        catList.push(categoriesMap.get(catName));
      });
    }

    // 2. Process Chapters
    const chapters = (kManga.chapters || []).map(kChap => ({
      url: kChap.url || '',
      name: kChap.name || `Chapter ${kChap.number}`,
      scanlator: kChap.scanlator || '',
      chapterNumber: parseFloat(kChap.number) || 0.0,
      read: !!kChap.read,
      bookmark: 0,
      dateFetch: safeDate(kChap.date), // Fallback to now
      dateUpload: safeDate(kChap.date),
      sourceOrder: 0
    }));

    // 3. Process Source
    const sName = kManga.source || 'Local';
    const sId = getSourceId(sName);
    usedSources.set(sId, sName);

    // 4. Create Manga Entry
    backupManga.push({
      source: sId,
      url: kManga.url || '',
      title: kManga.title || 'Unknown Title',
      artist: kManga.artist || '',
      author: kManga.author || '',
      description: kManga.description || '',
      genre: Array.isArray(kManga.genre) ? kManga.genre : [],
      status: kManga.status === 'ONGOING' ? 1 : kManga.status === 'COMPLETED' ? 2 : 0,
      thumbnailUrl: kManga.thumbnailUrl || '',
      chapters: chapters,
      categories: catList,
      dateAdded: safeDate(null), 
      viewer: 0
    });
  });

  // 5. Generate Source List
  // This helps Tachiyomi recognize the source name even if the extension isn't installed
  const backupSources = Array.from(usedSources.entries()).map(([id, name]) => ({
    sourceId: id,
    name: name
  }));

  // 6. Encode and Save
  const payload = { backupManga, backupCategories, backupSources };
  
  // Verify against schema to catch type errors early
  const errMsg = BackupMessage.verify(payload);
  if (errMsg) throw Error(errMsg);

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
  // Tachiyomi backups are Gzipped Protobuf
  const unzipped = zlib.gunzipSync(buffer);
  
  const message = BackupMessage.decode(unzipped);
  
  // IMPORTANT: 'longs: String' ensures 64-bit IDs are not corrupted by JS numbers
  const tachiData = BackupMessage.toObject(message, { defaults: true, longs: String });

  console.log(`Found ${tachiData.backupManga ? tachiData.backupManga.length : 0} manga entries.`);

  const kotatsuExport = [];

  // Map Categories ID to Name
  const catIdToName = {};
  if (Array.isArray(tachiData.backupCategories)) {
    tachiData.backupCategories.forEach(c => {
      catIdToName[c.order] = c.name; 
    });
  }

  // Iterate Manga
  const mangaArr = tachiData.backupManga || [];
  mangaArr.forEach(tm => {
    // Resolve Categories
    const categories = (tm.categories || []).map(id => catIdToName[id]).filter(Boolean);
    
    // Resolve Chapters
    const chapters = (tm.chapters || []).map(tc => ({
      url: tc.url,
      name: tc.name,
      number: tc.chapterNumber, // Keep as number for Kotatsu JSON
      read: tc.read,
      date: tc.dateUpload,
      scanlator: tc.scanlator
    }));

    kotatsuExport.push({
      title: tm.title,
      url: tm.url,
      source: getSourceName(tm.source), // Attempt to resolve ID back to Name
      author: tm.author,
      artist: tm.artist,
      description: tm.description,
      genre: tm.genre || [],
      status: tm.status === 1 ? 'ONGOING' : tm.status === 2 ? 'COMPLETED' : 'UNKNOWN',
      thumbnailUrl: tm.thumbnailUrl,
      chapters: chapters,
      categories: categories
    });
  });

  const zip = new AdmZip();
  // Kotatsu expects a JSON file inside the zip. 
  zip.addFile("backup.json", Buffer.from(JSON.stringify(kotatsuExport, null, 2), "utf8"));
  
  const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
  zip.writeZip(outFile);
  console.log(`✅ Success! Created: ${outFile}`);
}

main().catch(err => {
  console.error('❌ FATAL ERROR:', err);
  process.exit(1);
});
