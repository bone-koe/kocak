import asyncio
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

# --- KONFIGURASI MABES ENTERPRISE: CARRYFLIX V1 (FIREBASE INTERCEPTOR) ---
TARGET_URL = "https://carryflix.com/"
OUTPUT_FILE = "CarryFlix_BoneTV.m3u8"
DUMMY_LINK = "https://raw.githubusercontent.com/iwanfalstv/Nyetlu/refs/heads/main/njing/output.m3u8"

# Ekstraktor cerdas untuk membelah respons kotor WebChannel Firebase
def extract_json_objects(text):
    objects = []
    idx = 0
    while True:
        start = text.find('{"documentChange"', idx)
        if start == -1:
            break
        
        count = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                count += 1
            elif text[i] == '}':
                count -= 1
                if count == 0:
                    try:
                        obj = json.loads(text[start:i+1])
                        objects.append(obj)
                    except: pass
                    idx = i + 1
                    break
        else:
            break 
    return objects

async def intercept_firebase(context):
    page = await context.new_page()
    firebase_payload = ""

    # Memasang alat sadap jaringan untuk mencegat jalur Listen/channel
    async def handle_response(response):
        nonlocal firebase_payload
        if "/Listen/channel" in response.url and response.request.method == "POST":
            try:
                body = await response.text()
                if "documentChange" in body:
                    firebase_payload += body
            except: pass

    page.on("response", handle_response)

    print("📡 Tank Playwright diluncurkan. Mengendus sinyal Firebase...")
    try:
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=20000)
        
        # Beri waktu 5 detik agar web menarik data penuh dari database
        for _ in range(5):
            if firebase_payload: break
            await asyncio.sleep(1)
            
    except Exception as e:
        print(f"⚠️ Peringatan Kendala Navigasi: {e}")
    finally:
        await page.close()

    return firebase_payload

async def main():
    print("🚀 Memulai Operasi MABES ENTERPRISE: CarryFlix Engine V1...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        )
        
        raw_payload = await intercept_firebase(context)
        await browser.close()

    if not raw_payload:
        print("❌ Gagal menyadap sinyal Firebase CarryFlix.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:-1, [ERROR] CarryFlix Firebase Gagal Disadap\n{DUMMY_LINK}")
        return

    print("🎯 Sinyal berhasil disadap! Membedah brankas data...")
    documents = extract_json_objects(raw_payload)
    
    all_streams = []
    now_utc = datetime.now(timezone.utc)

    for doc in documents:
        doc_data = doc.get("documentChange", {}).get("document", {})
        fields = doc_data.get("fields", {})
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
            
            # Kita hanya rampas jalur HLS, DASH/Shaka, dan ClearKey. Buang iframe_sandbox!
            if srv_type not in ["hls", "clearkey", "shaka"]: continue

            srv_name = srv_fields.get("name", {}).get("stringValue", "Server")
            original_url = srv_fields.get("url", {}).get("stringValue", "")
            user_agent = srv_fields.get("userAgent", {}).get("stringValue", "")
            drm_key_id = srv_fields.get("drmKeyId", {}).get("stringValue", "")
            drm_key = srv_fields.get("drmKey", {}).get("stringValue", "")

            if not original_url: continue

            # Logika Manipulasi Dummy
            final_url = DUMMY_LINK if is_upcoming else original_url

            base_title = f"[{status_icon}] [{kickoff_wib}] {category_tag}{title} [{srv_name}]"
            
            stream_block = [f'#EXTINF:-1 tvg-logo="{thumb}" group-title="{group_title}",{base_title}']

            # Injeksi User Agent
            if user_agent and not is_upcoming:
                stream_block.append(f'#EXTVLCOPT:http-user-agent={user_agent}')

            # 🛡️ INJEKSI KODE RAHASIA DRM CLEARKEY (Hanya jika LIVE/VOD dan punya Kunci)
            if srv_type == "clearkey" and drm_key_id and drm_key and not is_upcoming:
                stream_block.append(f'#KOD-PROP:inputstream=inputstream.adaptive')
                stream_block.append(f'#KOD-PROP:inputstream.adaptive.manifest_type=mpd')
                stream_block.append(f'#KOD-PROP:inputstream.adaptive.license_type=clearkey')
                stream_block.append(f'#KOD-PROP:inputstream.adaptive.license_key={drm_key_id}:{drm_key}')

            stream_block.append(final_url)
            stream_block.append("")
            
            all_streams.append(stream_block)
            print(f"  ✅ Terkunci: {base_title}")

    # Membangun Berkas
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

if __name__ == "__main__":
    asyncio.run(main())
