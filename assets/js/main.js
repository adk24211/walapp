// Walapp — main.js

const root = document.documentElement;
const themeBtn = document.getElementById('theme-btn');
let dark = localStorage.getItem('walapp-theme') === 'dark';

function applyTheme() {
  root.setAttribute('data-theme', dark ? 'dark' : '');
  if (themeBtn) {
    themeBtn.innerHTML = dark
      ? '<i class="ti ti-sun" aria-hidden="true"></i>'
      : '<i class="ti ti-moon" aria-hidden="true"></i>';
    themeBtn.setAttribute('aria-label', dark ? '라이트모드로 전환' : '다크모드로 전환');
  }
}
applyTheme();

if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    dark = !dark;
    localStorage.setItem('walapp-theme', dark ? 'dark' : 'light');
    applyTheme();
  });
}

const tabBtns = document.querySelectorAll('.tab-btn');
const sectionGroups = document.querySelectorAll('.section-group[data-cat]');

tabBtns.forEach(btn => {
  btn.setAttribute('aria-pressed', btn.classList.contains('active') ? 'true' : 'false');
  btn.addEventListener('click', () => {
    tabBtns.forEach(b => { b.classList.remove('active'); b.setAttribute('aria-pressed', 'false'); });
    btn.classList.add('active');
    btn.setAttribute('aria-pressed', 'true');
    const f = btn.dataset.filter;
    sectionGroups.forEach(g => {
      g.style.display = (f === 'all' || g.dataset.cat === f) ? 'block' : 'none';
    });
  });
});
