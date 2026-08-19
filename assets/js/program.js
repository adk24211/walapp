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

    // 좁은 화면에서는 목차를 접는다. 항상 펼쳐 두면 9줄(319px)을 밀고 지나가야
    // 본문이 시작된다 — 모바일에서 그건 화면의 3분의 1이다.
    // 넓은 화면은 CSS 가 왼쪽 sticky 로 빼므로 토글이 필요 없다.
    var tocTitle = toc.querySelector('.post-toc-title');
    if (tocTitle) {
      tocTitle.setAttribute('role', 'button');
      tocTitle.setAttribute('tabindex', '0');
      tocTitle.setAttribute('aria-expanded', 'false');
      tocTitle.setAttribute('aria-controls', 'post-toc-list');
      var toggle = function () {
        var open = toc.classList.toggle('is-open');
        tocTitle.setAttribute('aria-expanded', open ? 'true' : 'false');
      };
      tocTitle.addEventListener('click', toggle);
      tocTitle.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
      // 목차 항목을 누르면 접어 준다 — 펼쳐진 채로 이동하면 목적지가 가려진다
      tocList.addEventListener('click', function (e) {
        if (e.target.tagName === 'A' && toc.classList.contains('is-open')) toggle();
      });
    }
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

  // 하단 고정 신청 바 — 좁은 화면에서만 뜬다.
  // 레일의 신청 버튼이 화면에 보이는 동안에는 내려 둔다. 같은 버튼이 한 화면에
  // 둘이면 어느 쪽을 눌러야 하는지가 오히려 헷갈린다.
  var dock = document.getElementById('apply-dock');
  var inlineBtn = document.getElementById('apply-inline');
  if (dock) {
    var narrow = window.matchMedia('(max-width: 1199px)');
    var tuck = function (on) { dock.classList.toggle('is-tucked', on); };

    var observer = null;
    if (window.IntersectionObserver && inlineBtn) {
      observer = new IntersectionObserver(function (entries) {
        tuck(entries[0].isIntersecting);
      }, { threshold: 0 });
    }

    var apply = function () {
      if (narrow.matches) {
        dock.hidden = false;
        if (observer) observer.observe(inlineBtn);
        // 관찰이 시작되기 전 첫 프레임에는 인라인 버튼이 대개 화면 안이다
        else tuck(false);
      } else {
        dock.hidden = true;
        if (observer) observer.disconnect();
      }
    };
    apply();
    // addListener 는 구형 사파리용 폴백
    if (narrow.addEventListener) narrow.addEventListener('change', apply);
    else if (narrow.addListener) narrow.addListener(apply);
  }

  // ── 공유 ──
  // 카카오톡·인스타그램은 트위터/페이스북 같은 '주소만 붙이면 되는' 공유 URL 이 없다.
  //   · 카카오톡  — JavaScript SDK + 앱 키가 있어야 공유창이 뜬다.
  //   · 인스타그램 — 웹에서 글·스토리를 미리 채우는 공개 API 가 아예 없다.
  // 그래서 순서대로 내려간다: 전용 SDK → OS 공유 시트 → 링크 복사.
  // 눌러도 아무 일이 없는 버튼은 두지 않는다.
  var toastEl = document.getElementById('share-toast');
  var toastTimer = null;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-on'); }, 3200);
  }

  var pageUrl = window.location.href;
  var pageTitle = document.title;

  function copyLink(then) {
    var done = function (ok) { if (then) then(ok); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(pageUrl)
        .then(function () { done(true); })
        .catch(function () { done(false); });
      return;
    }
    var t = document.createElement('textarea');
    t.value = pageUrl;
    t.setAttribute('readonly', '');
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(t);
    done(ok);
  }

  // navigator.share 가 있으면 OS 공유 시트를 띄운다. 거기에 카카오톡·인스타그램이
  // 앱으로 잡혀 있으면 사용자가 직접 고를 수 있다.
  function nativeShare() {
    if (!navigator.share) return false;
    navigator.share({ title: pageTitle, url: pageUrl }).catch(function () {});
    return true;
  }

  function fallbackCopy(msg) {
    copyLink(function (ok) {
      toast(ok ? msg : '링크 복사에 실패했습니다. 주소창의 주소를 직접 복사해 주세요.');
    });
  }

  var kakaoReady = false;
  if (window.Kakao && window.KAKAO_JS_KEY) {
    try {
      if (!window.Kakao.isInitialized()) window.Kakao.init(window.KAKAO_JS_KEY);
      kakaoReady = window.Kakao.isInitialized();
    } catch (e) { kakaoReady = false; }
  }

  var copyBtn = document.getElementById('share-copy');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      copyLink(function (ok) {
        if (!ok) return toast('링크 복사에 실패했습니다. 주소창의 주소를 직접 복사해 주세요.');
        var orig = copyBtn.innerHTML;
        copyBtn.innerHTML = '<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-check"></use></svg> 복사됨';
        setTimeout(function () { copyBtn.innerHTML = orig; }, 1500);
        toast('링크를 복사했습니다.');
      });
    });
  }

  var kakaoBtn = document.getElementById('share-kakao');
  if (kakaoBtn) {
    kakaoBtn.addEventListener('click', function () {
      if (kakaoReady) {
        try {
          window.Kakao.Share.sendDefault({
            objectType: 'text',
            text: pageTitle,
            link: { mobileWebUrl: pageUrl, webUrl: pageUrl }
          });
          return;
        } catch (e) { /* 아래 대체 경로로 */ }
      }
      if (nativeShare()) return;
      fallbackCopy('링크를 복사했습니다. 카카오톡 대화창에 붙여넣어 주세요.');
    });
  }

  var instaBtn = document.getElementById('share-instagram');
  if (instaBtn) {
    instaBtn.addEventListener('click', function () {
      // 인스타그램에는 링크 공유 endpoint 가 없다. 앱 공유 시트가 유일한 정식 경로다.
      if (nativeShare()) return;
      fallbackCopy('인스타그램은 웹에서 바로 공유하는 기능을 제공하지 않습니다. 링크를 복사했으니 스토리·프로필·DM에 붙여넣어 주세요.');
    });
  }
})();
