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
    var liveBadge = document.getElementById('live-badge');
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
