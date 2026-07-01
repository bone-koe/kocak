const { chromium } = require('playwright');
const fs = require('fs');

const DUMMY_URL = "https://raw.githubusercontent.com/iwanfalstv/Nyetlu/refs/heads/main/njing/output.m3u8";

(async () => {
  console.log('Memulai investigasi dengan Playwright...');
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

  // 📸 TANGKAPAN LAYAR 1: Cek apakah diblokir Cloudflare di beranda
  await page.waitForTimeout(2000); 
  await page.screenshot({ path: 'debug-1-beranda.png', fullPage: true });
  console.log('📸 [DEBUG] Tangkapan layar beranda disimpan: debug-1-beranda.png');

  const events = await page.$$eval('.events-grid .event-card', cards => {
    return cards.map(card => {
      const title = card.querySelector('h3')?.innerText || 'Unknown Match';
      const startTime = card.getAttribute('data-start');
      const statusText = card.querySelector('.event-status-badge')?.innerText?.trim() || '';
      const href = card.getAttribute('href');
      return { title, startTime, statusText, href };
    });
  }).catch(() => []);

  // Kita batasi hanya memproses 1 pertandingan saja untuk uji coba debug agar cepat
  const testEvents = events.filter(ev => !ev.statusText.toLowerCase().includes('ended')).slice(0, 1);
  console.log(`\nMenemukan jadwal. Mengambil 1 pertandingan live/upcoming untuk debug...`);

  for (const ev of testEvents) {
    console.log(`Memproses pertandingan: ${ev.title}`);
    const matchPage = await context.newPage();
    
    let interceptedM3u8 = null;
    
    // Pasang Jaring
    matchPage.on('request', request => {
      const url = request.url();
      // Melonggarkan jaring: Cetak SEMUA request XHR/Fetch untuk melihat apa yang lewat
      if (request.resourceType() === 'xhr' || request.resourceType() === 'fetch') {
        if (url.includes('.m3u8') || url.includes('inproviszon.st')) {
            interceptedM3u8 = url;
            console.log(`      [JARING XHR/FETCH] Menangkap sesuatu: ${url}`);
        }
      }
    });

    try {
      const fullMatchUrl = new URL(ev.href, 'https://xyzstreams.st/').href;
      await matchPage.goto(fullMatchUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
      
      await matchPage.mouse.click(10, 10);
      await matchPage.waitForTimeout(2000); // Tunggu render player HLS.js

      // 📸 TANGKAPAN LAYAR 2: Cek kondisi player sebelum klik saluran
      await matchPage.screenshot({ path: 'debug-2-sebelum-klik.png' });
      console.log('📸 [DEBUG] Tangkapan layar player disimpan: debug-2-sebelum-klik.png');

      const buttons = await matchPage.$$('.streambutton, .channel-btn, [class*="btn"]');
      console.log(`-> Menemukan ${buttons.length} tombol saluran.`);

      if (buttons.length > 0) {
        // Klik tombol saluran pertama saja untuk uji coba
        const buttonText = await matchPage.evaluate(el => el.innerText, buttons[0]).catch(() => `CH 1`);
        console.log(`   -> Mengklik CH 1: ${buttonText.trim()}`);
        
        await buttons[0].click({ force: true }).catch(() => {});
        
        let waitTime = 0;
        while (!interceptedM3u8 && waitTime < 5000) {
            await matchPage.waitForTimeout(500);
            waitTime += 500;
        }

        // 📸 TANGKAPAN LAYAR 3: Cek kondisi player setelah diklik
        await matchPage.screenshot({ path: 'debug-3-sesudah-klik.png' });
        console.log('📸 [DEBUG] Tangkapan layar setelah klik disimpan: debug-3-sesudah-klik.png');
      }

    } catch (err) {
      console.log(`-> Kegagalan navigasi/scraping: ${err.message}`);
    }

    await matchPage.close();
  }

  await browser.close();
  console.log('\n✅ Debug selesai. Silakan periksa 3 file gambar debug di folder yang sama.');
})();
