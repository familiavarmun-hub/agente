// --- Estado ---
let scanResults = {};
let activeFilter = 'all';
let activeSourceFilter = 'all';

// --- Escaneo progresivo con caché ---

async function startScan() {
    const cards = document.querySelectorAll('.email-card[data-source]');
    if (cards.length === 0) return;

    const btn = document.getElementById('btn-scan');
    const progressBar = document.getElementById('scan-progress-bar');
    const progress = document.getElementById('scan-progress');
    const scanText = document.getElementById('scan-text');
    const scanTextContainer = document.getElementById('scan-text-container');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    progressBar.style.display = 'block';
    if (scanTextContainer) scanTextContainer.classList.remove('hidden');
    scanText.textContent = 'Cargando cache...';

    // 1. Cargar caché del servidor
    try {
        const cacheResp = await fetch('/analysis-cache');
        const cache = await cacheResp.json();
        for (const [emailId, result] of Object.entries(cache)) {
            scanResults[emailId] = result;
            const card = document.querySelector(`.email-card[data-id="${emailId}"]`);
            if (card) updateCardBadge(card, result.category);
        }
        updateCounts();
    } catch (e) {}

    // 2. Identificar pendientes
    let done = 0;
    const total = cards.length;
    const pending = [];

    for (const card of cards) {
        const id = card.dataset.id;
        if (scanResults[id]) {
            done++;
        } else {
            pending.push(card);
        }
    }

    progress.style.width = `${(done / total) * 100}%`;

    if (pending.length === 0) {
        scanText.textContent = `Todo listo (${total} emails)`;
        btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">check</span>';
        btn.disabled = false;
        autoFilter();
        return;
    }

    scanText.textContent = `${done} cacheados, ${pending.length} nuevos por analizar...`;

    // 3. Analizar los nuevos
    for (const card of pending) {
        const source = card.dataset.source;
        const id = card.dataset.id;

        scanText.textContent = `Analizando ${done + 1} de ${total}...`;

        try {
            const resp = await fetch(`/email/${source}/${id}/analyze`, { method: 'POST' });
            const data = await resp.json();
            if (!data.error) {
                scanResults[id] = data;
                updateCardBadge(card, data.category);
            }
        } catch (e) {}

        done++;
        progress.style.width = `${(done / total) * 100}%`;
        updateCounts();
        applyFilter();
    }

    progress.style.width = '100%';
    scanText.textContent = `Listo (${total} emails)`;
    btn.innerHTML = '<span class="material-symbols-outlined text-[18px]">check</span>';
    btn.disabled = false;
    updateCounts();
    autoFilter();
}

// --- Buscar correos nuevos ---

async function refreshEmails() {
    const btn = document.getElementById('btn-refresh');
    if (!btn) return;

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        const resp = await fetch('/emails/refresh', { method: 'POST' });
        const data = await resp.json();

        if (data.new_count > 0) {
            window.location.reload();
        } else {
            btn.innerHTML = '<span class="material-symbols-outlined text-[20px]">check</span>';
            btn.disabled = false;
            setTimeout(() => {
                btn.innerHTML = '<span class="material-symbols-outlined text-[20px]">refresh</span>';
            }, 2000);
        }
    } catch (e) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[20px]">error</span>';
        btn.disabled = false;
    }
}

function autoFilter() {
    const spamCount = parseInt(document.getElementById('count-spam').textContent) || 0;
    const reqCount = parseInt(document.getElementById('count-requiere').textContent) || 0;
    if (spamCount > 0 && reqCount > 0) {
        filterEmails('requiere');
    }
}

