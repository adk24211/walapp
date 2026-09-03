/**
 * 글자 대비 상시 점검 — WCAG AA(4.5:1, 큰 글자 3:1) 미달을 찾는다.
 *
 * 왜 도구로 만들었나: 색은 눈으로 "좀 옅네" 까지만 알 수 있고 몇 대 몇인지는
 * 모른다. 실제로 이 사이트는 오래 "조용한 회색" 이라고 부르던 --ink3 이
 * 2.47~2.82:1 이었다. /support/ 한 페이지에서만 12px 회색 글자가 559개였다.
 * 어르신 대상 제도를 72건 싣고 '만 65세 이상' 이라고 적어 두는 사이트가
 * 그 값으로 갈 수는 없다.
 *
 * 배경은 조상으로 거슬러 올라가 처음 만나는 불투명한 색을 쓴다(브라우저가
 * 실제로 합성하는 것과 같은 순서). 반투명 글자색은 그 배경 위에 미리 섞는다.
 *
 * 라이트·다크 두 테마를 모두 본다 — 한쪽만 고치면 다른 쪽이 뒤집혀 깨진다.
 * 실제로 skip-link 가 그랬다: 라이트에서 배경을 진하게 바꾸면 다크에서는
 * 같은 변수가 밝은 민트라 흰 글자가 그 위에 얹힌다.
 *
 * 사용:
 *   bundle exec jekyll build -d _site_check
 *   node scripts/check_contrast.mjs            # 미달이 있으면 exit 1
 */
import { chromium } from 'playwright';
import http from 'http';
import fs from 'fs';
import path from 'path';

const ARG = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : null;
const CANDIDATES = ARG ? [ARG] : ['_site_check', '_site'];
const ROOT = CANDIDATES.map((c) => path.resolve(process.cwd(), c)).find((c) => fs.existsSync(c));
const BASEURL = '/walapp';
const PORT = 4711;

if (!ROOT) {
  console.error(`빌드 결과를 찾지 못했습니다(${CANDIDATES.join(', ')}). 먼저 jekyll build 를 실행하세요.`);
  process.exit(1);
}

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.json': 'application/json', '.xml': 'application/xml', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
};

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p.startsWith(BASEURL)) p = p.slice(BASEURL.length);
  let f = path.join(ROOT, p);
  if (f.endsWith('/') || (fs.existsSync(f) && fs.statSync(f).isDirectory())) f = path.join(f, 'index.html');
  if (!fs.existsSync(f)) { res.writeHead(404); return res.end('404'); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});

function firstDetail() {
  const base = path.join(ROOT, 'support');
  if (!fs.existsSync(base)) return null;
  for (const cat of fs.readdirSync(base)) {
    const dir = path.join(base, cat);
    if (!fs.statSync(dir).isDirectory()) continue;
    for (const slug of fs.readdirSync(dir)) {
      if (fs.existsSync(path.join(dir, slug, 'index.html'))) return `/support/${cat}/${slug}/`;
    }
  }
  return null;
}

/* 화면마다 색을 쓰는 방식이 다르다. 대상별 색인은 분야 색 점을,
   제도 상세는 카드 머리줄 표시를, 마감 예정은 긴급 색을 쓴다. */
const PAGES = [
  ['홈', '/'],
  ['대상별 색인', '/who/'],
  ['대상 허브', '/who/youth/'],
  ['전체 제도', '/support/'],
  ['마감 예정', '/deadline/'],
];
const detail = firstDetail();
if (detail) PAGES.push(['제도 상세', detail]);

