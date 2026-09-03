/**
 * 레이아웃 상시 점검 — 데스크톱 · 태블릿 · 모바일 세 폭을 한 번에 본다.
 *
 * 디자인을 고칠 때마다 세 폭을 손으로 확인하다 빠뜨리는 일이 반복돼 도구로 만들었다.
 * 빌드 결과(_site_check 또는 _site)를 정적 서버로 띄우고 주요 페이지를 돌며 검사한다:
 *
 *   · 가로 넘침(스크롤바가 생기는지)
 *   · 컨테이너 밖으로 삐져나간 요소
 *   · 중복 주의 문구 (같은 취지의 고지가 한 화면에 두 번 이상)
 *   · 어절 중간 줄바꿈 ("제도만 모 / 아 보여 줍니다")
 *   · 페이지 높이 (스크롤 길이 추이)
 *
 * 사용:
 *   bundle exec jekyll build      # 또는 jekyll build
 *   node scripts/check_layout.mjs           # 검사만
 *   node scripts/check_layout.mjs --shots   # 스크린샷도 저장 (.layout-shots/)
 */
import { chromium } from 'playwright';
import http from 'http';
import fs from 'fs';
import path from 'path';

// 빌드 위치는 부르는 쪽이 정한다. check_inline_js.mjs 와 같은 이유 —
// '_site' 를 박아 두면 CI 가 쓰는 '_site_check' 에서 "빌드 결과가 없다" 로
// 떨어진다. 그쪽에서는 그게 배포를 통째로 막은 적이 있다.
// 첫 인자가 플래그(--shots)면 경로가 아니다.
const ARG = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : null;
const CANDIDATES = ARG ? [ARG] : ['_site_check', '_site'];
const ROOT = CANDIDATES
  .map((c) => path.resolve(process.cwd(), c))
  .find((c) => fs.existsSync(c)) || path.resolve(process.cwd(), CANDIDATES[0]);
const BASEURL = '/walapp';
const SHOTS = process.argv.includes('--shots');
const SHOT_DIR = path.resolve(process.cwd(), '.layout-shots');

const WIDTHS = [
  { w: 1440, name: '데스크톱' },
  { w: 768, name: '태블릿' },
  { w: 390, name: '모바일' },
];

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.json': 'application/json', '.xml': 'application/xml', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
};

if (!fs.existsSync(ROOT)) {
  console.error(`빌드 결과를 찾지 못했습니다(${CANDIDATES.join(', ')}). 먼저 jekyll build 를 실행하세요.`);
  process.exit(1);
}
console.log(`검사 대상: ${path.relative(process.cwd(), ROOT) || ROOT}`);

/** 검사할 페이지. 제도 상세는 빌드 결과에서 하나 골라 넣는다. */
function pages() {
  const list = [
    ['홈', '/'],
    ['전체 제도', '/support/'],
    // 상단 메뉴바가 가리키는 화면이다. 왼쪽 칸에만 설명이 들어가는 두 칸 격자라
    // 좁은 폭에서 접히는 방식이 다른 색인과 다르다 — 그래서 따로 본다.
    ['대상별 색인', '/who/'],
    ['대상 허브', '/who/youth/'],
    // 교차 허브는 비교표가 들어가는 유일한 화면이다. 표는 좁은 화면에서
    // 자기 컨테이너 안으로 넘쳐야 하고 페이지를 밀면 안 된다 — 그 차이를
    // 눈으로 잡기 어려워서 목록에 넣는다.
    ['교차 허브(비교표)', '/who/youth/housing/'],
    ['마감 예정', '/deadline/'],
    ['검색', '/search/'],
    // 소개는 사이트에서 유일하게 '읽는' 화면이다. 커버리지 숫자와 목록이
    // 들어가면서 좁은 폭에서 줄이 어떻게 접히는지 볼 필요가 생겼다.
    ['소개', '/about/'],
  ];
  const detail = firstDetail();
  if (detail) list.push(['제도 상세', detail]);
  return list.filter(([, u]) => fs.existsSync(path.join(ROOT, u, 'index.html')));
}

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

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p.startsWith(BASEURL)) p = p.slice(BASEURL.length);
  let f = path.join(ROOT, p);
  if (f.endsWith('/') || fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
  if (!fs.existsSync(f)) { res.writeHead(404); return res.end('404'); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
  res.end(fs.readFileSync(f));
});