function updateCardBadge(card, category) {
    const cat = (category || '').toUpperCase();
    card.dataset.category = cat;

    const actionsDiv = card.querySelector('.email-actions');
    const badge = card.querySelector('.category-badge');
    const btnReply = card.querySelector('.btn-reply');
    const btnArchive = card.querySelector('.btn-archive-inline');

    if (cat.includes('REQUIERE')) {
        // Important — highlight card, show action buttons
        card.classList.add('has-actions');
        card.style.background = 'rgba(108, 43, 238, 0.05)';
        card.style.borderColor = 'rgba(108, 43, 238, 0.1)';

        // Add unread dot before subject
        const subject = card.querySelector('.email-subject');
        if (subject && !subject.querySelector('.unread-dot')) {
            const dot = document.createElement('div');
            dot.className = 'unread-dot';
            dot.style.cssText = 'width:8px;height:8px;background:#6c2bee;border-radius:50%;display:inline-block;margin-right:6px;vertical-align:middle;box-shadow:0 0 8px rgba(108,43,238,0.5);';
            subject.prepend(dot);
        }

        // Bold the from name
        const fromEl = card.querySelector('h3');
        if (fromEl) {
            fromEl.classList.add('!font-bold');
            fromEl.style.color = '#f0f1f3';
        }

        if (actionsDiv) { actionsDiv.classList.remove('hidden'); actionsDiv.classList.add('flex'); }
        if (btnReply) btnReply.classList.remove('hidden');
        if (btnArchive) btnArchive.classList.remove('hidden');
    } else if (cat.includes('INFORMATIVO')) {
        if (badge) {
            badge.classList.remove('hidden');
            badge.style.cssText = 'background:rgba(251,191,36,0.15);color:#fbbf24;';
            badge.textContent = 'INFO';
        }
        if (actionsDiv) { actionsDiv.classList.remove('hidden'); actionsDiv.classList.add('flex'); }
    } else if (cat.includes('SPAM') || cat.includes('MARKETING')) {
        card.style.opacity = '0.35';
        if (badge) {
            badge.classList.remove('hidden');
            badge.style.cssText = 'background:rgba(100,116,139,0.15);color:#64748b;';
            badge.textContent = 'SPAM';
        }
        if (actionsDiv) { actionsDiv.classList.remove('hidden'); actionsDiv.classList.add('flex'); }
    }
}

function updateCounts() {
    let countReq = 0, countInfo = 0, countSpam = 0;
    const cards = document.querySelectorAll('.email-card[data-source]');

    cards.forEach(card => {
        const cat = (card.dataset.category || '').toUpperCase();
        if (cat.includes('REQUIERE')) countReq++;
        else if (cat.includes('INFORMATIVO')) countInfo++;
        else if (cat.includes('SPAM') || cat.includes('MARKETING')) countSpam++;
    });

    document.getElementById('count-all').textContent = cards.length;
    document.getElementById('count-requiere').textContent = countReq;
    document.getElementById('count-informativo').textContent = countInfo;
    document.getElementById('count-spam').textContent = countSpam;
}

