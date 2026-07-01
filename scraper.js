const { chromium } = require('playwright');
const fs = require('fs');

const DUMMY_URL = "https://raw.githubusercontent.com/iwanfalstv/Nyetlu/refs/heads/main/njing/output.m3u8";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Otomatis menutup tab popup iklan secepat kilat
  context.on('page', async popup => {
    try { await popup.close(); } catch (e) {}
  });

  console.log('Membuka beranda XYZStreams...');
  await page.goto('https://xyzstreams.st/', { waitUntil: 'domcontentloaded', timeout: 30000 });

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
  });

  console.log(`Berhasil memetakan ${events.length} jadwal pertandingan.`);

  const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36";
  const streamOrigin = "https://xyzstreams.st";
  const streamReferer = "https://xyzstreams.st/";

  const nowOptions = { timeZone: "Asia/Jakarta", year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' };
  const lastUpdate = new Date().toLocaleString("en-US", nowOptions).replace(/\./g, ':');

  let m3u8Data = `#EXTM3U\n# Last Updated: ${lastUpdate} WIB\n# Mode: Playwright Server 1 Matrix Interception\n\n`;

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
      
      // KLIK PANCINGAN: Klik koordinat 10,10 untuk membuang lapisan pop-up iklan
      await matchPage.mouse.click(10, 10);
      await matchPage.waitForTimeout(1000);

      await matchPage.selectOption('#server-select', 'Server 1').catch(() => {});
      await matchPage.waitForTimeout(1000);

      const buttons = await matchPage.$$('#dynamic-buttons .streambutton');
      console.log(`-> Menemukan ${buttons.length} tombol saluran pada Server 1.`);

      for (let i = 0; i < buttons.length; i++) {
        const buttonText = await matchPage.evaluate(el => el.innerText, buttons[i]);
        const chNumber = i + 1;
        let capturedM3u8 = null;

        console.log(`   -> Mengklik CH ${chNumber}: ${buttonText}`);
        
        // DOUBLE CLICK: Memastikan tombol benar-benar tereksekusi
        await buttons[i].click({ force: true }).catch(() => {});
        await matchPage.waitForTimeout(500);
        await buttons[i].click({ force: true }).catch(() => {});

        // ACTIVE LISTENER: Menunggu maksimal 5 detik hingga request m3u8 muncul di network
        try {
          const request = await matchPage.waitForRequest(req => req.url().includes('.m3u8'), { timeout: 5000 });
          capturedM3u8 = request.url();
        } catch (e) {
          // Timeout tercapai, artinya tidak ada request m3u8 yang lewat
        }

        // CADANGAN: Mencari m3u8 di dalam atribut 'src' iframe jika network sniffer lolos
        if (!capturedM3u8) {
          const iframeSrcs = await matchPage.$$eval('iframe', frames => frames.map(f => f.src));
          for (let src of iframeSrcs) {
            const urlMatch = src.match(/(https?:\/\/[^\s"'<>]+\.m3u8)/);
            if (urlMatch) capturedM3u8 = urlMatch[1];
          }
        }

        if (capturedM3u8) {
          console.log(`      [BERHASIL] Tautan didapatkan: ${capturedM3u8}`);
          hasAnyStream = true;

          let displayTitle = `[${statusPrefix}${timeText}] ${ev.title} (CH ${chNumber} - ${buttonText})`;
          m3u8Data += `#EXTINF:-1 tvg-logo="${ev.logo}" group-title="XYZ STREAMS",${displayTitle}\n`;
          m3u8Data += `#EXTVLCOPT:http-referrer=${streamReferer}\n`;
          m3u8Data += `#EXTVLCOPT:http-origin=${streamOrigin}\n`;
          m3u8Data += `#EXTVLCOPT:http-user-agent=${userAgent}\n`;
          m3u8Data += `${capturedM3u8}\n\n`;
        } else {
          console.log(`      [KOSONG] Tidak ada aktivitas m3u8.`);
        }
      }
    } catch (err) {
      console.log(`-> Kegagalan navigasi: ${err.message}`);
    }

    await matchPage.close();

    if (!hasAnyStream) {
      console.log(`-> Pertandingan belum merilis video m3u8. Mengalihkan ke tautan dummy.`);
      let displayTitle = `[${statusPrefix}${timeText}] ${ev.title} (Belum Mulai)`;
      m3u8Data += `#EXTINF:-1 tvg-logo="${ev.logo}" group-title="XYZ STREAMS",${displayTitle}\n`;
      m3u8Data += `#EXTVLCOPT:http-user-agent=${userAgent}\n`;
      m3u8Data += `${DUMMY_URL}\n\n`;
    }
  }

  fs.writeFileSync('output.m3u8', m3u8Data);
  console.log('\n✅ Berkas output.m3u8 sukses diselesaikan!');
  await browser.close();
})();
