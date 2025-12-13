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

// --- GOLDEN DATABASE (Hardcoded Stability) 🏆 ---
// These are official Tachiyomi/Keiyoushi IDs. 
// We use these if the domain matches, overriding everything else.
const GOLDEN_DB = {
    // MangaDex
    "mangadex.org": { id: "2499283573021220255", name: "MangaDex" },
    
    // Manganato / Mangakakalot Family
    "manganato.com": { id: "1791778683660516", name: "Manganato" },
    "chapmanganato.com": { id: "1791778683660516", name: "Manganato" },
    "readmanganato.com": { id: "1791778683660516", name: "Manganato" },
    "mangakakalot.com": { id: "2229245767045543", name: "Mangakakalot" },
    
    // Bato Family
    "bato.to": { id: "73976367851206", name: "Bato.to" },
    "battwo.com": { id: "73976367851206", name: "Bato.to" },
    "mto.to": { id: "73976367851206", name: "Bato.to" },
    "dto.to": { id: "73976367851206", name: "Bato.to" },
    "zh.bato.to": { id: "73976367851206", name: "Bato.to" },
    
    // Asura
    "asuratoon.com": { id: "6676140324647343467", name: "Asura Scans" },
    "asura.gg": { id: "6676140324647343467", name: "Asura Scans" },
    "asurascans.com": { id: "6676140324647343467", name: "Asura Scans" },
    
    // Flame
    "flamecomics.com": { id: "7350700882194883466", name: "Flame Comics" },
    "flamescans.org": { id: "7350700882194883466", name: "Flame Comics" },

    // Reaper
    "reapercomics.com": { id: "5113063529342730466", name: "Reaper Scans" },
    "reaperscans.com": { id: "5113063529342730466", name: "Reaper Scans" },

    // Comick
    "comick.io": { id: "4689626359218228302", name: "Comick" },
    "comick.app": { id: "4689626359218228302", name: "Comick" },
    
    // Hentai / Others
    "nhentai.net": { id: "7670359809983944111", name: "NHentai" },
    "allporncomic.com": { id: "1721899314997758148", name: "AllPornComic" }
};

// --- Helper: Signed 64-bit Normalizer ---
// Converts any 64-bit value to a Signed String for Protobuf
function toSigned64(val) {
    try {
        return BigInt.asIntN(64, BigInt(val)).toString();
    } catch (e) {
        return "0";
    }
}

// --- BackupBuilder Class 🏗️ ---
// Guarantees that every Manga added also registers its Source.
class BackupBuilder {
    constructor() {
        this.mangas = [];
        // Map<ID, Name> - Uses a map to ensure unique ID entries
        this.sourceRegistry = new Map();
    }

    addManga(manga, sourceId, sourceName) {
        const sid = toSigned64(sourceId);
        
        // 1. Add Manga Record
        this.mangas.push({
            ...manga,
            source: sid // Link to normalized ID
        });

        // 2. Register Source (If not exists, or overwrite if "Unknown")
        if (!this.sourceRegistry.has(sid)) {
            this.sourceRegistry.set(sid, sourceName);
        } else {
            // Optional: If we have a better name now, update it?
            // For now, first come first serve, but Golden DB is checked before calling addManga
        }
    }

    getPayload() {
        const backupSources = [];
        for (const [id, name] of this.sourceRegistry.entries()) {
            backupSources.push({ sourceId: id, name: name });
        }
        return {
            backupManga: this.mangas,
            backupSources: backupSources,
            backupCategories: []
        };
    }
}

// --- Live Repos ---
const KEIYOUSHI_URL = 'https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json';
const DOKI_TREE_API = 'https://api.github.com/repos/DokiTeam/doki-exts/git/trees/base?recursive=1';

// --- Global Brain ---
const TACHI_DOMAIN_MAP = {}; // domain -> { id, name }
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
        const opts = { headers: { 'User-Agent': 'NodeJS-Bridge-v30' } };
        if (process.env.GH_TOKEN && url.includes('github.com')) opts.headers['Authorization'] = `Bearer ${process.env.GH_TOKEN}`;
        https.get(url, opts, (res) => {
            let data = '';
            res.on('data', c => data += c);
            res.on('end', () => { 
                try { 
                    if (isKeiyoushi) {
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

// --- Logic ---
function getDomain(url) {
    try {
        if(!url) return null;
        let u = url;
        if(!u.startsWith('http')) u = 'https://' + u;
        return new URL(u).hostname
            .replace(/^www\./, '')
            .replace(/^m\./, '')
            .replace(/^v\d+\./, '')
            .replace(/\.$/, '');
    } catch { return null; }
}

async function loadBridgeData() {
    console.log("🌐 [Bridge] Loading Live Data...");
    // 1. Load Golden DB into Map first
    for (const [dom, info] of Object.entries(GOLDEN_DB)) {
        TACHI_DOMAIN_MAP[dom] = info;
    }

    // 2. Fetch Keiyoushi to fill gaps
    const kData = await fetchJson(KEIYOUSHI_URL, true);
    if (Array.isArray(kData)) {
        kData.forEach(ext => {
           if(ext.sources) ext.sources.forEach(s => {
               const dom = getDomain(s.baseUrl);
               if(dom && !TACHI_DOMAIN_MAP[dom]) {
                   TACHI_DOMAIN_MAP[dom] = { id: toSigned64(s.id), name: s.name };
               }
           });
        });
    }
}

function resolveTachiInfo(kName, kUrl) {
    // 1. Check Domain Map (Includes Golden DB)
    const domain = getDomain(kUrl);
    if (domain && TACHI_DOMAIN_MAP[domain]) {
        return TACHI_DOMAIN_MAP[domain];
    }

    // 2. Fallback: Hash
    let hash = 0n;
    for (let i = 0; i < kName.length; i++) {
        hash = (31n * hash + BigInt(kName.charCodeAt(i))) & 0xFFFFFFFFFFFFFFFFn;
    }
    return { id: toSigned64(hash), name: kName };
}

const cleanStr = (s) => (s && (typeof s === 'string' || typeof s === 'number')) ? String(s) : "";

// --- MAIN ---

async function main() {
    if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR);
    console.log('📦 Initializing Migration Kit (v30.0 Bulletproof)...');
    
    await loadBridgeData();

    console.log('📖 Loading Protobuf Schema...');
    const root = await protobuf.load(PROTO_FILE);
    const BackupMessage = root.lookupType("tachiyomi.Backup");

    if (fs.existsSync(KOTATSU_INPUT)) {
        await kotatsuToTachiyomi(BackupMessage);
    } else {
        throw new Error('❌ No backup file found! Please upload Backup.zip');
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

    const builder = new BackupBuilder();

    favouritesData.forEach(fav => {
        const kManga = fav.manga;
        if(!kManga) return;

        // Resolve Info
        const info = resolveTachiInfo(kManga.source, kManga.url || kManga.public_url);
        
        // Add to Builder (Handles Linking automatically)
        builder.addManga({
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
        }, info.id, info.name);
    });

    const payload = builder.getPayload();
    
    // Validation Log
    console.log(`✅ Processed ${payload.backupManga.length} manga.`);
    console.log(`✅ Registered ${payload.backupSources.length} unique sources.`);

    const message = BackupMessage.create(payload);
    const buffer = BackupMessage.encode(message).finish();
    const gzipped = zlib.gzipSync(buffer);
    
    fs.writeFileSync(path.join(OUTPUT_DIR, 'Backup.tachibk'), gzipped);
    console.log('✅ Created output/Backup.tachibk');
}

main().catch(e => { console.error(e); process.exit(1); });
                                