function filterEmails(filter) {
    activeFilter = filter;
    applyAllFilters();

    // Update filter tabs
    document.querySelectorAll('.filter-tab[data-filter]').forEach(tab => {
        if (tab.dataset.filter === filter) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
}

function filterBySource(source) {
    activeSourceFilter = source;
    applyAllFilters();

    // Update source pills
    document.querySelectorAll('.pill-source[data-source-filter]').forEach(pill => {
        if (pill.dataset.sourceFilter === source) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });
}

function applyAllFilters() {
    const cards = document.querySelectorAll('.email-card[data-source]');

    cards.forEach(card => {
        const cat = (card.dataset.category || '').toUpperCase();
        const source = card.dataset.source || '';

        let showByCat = true;
        if (activeFilter === 'requiere') {
            showByCat = cat.includes('REQUIERE');
        } else if (activeFilter === 'informativo') {
            showByCat = cat.includes('INFORMATIVO');
        } else if (activeFilter === 'spam') {
            showByCat = cat.includes('SPAM') || cat.includes('MARKETING');
        }

        let showBySource = true;
        if (activeSourceFilter !== 'all') {
            showBySource = source === activeSourceFilter;
        }

        card.style.display = (showByCat && showBySource) ? '' : 'none';
    });
}

function applyFilter() {
    applyAllFilters();
}

// --- Archivar desde la lista ---

async function archiveFromList(source, emailId, btn) {
    btn.disabled = true;
    btn.textContent = '...';

    try {
        const resp = await fetch(`/email/${source}/${emailId}/archive`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'ok') {
            btn.textContent = 'ARCHIVADO';
            btn.className = 'text-[10px] font-bold tracking-wider bg-emerald-600 text-white px-2 py-0.5 rounded uppercase';
            const card = btn.closest('.email-card');
            if (card) {
                card.style.opacity = '0.3';
                setTimeout(() => card.remove(), 1000);
            }
        } else {
            btn.textContent = 'ERROR';
            btn.disabled = false;
        }
    } catch (e) {
        btn.textContent = 'ERROR';
        btn.disabled = false;
    }
}

// --- Análisis individual (email_detail) ---

async function analyzeEmail(source, emailId) {
    const panel = document.getElementById('ai-panel');
    const loading = document.getElementById('ai-loading');
    const result = document.getElementById('ai-result');
    const btn = document.getElementById('btn-analyze');

    panel.classList.remove('hidden');
    loading.classList.remove('hidden');
    result.classList.add('hidden');
    btn.disabled = true;

    try {
        const resp = await fetch(`/email/${source}/${emailId}/analyze`, { method: 'POST' });
        const data = await resp.json();

        if (data.error) {
            loading.innerHTML = `<span class="text-red-400 text-sm">${escapeHtml(data.error)}</span>`;
            return;
        }

        document.getElementById('ai-category').textContent = data.category;
        document.getElementById('ai-category').className = 'inline-block text-xs font-bold px-2.5 py-1 rounded ' + getCategoryClass(data.category);
        document.getElementById('ai-summary').textContent = data.summary;

        if (data.draft_response) {
            document.getElementById('ai-draft').textContent = data.draft_response;
            document.getElementById('ai-draft-section').classList.remove('hidden');

            if (data.category && data.category.toUpperCase().includes('REQUIERE')) {
                const replyBody = document.getElementById('reply-body');
                if (replyBody && !replyBody.value.trim()) {
                    replyBody.value = data.draft_response;
                }
            }
        } else {
            document.getElementById('ai-draft-section').classList.add('hidden');
        }

        loading.classList.add('hidden');
        result.classList.remove('hidden');
    } catch (e) {
        loading.innerHTML = '<span class="text-red-400 text-sm">Error al analizar.</span>';
    } finally {
        btn.disabled = false;
    }
}

function useDraft() {
    const draft = document.getElementById('ai-draft').textContent;
    document.getElementById('reply-body').value = draft;
    document.getElementById('reply-body').focus();
}

// --- Marcar como leído ---

async function markAsRead(source, emailId) {
    const btn = document.getElementById('btn-mark-read');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        const resp = await fetch(`/email/${source}/${emailId}/mark-read`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'ok') {
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">check</span> Leido';
            btn.classList.add('!text-emerald-400');
            setTimeout(() => { window.location.href = '/'; }, 1000);
        } else {
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">error</span> Error';
            btn.disabled = false;
        }
    } catch (e) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">error</span> Error';
        btn.disabled = false;
    }
}

// --- Archivar email ---

async function archiveEmail(source, emailId) {
    const btn = document.getElementById('btn-archive');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        const resp = await fetch(`/email/${source}/${emailId}/archive`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'ok') {
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">archive</span> Archivado';
            btn.classList.add('!text-emerald-400');
            setTimeout(() => { window.location.href = '/'; }, 1000);
        } else {
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">error</span> Error';
            btn.disabled = false;
        }
    } catch (e) {
        btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">error</span> Error';
        btn.disabled = false;
    }
}

// --- Enviar respuesta ---

async function sendReply(event) {
    event.preventDefault();

    const btn = document.getElementById('btn-send');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Enviando...';

    const payload = {
        to: document.getElementById('reply-to').value,
        subject: document.getElementById('reply-subject').value,
        body: document.getElementById('reply-body').value,
    };

    try {
        const resp = await fetch(`/email/${EMAIL_SOURCE}/${EMAIL_ID}/reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();

        if (data.status === 'ok') {
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">check</span> Enviado';
            btn.className = 'w-full py-3 bg-emerald-600 text-white rounded-xl font-bold text-sm';
            setTimeout(() => { window.location.href = '/'; }, 1500);
        } else {
            alert('Error: ' + (data.error || 'No se pudo enviar'));
            btn.disabled = false;
            btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">send</span> Enviar respuesta';
        }
    } catch (e) {
        alert('Error de conexion');
        btn.disabled = false;
        btn.innerHTML = '<span class="material-symbols-outlined text-[16px]">send</span> Enviar respuesta';
    }
}

// --- Utilidades ---

function getCategoryClass(category) {
    if (!category) return 'bg-slate-600 text-white';
    const c = category.toUpperCase();
    if (c.includes('REQUIERE')) return 'bg-red-500/20 text-red-400';
    if (c.includes('INFORMATIVO')) return 'bg-amber-500/20 text-amber-400';
    if (c.includes('SPAM') || c.includes('MARKETING')) return 'bg-slate-500/20 text-slate-400';
    return 'bg-primary/20 text-primary';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
