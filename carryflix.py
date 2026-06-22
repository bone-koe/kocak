import asyncio
import re
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

# --- KONFIGURASI MABES ENTERPRISE: SNIPER REST API V2 ---
TARGET_URL = "https://carryflix.com/"
OUTPUT_FILE = "CarryFlix_BoneTV.m3u8"
DUMMY_LINK = "https://raw.githubusercontent.com/iwanfalstv/Nyetlu/refs/heads/main/njing/output.m3u8"

# Karena kita menebak pintu belakang, ini adalah daftar nama tabel database yang paling umum dipakai
COLLECTIONS_TO_TRY = ["streams", "channels", "live", "matches", "events"]

async def hunt_firebase_keys():
    print("🕵️‍♂️ Tank Playwright diterjunkan. Menyisir Kunci Master di file JavaScript...")
    config = {"api_key": None, "project_id": None}

    async def handle_response(response):
        # Jika kunci sudah lengkap, abaikan file lain untuk hemat waktu
        if config["api_key"] and config["project_id"]: return
        
        # Hanya sadap file berjenis skrip atau dokumen utama
        if response.request.resource_type in ["script", "document"]:
            try:
                text = await response.text()
                # 🔑 Deteksi Kunci API Google
                if not config["api_key"]:
                    match_api = re.search(r'(AIza[a-zA-Z0-9_-]{35})', text)
                    if match_api: 
                        config["api_key"] = match_api.group(1)
                        print(f"  [+] Kunci Master Ditemukan: {config['api_key'][:15]}...")
                        
                # 🏢 Deteksi Project ID Firebase
                if not config["project_id"]:
                    match_proj = re.search(r'projectId["\']?\s*:\s*["\']([^"\']+)["\']', text)
                    if match_proj: 
                        config["project_id"] = match_proj.group(1)
                        print(f"  [+] Project ID Ditemukan: {config['project_id']}")
            except: pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context()
        page = await context.new_page()
        page.on("response", handle_response)
        
        try:
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=15000)
            # Beri waktu 5 detik agar robot sempat membaca regex
            for _ in range(5):
                if config["api_key"] and config["project_id"]: break
                await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️ Peringatan Navigasi: {e}")
        finally:
            await browser.close()
            
    return config

def fetch_firestore_data(api_key, project_id):
    print("🚀 Kunci siap! Menembak pintu belakang REST API Firestore...")
    documents = []
    
    for collection in COLLECTIONS_TO_TRY:
        url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/{collection}?key={api_key}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                docs = data.get("documents", [])
                if docs:
                    print(f"  🎯 BINGO! Data berhasil disedot dari tabel: '{collection}'")
                    documents.extend(docs)
                    break # Berhenti mencari jika sudah dapat data
            else:
                print(f"  [-] Tabel '{collection}' kosong atau dikunci.")
        except Exception as e:
            print(f"  [!] Gagal menembak tabel '{collection}': {e}")
            
    return documents

