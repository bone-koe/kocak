import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

# --- KONFIGURASI MABES ENTERPRISE: CARRYFLIX VOD HUNTER ---
TARGET_URL = "https://carryflix.com/replays"
OUTPUT_FILE = "CarryFlix_VOD_BoneTV.m3u8"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

async def main():
    print("🚀 Memulai Operasi MABES ENTERPRISE: CarryFlix VOD Hunter...")
    all_streams = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={'width': 1280, 'height': 720}, user_agent=USER_AGENT)
        page = await context.new_page()

        # 📡 ALAT SADAP JARINGAN (Menangkap M3U8 di udara)
        current_m3u8 = None
        current_referer = "https://carryflix.com/"

        async def handle_request(request):
            nonlocal current_m3u8, current_referer
            if ".m3u8" in request.url:
                # Prioritaskan link utama (hindari chunk)
                if not current_m3u8 or "master" in request.url or "index" in request.url:
                    current_m3u8 = request.url
                    current_referer = request.headers.get("referer", "https://carryflix.com/")

        page.on("request", handle_request)

        print("🔍 Membuka Halaman Replay Utama...")
        try:
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=20000)
            await page.wait_for_selector('.bg-cf-card', timeout=15000)
        except Exception as e:
            print("❌ Gagal memuat halaman Replay. Target down atau dilindungi Cloudflare.")
            await browser.close()
            return

        # Hitung jumlah VOD yang tersedia
        card_count = await page.locator('.bg-cf-card').count()
        # Kita batasi 20 VOD terbaru agar proses GitHub Actions tidak terlalu lama
        limit = min(card_count, 20)
        print(f"🎯 Ditemukan {card_count} VOD di layar. Mengunci {limit} target terbaru...")

        for i in range(limit):
            try:
                # Kembali ke halaman depan agar state bersih
                await page.goto(TARGET_URL, wait_until="networkidle")
                await page.wait_for_selector('.bg-cf-card', timeout=10000)
                
                card = page.locator('.bg-cf-card').nth(i)
                
                # Ekstrak Judul dan Thumbnail
                title_el = card.locator('h3')
                raw_title = await title_el.inner_text() if await title_el.count() > 0 else f"Unknown VOD {i+1}"
                clean_title = raw_title.replace('\n', ' ').strip()
                
                img_el = card.locator('img')
                thumb = await img_el.get_attribute('src') if await img_el.count() > 0 else ""

                print(f"\n⚡ Mendobrak masuk ke: {clean_title}")
                current_m3u8 = None # Reset tangkapan
                
                # Eksekusi Klik Target
                await card.click()
                await page.wait_for_selector('.wn-title', timeout=15000)
                await page.wait_for_timeout(3000) # Tunggu autoplay memicu jaringan

                # Cari apakah ada tombol pemisah Babak (1st Half / 2nd Half)
                tabs = page.locator('.wb-srv-btn')
                tab_count = await tabs.count()

                if tab_count > 0:
                    for j in range(tab_count):
                        tab_name = await tabs.nth(j).inner_text()
                        current_m3u8 = None
                        
                        await tabs.nth(j).click()
                        await page.wait_for_timeout(3000) # Tunggu M3U8 lewat
                        
                        if current_m3u8:
                            print(f"    ✅ Sukses menyadap: [{tab_name}] -> {current_m3u8[:40]}...")
                            display_title = f"[VOD] {clean_title} [{tab_name}]"
                            all_streams.append({
                                "title": display_title,
                                "url": current_m3u8,
                                "referer": current_referer,
                                "logo": thumb
                            })
                        else:
                            print(f"    ⚠️ Gagal menyadap link untuk [{tab_name}].")
                else:
                    # Jika pertandingan utuh tanpa pembagian babak
                    if current_m3u8:
                        print(f"    ✅ Sukses menyadap: {current_m3u8[:40]}...")
                        all_streams.append({
                            "title": f"[VOD] {clean_title}",
                            "url": current_m3u8,
                            "referer": current_referer,
                            "logo": thumb
                        })
                    else:
                        print("    ⚠️ Gagal menyadap M3U8 utama.")

            except Exception as e:
                print(f"  ❌ Gagal memproses kartu ke-{i+1}: {e}")
                continue

        await browser.close()

    # --- MEMBANGUN BERKAS FISIK M3U8 ---
    print("\n🎯 Membangun berkas M3U8 VOD...")
    ts = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M WIB")
    header = ['#EXTM3U', f'# Last Updated: {ts}', '']
    
    playlist_lines = []
    for stream in all_streams:
        extinf = f'#EXTINF:-1 tvg-logo="{stream["logo"]}" group-title="VOD - CarryFlix",{stream["title"]}'
        playlist_lines.append(extinf)
        playlist_lines.append(f'#EXTVLCOPT:http-referer={stream["referer"]}')
        playlist_lines.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        playlist_lines.append(stream["url"])
        playlist_lines.append("")

    if playlist_lines:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(header + playlist_lines))
        print(f"🏁 BERHASIL! {len(all_streams)} VOD dikunci ke {OUTPUT_FILE}")
    else:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(header + ["# Tidak ada VOD yang berhasil disadap saat ini."]))
        print("💀 Selesai tanpa hasil buruan.")

if __name__ == "__main__":
    asyncio.run(main())
