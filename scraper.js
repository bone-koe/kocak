const { chromium } = require('playwright');
const fs = require('fs');

const DUMMY_URL = "https://raw.githubusercontent.com/iwanfalstv/Nyetlu/refs/heads/main/njing/output.m3u8";

(async () => {
  const browser = await chromium.launch({ 
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-blink-features=AutomationControlled'
    ]
  });
  
  const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
  const context = await browser.newContext({ userAgent: userAgent });
  const page = await context.newPage();

  context.on('page', async popup => {
    try { await popup.close(); } catch (e) {}
  });

  console.log('Membuka beranda XYZStreams...');
  await page.goto('https://xyzstreams.st/', { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});

  const events = await page.$$eval('.events-grid .event-card', cards => {
    return cards.map(card => {
      const title = card.querySelector('h3')?.innerText || 'Unknown Match';
      const startTime = card.getAttribute('data-start');
      const statusText = card.querySelector('.event-status-badge')?.innerText?.trim() || '';
      const href = card.getAttribute('href');
      
      let logo = '';
      const bgStyle = card.getAttribute('style') || '';
      const match = bgStyle.match(/url\(["']?(.*?)["']?\)/);
      if (match && match[1]) logo = match[1];

      return { title, startTime, statusText, logo, href };
    });
  }).catch(() => []);

  console.log(`Berhasil memetakan ${events.length} jadwal pertandingan.`);

  const streamOrigin = "https://xyzstreams.st";
  const streamReferer = "https://xyzstreams.st/";
  const nowOptions = { timeZone: "Asia/Jakarta", year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' };
  const lastUpdate = new Date().toLocaleString("en-US", nowOptions).replace(/\./g, ':');

  // Mode diubah ke JW Player API Extraction
  let m3u8Data = `#EXTM3U\n# Last Updated: ${lastUpdate} WIB\n# Mode: JW Player API Extraction\n\n`;

  for (const ev of events) {
    if (ev.statusText.toLowerCase() === 'ended') continue;

    let timeText = "";
    let isLive = false;

    if (ev.startTime) {
      const start = new Date(ev.startTime);
      const timeFormatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', hour12: false
      });
      timeText = ` ${timeFormatter.format(start)} WIB`;
      if (new Date() >= start) isLive = true;
    }

    if (ev.statusText.toLowerCase().includes('live')) isLive = true;
    const statusPrefix = isLive ? "🔴 LIVE" : "⏳ UPCOMING";
    
    console.log(`\nMemproses pertandingan: ${ev.title}`);
    const matchPage = await context.newPage();
    let hasAnyStream = false;

    try {
      const fullMatchUrl = new URL(ev.href, 'https://xyzstreams.st/').href;
      await matchPage.goto(fullMatchUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
      
      // Membuang overlay iklan
      await matchPage.mouse.click(10, 10);
      await matchPage.waitForTimeout(1000);

      const buttons = await matchPage.$$('.streambutton, .channel-btn, [class*="btn"]');
      console.log(`-> Menemukan ${buttons.length} tombol saluran.`);

      for (let i = 0; i < buttons.length; i++) {
        const buttonText = await matchPage.evaluate(el => el.innerText, buttons[i]).catch(() => `CH ${i+1}`);
        const chNumber = i + 1;

        console.log(`   -> Mengklik CH ${chNumber}: ${buttonText.trim()}`);
        
        await buttons[i].click({ force: true }).catch(() => {});
        
        // --- INTI STRATEGI BARU: BERTANYA LANGSUNG KE JW PLAYER ---
        // Skrip akan masuk ke dalam browser dan memaksa JW Player menyerahkan URL-nya
        const capturedM3u8 = await matchPage.evaluate(async () => {
          return new Promise(resolve => {
            let attempts = 0;
            const interval = setInterval(() => {
              attempts++;
              try {
                // Mengecek apakah JW Player sudah siap dan memiliki antrean file
                if (typeof jwplayer === 'function' && jwplayer().getPlaylistItem()) {
                  const fileUrl = jwplayer().getPlaylistItem().file;
                  if (fileUrl && fileUrl.includes('.m3u8')) {
                    clearInterval(interval);
                    resolve(fileUrl);
                  }
                }
              } catch (e) {
                // Abaikan error jika jwplayer belum sepenuhnya dimuat
              }
              
              // Timeout setelah ~5 detik (20 percobaan x 250ms)
              if (attempts >= 20) {
                clearInterval(interval);
                resolve(null);
              }
            }, 250);
          });
        });
        // ---------------------------------------------------------

        if (capturedM3u8) {
          console.log(`      [BERHASIL] Tautan diekstrak dari Player: ${capturedM3u8}`);
          hasAnyStream = true;

          let displayTitle = `[${statusPrefix}${timeText}] ${ev.title} (${buttonText.trim()})`;
          m3u8Data += `#EXTINF:-1 tvg-logo="${ev.logo}" group-title="XYZ STREAMS",${displayTitle}\n`;
          m3u8Data += `#EXTVLCOPT:http-referrer=${streamReferer}\n`;
          m3u8Data += `#EXTVLCOPT:http-origin=${streamOrigin}\n`;
          m3u8Data += `#EXTVLCOPT:http-user-agent=${userAgent}\n`;
          m3u8Data += `${capturedM3u8}\n\n`;
        } else {
          console.log(`      [KOSONG] JW Player tidak mengembalikan tautan m3u8.`);
        }
      }
    } catch (err) {
      console.log(`-> Kegagalan navigasi/scraping: ${err.message}`);
    }

    await matchPage.close();

    if (!hasAnyStream) {
      console.log(`-> Pertandingan belum merilis video m3u8. Mengalihkan ke tautan dummy.`);
      let displayTitle = `[${statusPrefix}${timeText}] ${ev.title} (Belum Mulai/Tidak Tersedia)`;
      m3u8Data += `#EXTINF:-1 tvg-logo="${ev.logo}" group-title="XYZ STREAMS",${displayTitle}\n`;
      m3u8Data += `#EXTVLCOPT:http-user-agent=${userAgent}\n`;
      m3u8Data += `${DUMMY_URL}\n\n`;
    }
  }

  fs.writeFileSync('output.m3u8', m3u8Data);
  console.log('\n✅ Berkas output.m3u8 sukses diselesaikan!');
  await browser.close();
})();