def build_m3u8(documents):
    if not documents:
        print("❌ Gagal mendapatkan data siaran. Database kosong.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:-1, [ERROR] Tidak Ada Data Aktif di CarryFlix\n{DUMMY_LINK}")
        return

    print("🎯 Membedah brankas data dan merakit M3U8...")
    all_streams = []
    now_utc = datetime.now(timezone.utc)

    for doc in documents:
        # Format JSON REST API sedikit lebih bersih daripada WebChannel
        fields = doc.get("fields", {})
        if not fields: continue

        title = fields.get("title", {}).get("stringValue", "Unknown Match")
        thumb = fields.get("thumbnail", {}).get("stringValue", "")
        is_replay = fields.get("isReplay", {}).get("booleanValue", False)
        start_time_str = fields.get("startTime", {}).get("stringValue", "")
        desc_str = fields.get("description", {}).get("stringValue", "")
        servers_val = fields.get("servers", {}).get("arrayValue", {}).get("values", [])

        # Kategori Cerdas
        category_tag = ""
        if "Kategori:" in desc_str:
            clean_cat = desc_str.split("Kategori:")[1].strip().upper()
            category_tag = f"[{clean_cat}] "

        # Format WIB
        kickoff_wib = "UNKNOWN"
        start_dt = None
        if start_time_str:
            try:
                start_dt = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                kickoff_wib = start_dt.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%H:%M WIB %d/%m")
            except: pass

        # Radar Waktu (1 Jam Pre-Match)
        status_icon = ""
        group_title = ""
        is_upcoming = False

        if is_replay:
            status_icon = "VOD"
            group_title = "VOD - CarryFlix"
        elif start_dt:
            time_to_kickoff = (start_dt - now_utc).total_seconds()
            
            if time_to_kickoff > 3600: # Lebih dari 1 Jam
                status_icon = "⏳ UPCOMING"
                group_title = "UPCOMING - CarryFlix"
                is_upcoming = True
            elif -18000 <= time_to_kickoff <= 3600: # Masuk radius 1 Jam sampai 5 jam kedepan
                status_icon = "🔴 LIVE"
                group_title = "LIVE - CarryFlix"
            else:
                continue # Expired / Selesai

        if not status_icon: continue

        for srv in servers_val:
            srv_fields = srv.get("mapValue", {}).get("fields", {})
            srv_type = srv_fields.get("type", {}).get("stringValue", "")
            
            if srv_type not in ["hls", "clearkey", "shaka"]: continue

            srv_name = srv_fields.get("name", {}).get("stringValue", "Server")
            original_url = srv_fields.get("url", {}).get("stringValue", "")
            user_agent = srv_fields.get("userAgent", {}).get("stringValue", "")
            drm_key_id = srv_fields.get("drmKeyId", {}).get("stringValue", "")
            drm_key = srv_fields.get("drmKey", {}).get("stringValue", "")

            if not original_url: continue

            # Dummy jika Upcoming
            final_url = DUMMY_LINK if is_upcoming else original_url

            base_title = f"[{status_icon}] [{kickoff_wib}] {category_tag}{title} [{srv_name}]"
            stream_block = [f'#EXTINF:-1 tvg-logo="{thumb}" group-title="{group_title}",{base_title}']

            # Inject User Agent
            if user_agent and not is_upcoming:
                stream_block.append(f'#EXTVLCOPT:http-user-agent={user_agent}')

            # Inject Kunci DRM
            if srv_type == "clearkey" and drm_key_id and drm_key and not is_upcoming:
                stream_block.append(f'#KOD-PROP:inputstream=inputstream.adaptive')
                stream_block.append(f'#KOD-PROP:inputstream.adaptive.manifest_type=mpd')
                stream_block.append(f'#KOD-PROP:inputstream.adaptive.license_type=clearkey')
                stream_block.append(f'#KOD-PROP:inputstream.adaptive.license_key={drm_key_id}:{drm_key}')

            stream_block.append(final_url)
            stream_block.append("")
            
            all_streams.append(stream_block)
            print(f"  ✅ Terkunci: {base_title}")

    # Finishing Sentuhan Berkas
    ts = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M WIB")
    header = ['#EXTM3U', f'# Last Updated: {ts}', '']
    
    if all_streams:
        flat_list = [item for sublist in all_streams for item in sublist]
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(header + flat_list))
        print(f"\n🏁 BERHASIL! {len(all_streams)} Channel CarryFlix siap tayang di {OUTPUT_FILE}.")
    else:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(header + ["# Tidak ada siaran aktif dalam radar."]))
        print("\n💀 Operasi selesai tanpa hasil buruan.")

async def main():
    print("🚀 Memulai Operasi MABES ENTERPRISE: CarryFlix API Hunter...")
    
    # Langkah 1: Curi Kunci
    keys = await hunt_firebase_keys()
    
    if not keys["api_key"] or not keys["project_id"]:
        print("❌ Operasi Gagal: Kunci API atau Project ID tidak ditemukan di CarryFlix.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:-1, [ERROR] Kunci Master Gagal Disadap\n{DUMMY_LINK}")
        return
        
    # Langkah 2: Tembak Pintu Belakang REST API
    documents = fetch_firestore_data(keys["api_key"], keys["project_id"])
    
    # Langkah 3: Ekstraksi DRM & M3U8
    build_m3u8(documents)

if __name__ == "__main__":
    asyncio.run(main())
