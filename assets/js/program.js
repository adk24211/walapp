// 제도 페이지 공통 동작 — 목차 생성, 읽기 진행바, 링크 복사.
// 구 _layouts/post.html 의 인라인 스크립트를 파일로 뺐다. 제도 페이지와
// 브리핑 아카이브가 같은 코드를 쓰므로 중복을 둘 이유가 없다.
(function () {
  var article = document.querySelector('.post-content');

  // 목차 — 본문 h2/h3 기반
  var toc = document.getElementById('post-toc');
  var tocList = document.getElementById('post-toc-list');
  if (article && toc && tocList) {
    var heads = article.querySelectorAll('h2, h3');
    var count = 0;
    heads.forEach(function (h) {
      if (!h.id) {
        h.id = 'sec-' + (++count) + '-' + (h.textContent || '').trim().replace(/\s+/g, '-').slice(0, 24);
      }
      var li = document.createElement('li');
      if (h.tagName.toLowerCase() === 'h3') li.className = 'toc-h3';
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.textContent = h.textContent;
      li.appendChild(a);
      tocList.appendChild(li);
    });
    if (tocList.children.length >= 2) toc.hidden = false;
  }

  // 읽기 진행바
  var bar = document.getElementById('reading-progress');
  function onScroll() {
    if (!article || !bar) return;
    var rect = article.getBoundingClientRect();
    var total = article.offsetHeight - window.innerHeight;
    var scrolled = Math.min(Math.max(-rect.top, 0), total);
    bar.style.width = (total > 0 ? (scrolled / total) * 100 : 0) + '%';
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  onScroll();

  // 링크 복사
  var copyBtn = document.getElementById('share-copy');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var done = function () {
        var orig = copyBtn.innerHTML;
        copyBtn.innerHTML = '<i class="ti ti-check"></i> 복사됨';
        setTimeout(function () { copyBtn.innerHTML = orig; }, 1500);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(window.location.href).then(done).catch(done);
      } else {
        var t = document.createElement('textarea');
        t.value = window.location.href;
        document.body.appendChild(t);
        t.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(t);
        done();
      }
    });
  }
})();
