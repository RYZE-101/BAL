/* BAL Frontend-JavaScript */

// Theme-Umschalter (mit Persistenz in localStorage)
(function () {
    var toggle = document.getElementById('theme-toggle');
    if (!toggle) return;

    function apply(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('bal-theme', theme);
    }

    toggle.addEventListener('click', function () {
        var current = document.documentElement.dataset.theme;
        apply(current === 'dark' ? 'light' : 'dark');
    });
})();

// Navigationsleiste: dezenten Schatten/Hintergrund beim Scrollen (Apple-Stil)
(function () {
    var header = document.querySelector('.site-header');
    if (!header) return;

    function update() {
        header.classList.toggle('scrolled', window.scrollY > 10);
    }
    window.addEventListener('scroll', update, { passive: true });
    update();
})();

// Scroll-Reveal: Sektionen/Karten sanft einblenden, sobald sie ins Bild kommen
// (Intersection Observer, leichtgewichtig, KEIN Animations-Framework)
(function () {
    if (!('IntersectionObserver' in window)) return;

    // Progressive Enhancement: reveal-Klasse nur hinzufügen, wenn JS läuft,
    // damit Inhalte ohne JS nie unsichtbar bleiben.
    var targets = document.querySelectorAll(
        '.hero, .section-head, .card, .podium-card, .profile-header, .section-title'
    );

    var observer = new IntersectionObserver(
        function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.12 }
    );

    targets.forEach(function (el) {
        el.classList.add('reveal');
        observer.observe(el);
    });
})();

// Live-Rang-Anzeige für Slider (Bewertungsformular)
document.addEventListener('input', function (e) {
    if (e.target && e.target.type === 'range') {
        var display = e.target.closest('.range-wrap').querySelector('.range-value');
        if (display) display.textContent = e.target.value;
    }
});

// Ranking-Polling (alle 10s aktualisieren ohne Reload)
(function () {
    var list = document.getElementById('ranking-list');
    if (!list) return;
    var url = list.getAttribute('data-url');

    function refresh() {
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.text() : null; })
            .then(function (html) {
                if (html) list.innerHTML = html;
            })
            .catch(function () { /* Netzwerkfehler ignorieren, beim nächsten Tick erneut versuchen */ });
    }
    setInterval(refresh, 10000);
})();
