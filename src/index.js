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

const SOURCE_MAPPINGS = {
  'MangaDex': 2499283573021220255n,
  'Manganato': 7367807421835334005n,
};

// --- Helpers ---

function getSourceId(sourceName) {
  if (SOURCE_MAPPINGS[sourceName]) return SOURCE_MAPPINGS[sourceName];
  let hash = 0n;
  for (let i = 0; i < sourceName.length; i++) {
    hash = (hash << 5n) - hash + BigInt(sourceName.charCodeAt(i));
    hash |= 0n;
  }
  return hash;
}

function getSourceName(sourceId) {
  // Reverse lookup or best guess
  for (const [name, id] of Object.entries(SOURCE_MAPPINGS)) {
    if (id === sourceId) return name;
  }
  return `Source_${sourceId}`;
}

// --- Main Logic ---

async function main() {
  const root = await protobuf.load(PROTO_FILE);
  const BackupMessage = root.lookupType("tachiyomi.Backup");

  if (fs.existsSync(KOTATSU_INPUT)) {
    await kotatsuToTachiyomi(BackupMessage);
  } else if (fs.existsSync(TACHI_INPUT)) {
    await tachiyomiToKotatsu(BackupMessage);
  } else {
    throw new Error('No backup file found! Please add Backup.zip or Backup.tachibk');
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
      const json = JSON.parse(entry.getData().toString('utf8'));
      if (Array.isArray(json) || json.manga || json.favorites) {
        kotatsuData = json;
        break;
      }
    }
  }

  if (!kotatsuData) throw new Error("Invalid Kotatsu backup");

  const mangaList = Array.isArray(kotatsuData) ? kotatsuData : (kotatsuData.favorites || []);
  const backupManga = [];
  const backupCategories = [];
  const categoriesMap = new Map();

  mangaList.forEach((kManga) => {
    // Categories
    const catList = [];
    if (kManga.categories) {
      kManga.categories.forEach(catName => {
        if (!categoriesMap.has(catName)) {
          const order = categoriesMap.size + 1;
          categoriesMap.set(catName, order);
          backupCategories.push({ name: catName, order: order, flags: 0 });
        }
        catList.push(categoriesMap.get(catName));
      });
    }

    // Chapters
    const chapters = (kManga.chapters || []).map(kChap => ({
      url: kChap.url || '',
      name: kChap.name || `Chapter ${kChap.number}`,
      chapterNumber: kChap.number || 0,
      read: kChap.read || false,
      dateFetch: Date.now(),
      dateUpload: kChap.date || Date.now(),
      sourceOrder: 0
    }));

    backupManga.push({
      source: getSourceId(kManga.source || 'Local'),
      url: kManga.url || '',
      title: kManga.title || 'Unknown',
      artist: kManga.artist || '',
      author: kManga.author || '',
      description: kManga.description || '',
      genre: kManga.genre || [],
      status: kManga.status === 'ONGOING' ? 1 : kManga.status === 'COMPLETED' ? 2 : 0,
      thumbnailUrl: kManga.thumbnailUrl || '',
      chapters: chapters,
      categories: catList,
    });
  });

  const message = BackupMessage.create({ backupManga, backupCategories });
  const buffer = BackupMessage.encode(message).finish();
  const gzipped = zlib.gzipSync(buffer);
  
  const outFile = path.join(OUTPUT_DIR, 'converted_tachiyomi.tachibk');
  fs.writeFileSync(outFile, gzipped);
  console.log(`✅ Created: ${outFile}`);
}

async function tachiyomiToKotatsu(BackupMessage) {
  console.log('🔄 Mode: Tachiyomi -> Kotatsu');
  
  const buffer = fs.readFileSync(TACHI_INPUT);
  const unzipped = zlib.gunzipSync(buffer);
  const message = BackupMessage.decode(unzipped);
  const tachiData = BackupMessage.toObject(message, { defaults: true });

  const kotatsuExport = [];

  // Map Categories ID to Name
  const catIdToName = {};
  if (tachiData.backupCategories) {
    tachiData.backupCategories.forEach(c => {
      catIdToName[c.order] = c.name; // Simplification, Tachi logic is complex here
    });
  }

  tachiData.backupManga.forEach(tm => {
    const categories = (tm.categories || []).map(id => catIdToName[id] || 'Default');
    
    const chapters = (tm.chapters || []).map(tc => ({
      url: tc.url,
      name: tc.name,
      number: tc.chapterNumber,
      read: tc.read,
      date: tc.dateUpload
    }));

    kotatsuExport.push({
      title: tm.title,
      url: tm.url,
      source: getSourceName(tm.source),
      author: tm.author,
      artist: tm.artist,
      description: tm.description,
      genre: tm.genre,
      status: tm.status === 1 ? 'ONGOING' : tm.status === 2 ? 'COMPLETED' : 'UNKNOWN',
      thumbnailUrl: tm.thumbnailUrl,
      chapters: chapters,
      categories: categories
    });
  });

  const zip = new AdmZip();
  zip.addFile("backup.json", Buffer.from(JSON.stringify(kotatsuExport, null, 2), "utf8"));
  
  const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
  zip.writeZip(outFile);
  console.log(`✅ Created: ${outFile}`);
}

main().catch(console.error);
