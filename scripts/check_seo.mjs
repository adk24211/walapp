/**
 * 제도 페이지가 검색엔진에 자기를 뭐라고 소개하는지 본다.
 *
 * 세 가지가 조용히 잘못돼 있었다. 화면은 멀쩡해서 눈으로는 안 보이는 부류다.
 *
 *  ① meta description 이 201개 전부 깨진 조각이었다.
 *     jekyll-seo-tag 는 page.summary 를 모른다. description 이 없으면 본문
 *     앞부분을 자르는데, 이 사이트 본문은 카드 마크업으로 시작한다:
 *       "01 지원 내용 금액이 적힌 항목 시중 시세의 60~80% 수준으로 …"
 *     그게 구글 검색 결과에 나가는 자리다.
 *
 *  ② 한 페이지가 자기를 BlogPosting 이자 GovernmentService 라고 동시에 주장했다.
 *     앞의 것은 seo-tag 가 '컬렉션 + 날짜' 를 보고 자동으로 찍은 것 —
 *     뉴스 브리핑 시절의 잔재다.
 *
 *  ③ 화면에 FAQ 가 있는데 FAQPage 마크업이 없었다.
 *
 *   node scripts/check_seo.mjs [빌드경로]
 */
import fs from 'node:fs';
import path from 'node:path';

const ARG = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : null;
const CANDIDATES = ARG ? [ARG] : ['_site_check', '_site'];
const ROOT = CANDIDATES
  .map((c) => (path.isAbsolute(c) ? c : path.join(import.meta.dirname, '..', c)))
  .find((c) => fs.existsSync(c));

if (!ROOT) {
  console.error(`빌드 결과를 찾지 못했습니다(${CANDIDATES.join(', ')}). 먼저 jekyll build 를 실행하세요.`);
  process.exit(1);
}

/** 제도 상세만 본다 — /support/<분야>/<제도>/index.html */
function programPages(dir, depth = 0) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...programPages(full, depth + 1));
    else if (e.name === 'index.html' && depth === 2) out.push(full);
  }
  return out;
}

const SUPPORT = path.join(ROOT, 'support');
const pages = fs.existsSync(SUPPORT) ? programPages(SUPPORT) : [];
if (pages.length === 0) {
  console.error('제도 페이지를 찾지 못했습니다.');
  process.exit(1);
}

const problems = [];
let faqPages = 0;

for (const file of pages) {
  const html = fs.readFileSync(file, 'utf8');
  const rel = path.relative(ROOT, file);

  const types = [];
  for (const m of html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    try { types.push(JSON.parse(m[1])['@type']); }
    catch { problems.push(`${rel} — JSON-LD 파싱 실패`); }
  }

  // ② 블로그 글이 아니다
  if (types.includes('BlogPosting') || types.includes('Article')) {
    problems.push(`${rel} — ${types.join('+')} : 제도 페이지는 블로그 글이 아니다`);
  }
  if (!types.includes('GovernmentService')) {
    problems.push(`${rel} — GovernmentService 가 없다`);
  }

  // ① 검색 결과에 나가는 문장
  const desc = html.match(/<meta name="description" content="([^"]*)"/);
  if (!desc || !desc[1].trim()) {
    problems.push(`${rel} — meta description 이 비었다`);
  } else if (/^\s*0?\d\s|지원 내용 금액이 적힌/.test(desc[1])) {
    // 본문 앞부분을 잘라 쓴 흔적(카드 번호로 시작하거나 마크업 문구가 섞임)
    problems.push(`${rel} — meta description 이 본문 조각이다: ${desc[1].slice(0, 50)}…`);
  }

  // ③ 화면에 보이는 것과 마크업이 일치해야 한다.
  //    구글은 페이지에 없는 내용을 구조화 데이터로만 넣는 것을 정책 위반으로 본다.
  const shown = (html.match(/<div class="cn-faq-body">/g) || []).length;
  const marked = (html.match(/"@type": ?"Question"/g) || []).length;
  if (shown !== marked) {
    problems.push(`${rel} — 화면 FAQ ${shown}개 vs 마크업 ${marked}개 (일치해야 한다)`);
  }
  if (shown > 0) faqPages++;
}

console.log(`제도 페이지 ${pages.length}건 검사 (${path.relative(process.cwd(), ROOT) || ROOT})`);
console.log(`  FAQ 가 있는 페이지 ${faqPages}건 — 전부 FAQPage 마크업과 개수가 같다`);
if (problems.length === 0) {
  console.log('문제 없음 ✓');
  process.exit(0);
}
for (const p of problems.slice(0, 20)) console.error(`  ✗ ${p}`);
if (problems.length > 20) console.error(`  … 외 ${problems.length - 20}건`);
console.error(`\n${problems.length}건 문제.`);
process.exit(1);
