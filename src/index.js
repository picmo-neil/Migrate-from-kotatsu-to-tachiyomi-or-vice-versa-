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

// Comprehensive Mapping derived from Extension Index
// Maps Source Name -> Source ID (Long)
const SOURCE_MAP = {
  // Common / Global
  'MangaDex': '2499283573021220255',
  'Manganato': '1024627298672457456',
  'Mangakakalot': '2528986671771677900',
  'Bato.to': '4531444389842992129',
  'NHentai': '7309872737163460316',
  'E-Hentai': '57122881048805941',
  'Asura Scans': '6247824327199706550',
  'Flame Comics': '8531542650987673943',
  'MangaFire': '6084907896154116083',
  'MANGA Plus by SHUEISHA': '1998944621602463790',
  'Webtoons.com': '2522335540328470744',
  'Tappytoon': '7049142072741547166',
  'Toomics': '7004582542854505662',
  'Leitor de Mangá': '2818837330174796449',
  'Manga Livre': '2834885536325274328',
  'TuMangaOnline': '4146344224513899730',
  'Lectormanga': '3701714196729780447',
  'Japscan': '11',
  'Manga-Scantrad': '540252682818453285',
  'Manhwaclan': '3313733609433811176',
  'Manhwa18': '1901763227259218891',
  'Hiperdex': '3064755045370217842',
  'Doujins': '3733450486998805728',
  'HentaiRead': '2299981010822511979',
  'HentaiFox': '7945033982379409892',
  'Pururin': '2221515250486218861',
  'ReadManga': '5',
  'MintManga': '6',
  'SelfManga': '5227602742162454547',
  'Remangas': '7462657023971681136',
  'MangaPark': '2292947733994124621',
  'MangaLife': '6353982348574163056',
  'MangaSee': '4462085750100414706',
  'KomikCast': '972717448578983812',
  'West Manga': '8883916630998758688',
  'Shinigami': '3411809758861089969',
  'Kiryuu': '3639673976007021338',
  'Komiku': '4838485846640015979',
  'Maid - Manga': '5716614438725518956',
  'MangaHub': '4758858684982406533',
  'MangaReader': '789561949979941461',
  'MangaKakalot': '2528986671771677900',
  'Manganelo': '1024627298672457456',
  'Nhentai': '7309872737163460316',
  'Hitomi': '690123758188633713',
  'Tsumino': '676426462615430480',
  'Luscious': '2774395484485436593',
  'ManhwaHentai': '5733146869195184954',
  'Manhwa18.cc': '4841602236575491202',
  'Toonily': '5190569675461947007',
  'ManyToon': '8506087325905168576',
  'Hentai2Read': '8314925449740051373',
  'HentaiHere': '7266624490370375187',
  'Simply Hentai': '298934354390867671',
  '8Muses': '1802675169972965535',
  'Hentai20': '7114409483685920616',
  'Manga18.Club': '3436561761894030433',
  '3Hentai': '7819216870104067677'
};

// --- Helpers ---

function getSourceId(sourceName) {
  if (!sourceName) return "0"; // Local
  
  // 1. Exact Match
  if (SOURCE_MAP[sourceName]) return SOURCE_MAP[sourceName];
  
  // 2. Case Insensitive Match
  const lowerName = sourceName.toLowerCase();
  for (const key in SOURCE_MAP) {
    if (key.toLowerCase() === lowerName) return SOURCE_MAP[key];
  }

  // 3. Hash Fallback (Deterministic)
  let hash = 0n;
  for (let i = 0; i < sourceName.length; i++) {
    hash = (hash << 5n) - hash + BigInt(sourceName.charCodeAt(i));
    hash |= 0n;
  }
  return hash.toString();
}

