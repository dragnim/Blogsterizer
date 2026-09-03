function updateSourceMode() {
    const selected = document.querySelector('input[name="source_type"]:checked');
    if (!selected) return;

    const mode = selected.value;
    const label = document.getElementById('content-label');
    const textarea = document.querySelector('textarea[name="content"]');
    const selector = document.querySelector('.selector-field');
    const help = document.getElementById('source-help');
    if (!label || !textarea || !selector) return;

    const config = {
        html: ['HTML', 'Paste your HTML here…', 'Existing <code> elements are treated as APL unless they explicitly name another language.'],
        text: ['Plain text', 'Paste your text here…', 'APL glyphs and ]commands are detected. Use backticks for ASCII-only code such as `words` or `0`.'],
        url: ['Public page URL', 'https://example.com/article/', 'The Blogsterizer extracts the main post/page content when it can; use a CSS selector to override it.']
    };

    label.textContent = config[mode][0];
    textarea.placeholder = config[mode][1];
    if (help) help.textContent = config[mode][2];
    selector.hidden = mode !== 'url';
}

function unresolvedWarning() {
    // Errors already disable export. Warnings do not, but taking the output
    // away with warnings still open is worth one question first.
    const panel = document.querySelector('[data-open-warnings]');
    if (!panel) return null;

    const count = parseInt(panel.dataset.openWarnings, 10);
    if (!count) return null;

    return count === 1
        ? 'There is 1 unresolved warning. Take the output anyway?'
        : `There are ${count} unresolved warnings. Take the output anyway?`;
}

function confirmDespiteWarnings() {
    const message = unresolvedWarning();
    return !message || window.confirm(message);
}

async function copyText(targetId, button) {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!confirmDespiteWarnings()) return;

    await navigator.clipboard.writeText(target.textContent);
    const original = button.textContent;
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = original; }, 1200);
}

function downloadText(targetId, filename) {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!confirmDespiteWarnings()) return;

    const blob = new Blob([target.textContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function activateTab(name) {
    const tabs = document.querySelectorAll('[data-tab]');
    const panels = document.querySelectorAll('[data-panel]');

    tabs.forEach((tab) => {
        const active = tab.dataset.tab === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    panels.forEach((panel) => {
        const active = panel.dataset.panel === name;
        panel.hidden = !active;
        panel.classList.toggle('active', active);
    });
}

function initialiseTabs() {
    document.querySelectorAll('[data-tab]').forEach((tab) => {
        tab.addEventListener('click', () => activateTab(tab.dataset.tab));
    });
}

function setFindingFilter(filter) {
    const findings = Array.from(document.querySelectorAll('[data-finding-severity]'));
    const groups = Array.from(document.querySelectorAll('[data-group-severity]'));
    const filters = document.querySelectorAll('[data-finding-filter]');
    const count = document.getElementById('finding-count');
    const empty = document.getElementById('empty-filter-message');

    let visible = 0;
    findings.forEach((finding) => {
        const show = filter === 'all' || finding.dataset.findingSeverity === filter;
        finding.hidden = !show;
        if (show) visible += 1;
    });

    // A group whose findings are all filtered out should disappear too, and the
    // ones left should say how many they are now showing.
    groups.forEach((group) => {
        const shown = group.querySelectorAll('[data-finding-severity]:not([hidden])').length;
        group.hidden = shown === 0;
        const badge = group.querySelector('[data-group-count]');
        if (badge) badge.textContent = shown;
        // Narrowing to one severity means the user is looking for those, so open
        // the groups that survive rather than making them click again.
        if (filter !== 'all' && shown > 0) group.open = true;
    });

    filters.forEach((button) => {
        const active = button.dataset.findingFilter === filter;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });

    if (count) {
        count.textContent = `Showing ${visible} of ${findings.length}`;
    }

    if (empty) {
        empty.hidden = visible !== 0;
    }

    activateTab('changes');
}

function initialiseFindingFilters() {
    document.querySelectorAll('[data-finding-filter]').forEach((button) => {
        button.addEventListener('click', () => setFindingFilter(button.dataset.findingFilter));
    });
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[name="source_type"]').forEach((input) => {
        input.addEventListener('change', updateSourceMode);
    });
    updateSourceMode();

    initialiseTabs();
    initialiseFindingFilters();

    document.querySelectorAll('[data-copy-target]').forEach((button) => {
        button.addEventListener('click', () => copyText(button.dataset.copyTarget, button));
    });

    document.querySelectorAll('[data-download-target]').forEach((button) => {
        button.addEventListener('click', () => downloadText(button.dataset.downloadTarget, button.dataset.filename));
    });
});
