/* BAL Frontend-JavaScript */

// Theme-Umschalter (mit Persistenz in localStorage) — Desktop- und Mobile-Toggle
(function () {
    var toggles = document.querySelectorAll('#theme-toggle, #theme-toggle-mobile');
    if (!toggles.length) return;

    function apply(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('bal-theme', theme);
    }

    toggles.forEach(function (toggle) {
        toggle.addEventListener('click', function () {
            var current = document.documentElement.dataset.theme;
            apply(current === 'dark' ? 'light' : 'dark');
        });
    });
})();

// Mobile-Navigation (Hamburger-Menü)
(function () {
    var toggle = document.getElementById('nav-toggle');
    var menu = document.getElementById('mobile-menu');
    if (!toggle || !menu) return;

    function open() {
        menu.classList.add('open');
        toggle.classList.add('open');
        document.body.classList.add('menu-open');
        toggle.setAttribute('aria-expanded', 'true');
        menu.setAttribute('aria-hidden', 'false');
    }

    function close() {
        menu.classList.remove('open');
        toggle.classList.remove('open');
        document.body.classList.remove('menu-open');
        toggle.setAttribute('aria-expanded', 'false');
        menu.setAttribute('aria-hidden', 'true');
    }

    toggle.addEventListener('click', function () {
        if (menu.classList.contains('open')) close(); else open();
    });

    // Beim Antippen eines Menüpunkts schließen
    menu.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', close);
    });

    // Beim Klick auf den Overlay-Hintergrund schließen
    menu.addEventListener('click', function (e) {
        if (e.target === menu || e.target.classList.contains('mobile-menu-inner')) close();
    });

    // Escape schließt das Menü
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') close();
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

// Live-Suche/Fächer-Filter auf der Lehrkräfte-Übersicht (Debounce 300ms)
(function () {
    var input = document.getElementById('teacher-q');
    var subject = document.getElementById('teacher-subject');
    var container = document.getElementById('teacher-grid-container');
    if (!input || !container) return;
    var url = container.getAttribute('data-url');
    if (!url) return;
    var timer = null;

    function refresh() {
        var params = new URLSearchParams();
        if (input.value.trim()) params.set('q', input.value.trim());
        if (subject && subject.value) params.set('subject', subject.value);
        fetch(url + '?' + params.toString(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.text() : null; })
            .then(function (html) { if (html) container.innerHTML = html; })
            .catch(function () {});
    }

    input.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(refresh, 300);
    });
    if (subject) {
        subject.addEventListener('change', refresh);
    }
})();

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