function safeDate(val) {
  if (!val) return Date.now();
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
  let kotatsuData = null;
  
  try {
    const zip = new AdmZip(KOTATSU_INPUT);
    const zipEntries = zip.getEntries();
    
    // Debug logging
    console.log("📂 Zip contents:", zipEntries.map(e => e.entryName).join(", "));

    // AGGRESSIVE SEARCH STRATEGY
    for (const entry of zipEntries) {
      if (entry.isDirectory) continue;
      
      // Attempt to parse EVERY file as JSON, regardless of extension
      try {
        const text = entry.getData().toString('utf8');
        // Simple heuristic: Does it start like a JSON array or object?
        if (text.trim().startsWith('[') || text.trim().startsWith('{')) {
             const json = JSON.parse(text);
             // Validation: Is this a backup?
             if (Array.isArray(json) || (json.manga && Array.isArray(json.manga)) || (json.favorites && Array.isArray(json.favorites))) {
                 console.log(`✅ Found Kotatsu data in: ${entry.entryName}`);
                 kotatsuData = json;
                 break;
             }
        }
      } catch (e) {
        // Not a JSON file, ignore
      }
    }
  } catch (e) {
    console.warn("⚠️ Could not open as ZIP. Trying as plain text file...");
  }

  // Fallback: User might have uploaded a .json file renamed to .zip
  if (!kotatsuData) {
      try {
          const rawContent = fs.readFileSync(KOTATSU_INPUT, 'utf8');
          const json = JSON.parse(rawContent);
          if (Array.isArray(json) || json.manga || json.favorites) {
               console.log("✅ Found Kotatsu data in the raw file (not a zip).");
               kotatsuData = json;
          }
      } catch (e) {}
  }

  if (!kotatsuData) throw new Error("Invalid Kotatsu backup: No valid JSON found inside zip or file.");

  // Normalization: Kotatsu backups vary (Array of manga OR Object with favorites)
  const mangaList = Array.isArray(kotatsuData) ? kotatsuData : (kotatsuData.favorites || kotatsuData.manga || []);
  console.log(`found ${mangaList.length} manga entries.`);

  const backupManga = [];
  const backupCategories = [];
  const categoriesMap = new Map();
  const usedSources = new Map(); 

  mangaList.forEach((kManga) => {
    // 1. Process Categories
    const catList = [];
    if (kManga.categories) {
      const cats = Array.isArray(kManga.categories) ? kManga.categories : [kManga.categories];
      cats.forEach(catName => {
        if (!catName) return;
        if (!categoriesMap.has(catName)) {
          const order = categoriesMap.size + 1; 
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
      dateFetch: safeDate(kChap.date),
      dateUpload: safeDate(kChap.date),
      sourceOrder: 0
    }));

    // 3. Process Source
    const sName = kManga.source || 'Local';
    const sId = getSourceId(sName); // This now uses the massive ID map
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

  // 5. Generate Source List for Tachiyomi
  const backupSources = Array.from(usedSources.entries()).map(([id, name]) => ({
    sourceId: id,
    name: name
  }));

  const payload = { backupManga, backupCategories, backupSources };
  
  // Verify against schema
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
  const unzipped = zlib.gunzipSync(buffer);
  const message = BackupMessage.decode(unzipped);
  
  // Use 'longs: String' to preserve precision of Source IDs
  const tachiData = BackupMessage.toObject(message, { defaults: true, longs: String });
  console.log(`Found ${tachiData.backupManga ? tachiData.backupManga.length : 0} manga entries.`);

  const kotatsuExport = [];
  const catIdToName = {};
  if (Array.isArray(tachiData.backupCategories)) {
    tachiData.backupCategories.forEach(c => {
      catIdToName[c.order] = c.name; 
    });
  }

  // Reverse mapping for Sources (ID -> Name)
  const idToSourceName = {};
  for(const [name, id] of Object.entries(SOURCE_MAP)) {
      idToSourceName[id] = name;
  }

  const mangaArr = tachiData.backupManga || [];
  mangaArr.forEach(tm => {
    const categories = (tm.categories || []).map(id => catIdToName[id]).filter(Boolean);
    
    const chapters = (tm.chapters || []).map(tc => ({
      url: tc.url,
      name: tc.name,
      number: tc.chapterNumber,
      read: tc.read,
      date: tc.dateUpload,
      scanlator: tc.scanlator
    }));

    // Try to find the name in our map, otherwise use what's in the backup or a fallback
    let sourceName = idToSourceName[tm.source];
    if (!sourceName) {
        // Try to find it in the backup's source list
        const sEntry = (tachiData.backupSources || []).find(s => s.sourceId == tm.source);
        if (sEntry) sourceName = sEntry.name;
    }

    kotatsuExport.push({
      title: tm.title,
      url: tm.url,
      source: sourceName || `Source_${tm.source}`,
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
  zip.addFile("backup.json", Buffer.from(JSON.stringify(kotatsuExport, null, 2), "utf8"));
  
  const outFile = path.join(OUTPUT_DIR, 'converted_kotatsu.zip');
  zip.writeZip(outFile);
  console.log(`✅ Success! Created: ${outFile}`);
}

main().catch(err => {
  console.error('❌ FATAL ERROR:', err);
  process.exit(1);
});
