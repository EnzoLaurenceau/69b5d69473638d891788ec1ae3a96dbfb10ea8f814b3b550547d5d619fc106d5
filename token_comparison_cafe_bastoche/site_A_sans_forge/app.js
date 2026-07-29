// Café Bastoche — interactions (Version A, écrit par Claude directement)

// Année footer
document.getElementById('year').textContent = new Date().getFullYear();

// Thème (en mémoire — pas de localStorage, environnements isolés)
const toggle = document.getElementById('themeToggle');
const root = document.documentElement;
toggle.addEventListener('click', () => {
  const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  toggle.textContent = next === 'dark' ? '🌙' : '☀️';
});

// Menu mobile
const burger = document.getElementById('burger');
const navLinks = document.getElementById('navLinks');
burger.addEventListener('click', () => navLinks.classList.toggle('open'));
navLinks.addEventListener('click', e => {
  if (e.target.tagName === 'A') navLinks.classList.remove('open');
});

// Nav ombrée au scroll
const nav = document.getElementById('nav');
const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 20);
onScroll();
window.addEventListener('scroll', onScroll, { passive: true });

// Reveal au scroll
const io = new IntersectionObserver((entries) => {
  entries.forEach(el => { if (el.isIntersecting) { el.target.classList.add('in'); io.unobserve(el.target); } });
}, { threshold: 0.12 });
document.querySelectorAll('.reveal').forEach(el => io.observe(el));

// Carte OpenStreetMap (Leaflet + tuiles CartoDB Voyager)
// Coordonnées Ixelles = placeholder, à recentrer sur l'adresse réelle du café.
const IXELLES = [50.8270, 4.3720];
const map = L.map('map', { scrollWheelZoom: false }).setView(IXELLES, 15);
L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap, &copy; CARTO', maxZoom: 20
}).addTo(map);
L.marker(IXELLES).addTo(map)
  .bindPopup('<b>Café Bastoche</b><br>Ixelles (emplacement à confirmer)')
  .openPopup();
