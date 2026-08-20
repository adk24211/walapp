/**
 * 빌드 결과의 인라인 <script> 가 문법적으로 올바른지 본다.
 *
 * 왜 필요한가: 아이콘을 인라인 SVG 로 바꾸면서 검색 페이지의 JS 문자열 안에
 * {% include %} 를 넣었는데, include 가 끝에 줄바꿈을 붙이는 바람에 홑따옴표
 * 문자열이 끊겼다. "Invalid or unexpected token" 하나로 그 페이지 스크립트가
 * 통째로 죽었고 — 검색이 완전히 멈춘 채로 배포됐다. 화면은 멀쩡해 보였다.
 *
 * 빌드는 통과하고 눈으로도 안 보이는 부류라, 기계가 봐야 한다.
 * 실행하지 않고 컴파일만 해 보므로 브라우저가 필요 없다(CI 에서 몇 초).
 *
 *   node scripts/check_inline_js.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const ROOT = path.join(import.meta.dirname, '..');
const SITE = path.join(ROOT, '_site');

if (!fs.existsSync(SITE)) {
  console.error('_site 가 없습니다. 먼저 jekyll build 를 실행하세요.');
  process.exit(1);
}

/** _site 안의 모든 .html */
function htmlFiles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...htmlFiles(full));
    else if (e.name.endsWith('.html')) out.push(full);
  }
  return out;
}

// src 가 있는 것은 외부 파일이라 여기서 볼 대상이 아니다. 본문이 든 것만 본다.
const SCRIPT_RE = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;

let checked = 0;
const problems = [];

for (const file of htmlFiles(SITE)) {
  const html = fs.readFileSync(file, 'utf8');
  const rel = path.relative(SITE, file);
  let m;
  while ((m = SCRIPT_RE.exec(html)) !== null) {
    const attrs = m[1] || '';
    const body = m[2] || '';
    if (/\bsrc=/i.test(attrs)) continue;
    // JSON-LD 등 자바스크립트가 아닌 것은 건너뛴다
    if (/type\s*=\s*["']?application\/(ld\+json|json)/i.test(attrs)) continue;
    if (!body.trim()) continue;
    checked++;
    try {
      new vm.Script(body, { filename: rel });   // 컴파일만. 실행하지 않는다.
    } catch (err) {
      problems.push({ file: rel, message: err.message, snippet: body.trim().slice(0, 120) });
    }
  }
}

console.log(`인라인 스크립트 ${checked}개 검사 (HTML ${htmlFiles(SITE).length}개)`);
if (problems.length === 0) {
  console.log('문법 오류 없음 ✓');
  process.exit(0);
}
for (const p of problems) {
  console.error(`\n✗ ${p.file}\n    ${p.message}\n    ${p.snippet}…`);
}
console.error(`\n인라인 스크립트 ${problems.length}개에 문법 오류가 있습니다.`);
process.exit(1);