await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}${BASEURL}`;
if (SHOTS) fs.mkdirSync(SHOT_DIR, { recursive: true });

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
let problems = 0;

for (const [label, url] of pages()) {
  console.log(`\n▸ ${label}  ${url}`);
  for (const { w, name } of WIDTHS) {
    const page = await browser.newPage({ viewport: { width: w, height: 900 } });
    // 바깥 요청(구글 폰트·애널리틱스·광고)은 막는다. networkidle 이 막힌 호스트를
    // 기다리느라 한 번 도는 데 몇 분씩 걸렸다. 본문 글꼴(Pretendard)은 원래
    // <link> 로 받지 않고 시스템 글꼴로 떨어지므로, 막아도 글자 크기는 같다.
    await page.route('**/*', (route) => (
      route.request().url().startsWith(base.slice(0, base.indexOf(BASEURL)))
        ? route.continue() : route.abort()
    ));
    await page.goto(base + url, { waitUntil: 'domcontentloaded' });

    const r = await page.evaluate((vw) => {
      const doc = document.documentElement;
      const overflow = doc.scrollWidth - doc.clientWidth;

      // 뷰포트 밖으로 나간 요소 (스크롤 컨테이너 안쪽은 제외)
      const escaped = [];
      document.querySelectorAll('body *').forEach((el) => {
        const b = el.getBoundingClientRect();
        if (b.width === 0 || b.height === 0) return;
        if (b.right > vw + 1 || b.left < -1) {
          let scrollable = false;
          for (let p = el.parentElement; p; p = p.parentElement) {
            const ov = getComputedStyle(p).overflowX;
            if (ov === 'auto' || ov === 'scroll') { scrollable = true; break; }
          }
          if (!scrollable) {
            escaped.push(`${el.tagName.toLowerCase()}.${(el.className || '').toString().split(' ')[0]}`);
          }
        }
      });

      // 같은 취지의 주의 문구가 여러 번 나오는지 — 핵심 어구로 센다
      const text = document.body.innerText;
      const dup = {};
      // ⚠️ 소개·법률 문서(.legal-page)는 빼고 센다. 그 화면들은 푸터가 한 줄로
      //    말하는 것을 **설명하는 것이 일** 이다. /about/ 의 '정부 공식 사이트가
      //    아닙니다' 절과 푸터 고지가 같은 화면에 있는 것은 중복이 아니라 구조다.
      //    이 검사가 잡으려던 것은 목록·허브에서 같은 고지가 두 번 나오는 경우다.
      if (!document.querySelector('.legal-page')) {
        // '공식 창구' 같은 보통 말은 섹션 제목·버튼 이름으로도 쓰여 오탐이 난다.
        // 고지 문장에만 나오는 어구로 좁힌다.
        ['정부 공식 사이트가 아닙니다', '지침 개정', '참고 자료이며'].forEach((k) => {
          const n = text.split(k).length - 1;
          if (n >= 2) dup[k] = n;
        });
      }

      // 한글이 어절 한가운데서 끊겼는가.
      //
      // 브라우저 기본값(word-break: normal)은 한글을 아무 글자에서나 끊는다.
      // "제도만 모 / 아 보여 줍니다" 같은 줄이 그래서 나온다. body 에 keep-all 을
      // 걸어 두었지만, 어딘가에서 다시 normal 로 되돌리면 조용히 되살아난다.
      //
      // 재는 방법: 글자 하나씩 Range 를 잡아 다음 글자가 아래 줄로 내려갔는지 본다.
      // 그 경계의 앞뒤가 둘 다 공백이 아닌 한글이면 어절 중간에서 끊긴 것이다.
      const broken = [];
      const HANGUL = /[가-힣]/;
      for (const el of document.querySelectorAll('body *')) {
        const cs2 = getComputedStyle(el);
        if (cs2.display === 'none' || cs2.visibility === 'hidden') continue;
        if (cs2.wordBreak === 'keep-all') continue;
        for (const node of el.childNodes) {
          if (node.nodeType !== 3) continue;
          const t = node.textContent;
          if (!t.trim() || !HANGUL.test(t)) continue;
          const rng = document.createRange();
          rng.selectNodeContents(node);
          if ([...rng.getClientRects()].filter((r) => r.width > 0).length < 2) continue;
          for (let i = 0; i < t.length - 1; i++) {
            if (!HANGUL.test(t[i]) || !HANGUL.test(t[i + 1])) continue;
            const a = document.createRange(); a.setStart(node, i); a.setEnd(node, i + 1);
            const c = document.createRange(); c.setStart(node, i + 1); c.setEnd(node, i + 2);
            const ra = a.getBoundingClientRect(), rc = c.getBoundingClientRect();
            if (ra.height && rc.height && rc.top > ra.top + 1) {
              const cls = (el.className || el.tagName).toString().trim().split(' ')[0];
              broken.push(`.${cls} "…${t.slice(Math.max(0, i - 7), i + 1)} ▸ ${t.slice(i + 1, i + 6)}…"`);
              break;
            }
          }
          if (broken.length >= 3) break;
        }
        if (broken.length >= 3) break;
      }

      return { overflow, escaped: [...new Set(escaped)].slice(0, 5), dup, broken, h: doc.scrollHeight };
    }, w);

    const bad = r.overflow > 0 || r.escaped.length > 0 || r.broken.length > 0;
    if (bad) problems++;
    const flag = bad ? '✗' : '✓';
    let line = `  ${flag} ${name.padEnd(5)} ${String(w).padStart(4)}px · 높이 ${String(r.h).padStart(5)}px`;
    if (r.overflow > 0) line += ` · 가로넘침 ${r.overflow}px`;
    if (r.escaped.length) line += ` · 밖으로 나간 요소 ${r.escaped.join(', ')}`;
    console.log(line);
    for (const b of r.broken) console.log(`    ⚠ 어절 중간 줄바꿈  ${b}`);

    if (w === 1440 && Object.keys(r.dup).length) {
      problems++;
      for (const [k, n] of Object.entries(r.dup)) {
        console.log(`    ⚠ 중복 문구 "${k}" ${n}회`);
      }
    }

    if (SHOTS) {
      const safe = label.replace(/[^\w가-힣]/g, '');
      await page.screenshot({ path: path.join(SHOT_DIR, `${safe}-${w}.png`), fullPage: w === 1440 });
    }
    await page.close();
  }
}

await browser.close();
server.close();

console.log(problems === 0
  ? '\n전부 통과 — 세 폭 모두 가로 넘침·이탈 요소·중복 문구·어절 중간 줄바꿈 없음'
  : `\n문제 ${problems}건 — 위 ✗ / ⚠ 항목을 확인하세요`);
process.exit(problems === 0 ? 0 : 1);