/** 페이지 안의 모든 글자 노드에서 전경/배경을 실제로 합성해 비율을 낸다. */
function scan() {
  const lum = (c) => {
    const s = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2];
  };
  const parse = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 };
  };
  // 브라우저가 실제로 합성하는 순서 — 위로 올라가며 처음 만나는 불투명한 면.
  const bgOf = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c.a > 0.05) return c.rgb;
      n = n.parentElement;
    }
    const root = parse(getComputedStyle(document.documentElement).backgroundColor);
    return root && root.a > 0.05 ? root.rgb : [255, 255, 255];
  };

  const seen = new Map();
  for (const el of document.querySelectorAll('body *')) {
    // 자기 자신이 직접 가진 글자만 본다. 안 그러면 부모가 자식 글자를 대신 세어
    // 같은 글자가 조상 수만큼 중복된다.
    const txt = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join('');
    if (!txt) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const fg = parse(cs.color);
    if (!fg) continue;
    const bg = bgOf(el);
    const front = fg.a === 1 ? fg.rgb : fg.rgb.map((v, i) => v * fg.a + bg[i] * (1 - fg.a));
    const L1 = lum(front), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const px = parseFloat(cs.fontSize), w = parseInt(cs.fontWeight) || 400;
    // WCAG 의 '큰 글자' — 24px 이상, 또는 굵으면 18.66px 이상.
    const need = (px >= 24 || (px >= 18.66 && w >= 700)) ? 3 : 4.5;
    if (ratio >= need) continue;
    const cls = (el.className || el.tagName).toString().trim().slice(0, 44);
    const key = `${cls}|${Math.round(ratio * 100)}`;
    if (seen.has(key)) { seen.get(key).n++; continue; }
    seen.set(key, { cls, ratio: +ratio.toFixed(2), need, px: +px.toFixed(1), w, sample: txt.slice(0, 30), n: 1 });
  }
  return [...seen.values()].sort((a, b) => a.ratio - b.ratio);
}

await new Promise((r) => server.listen(PORT, r));
// PLAYWRIGHT_BROWSERS_PATH 아래 chromium 이 있으면 그걸 쓴다. 없으면 기본 경로.
const exe = ['/opt/pw-browsers/chromium'].find((p) => fs.existsSync(p));
const browser = await chromium.launch(exe ? { executablePath: exe } : {});

let failed = 0;
for (const theme of ['라이트', '다크']) {
  console.log(`\n══ ${theme} 테마 ══`);
  for (const [name, url] of PAGES) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
    // 바깥 요청(폰트·애널리틱스·광고)은 막는다. 이 검사는 색만 보는데 networkidle
    // 이 막힌 호스트를 기다리느라 페이지당 몇십 초씩 걸렸다.
    await page.route('**/*', (route) => {
      const u = route.request().url();
      return u.startsWith(`http://127.0.0.1:${PORT}`) ? route.continue() : route.abort();
    });
    if (theme === '다크') {
      // ⚠️ 키 이름이 정확해야 한다. 사이트의 인라인 스크립트가 파싱 시점에
      //    'walapp-theme' 을 읽어 html 에 data-theme 을 단다. 그 경로로 태워야
      //    전환 애니메이션 없이 처음부터 다크로 그려진다.
      //
      //    처음엔 키를 틀린 채 로드 뒤에 setAttribute 로 바꿨는데, body 에
      //    `transition: background .2s` 가 걸려 있어 배경만 아직 밝은 채로
      //    측정됐다. 글자색은 즉시 다크 값이 되고 배경은 아직 라이트여서
      //    1.05:1 같은 값이 33종씩 쏟아졌다 — 전부 측정 오류였다.
      await page.addInitScript(() => {
        try { localStorage.setItem('walapp-theme', 'dark'); } catch (e) {}
      });
    }
    await page.goto(`http://127.0.0.1:${PORT}${BASEURL}${url}`, { waitUntil: 'domcontentloaded' });
    const applied = await page.evaluate(() => document.documentElement.getAttribute('data-theme') === 'dark');
    if ((theme === '다크') !== applied) {
      console.error(`  ! ${name}: 테마가 걸리지 않았습니다(원한 것 ${theme}). 검사 중단.`);
      process.exit(2);
    }
    const rows = await page.evaluate(scan);
    await page.close();
    if (!rows.length) { console.log(`  ✓ ${name}`); continue; }
    failed += rows.length;
    console.log(`  ✗ ${name} — ${rows.length}종`);
    for (const r of rows) {
      console.log(`      ${String(r.ratio).padStart(5)} / ${r.need}   ${r.px}px w${r.w} ×${r.n}   .${r.cls}   "${r.sample}"`);
    }
  }
}
await browser.close();
server.close();

if (failed) {
  console.log(`\n대비 미달 ${failed}종. 색을 바꾸거나(권장) 글자를 키우세요.`);
  process.exit(1);
}
console.log('\n전부 통과 — 라이트·다크 두 테마 모두 WCAG AA 이상');
