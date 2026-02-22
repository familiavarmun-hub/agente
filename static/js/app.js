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

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    progressBar.style.display = 'block';
    scanText.textContent = 'Cargando caché...';

    // 1. Cargar caché del servidor (resultados IA previos)
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

    // 2. Identificar solo los pendientes (no analizados aún)
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
        btn.innerHTML = '<i class="bi bi-check2"></i>';
        btn.disabled = false;
        autoFilter();
        return;
    }

    scanText.textContent = `${done} cacheados, ${pending.length} nuevos por analizar...`;

    // 3. Solo analizar los nuevos
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
    btn.innerHTML = '<i class="bi bi-check2"></i>';
    btn.disabled = false;
    updateCounts();
    autoFilter();
}

// --- Buscar correos nuevos (sin recargar toda la página) ---

async function refreshEmails() {
    const btn = document.getElementById('btn-refresh');
    if (!btn) return;

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
        const resp = await fetch('/emails/refresh', { method: 'POST' });
        const data = await resp.json();

        if (data.new_count > 0) {
            // Hay correos nuevos → recargar la página para mostrarlos
            window.location.reload();
        } else {
            btn.innerHTML = '<i class="bi bi-check2"></i> Sin cambios';
            btn.disabled = false;
            setTimeout(() => {
                btn.innerHTML = '<i class="bi bi-arrow-clockwise"></i>';
            }, 2000);
        }
    } catch (e) {
        btn.innerHTML = '<i class="bi bi-x"></i> Error';
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
    const badge = card.querySelector('.category-badge');
    if (!badge) return;

    const cat = (category || '').toUpperCase();
    card.dataset.category = cat;

    if (cat.includes('REQUIERE')) {
        badge.className = 'category-badge cat-danger';
        badge.textContent = 'IMPORTANTE';
        card.classList.add('has-actions');
    } else if (cat.includes('INFORMATIVO')) {
        badge.className = 'category-badge cat-warning';
        badge.textContent = 'INFO';
    } else if (cat.includes('SPAM') || cat.includes('MARKETING')) {
        badge.className = 'category-badge cat-muted';
        badge.textContent = 'SPAM';
        card.classList.add('spam');
    } else {
        badge.className = 'category-badge cat-info';
        badge.textContent = cat || '';
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

    // Actualizar pills de categoría
    document.querySelectorAll('.pill[data-filter]').forEach(pill => {
        pill.classList.toggle('active', pill.dataset.filter === filter);
    });
}

function filterBySource(source) {
    activeSourceFilter = source;
    applyAllFilters();

    // Actualizar pills de fuente
    document.querySelectorAll('.pill[data-source-filter]').forEach(pill => {
        pill.classList.toggle('active', pill.dataset.sourceFilter === source);
    });
}

function applyAllFilters() {
    const cards = document.querySelectorAll('.email-card[data-source]');

    cards.forEach(card => {
        const cat = (card.dataset.category || '').toUpperCase();
        const source = card.dataset.source || '';

        // Filtro por categoría
        let showByCat = true;
        if (activeFilter === 'requiere') {
            showByCat = cat.includes('REQUIERE');
        } else if (activeFilter === 'informativo') {
            showByCat = cat.includes('INFORMATIVO');
        } else if (activeFilter === 'spam') {
            showByCat = cat.includes('SPAM') || cat.includes('MARKETING');
        }

        // Filtro por fuente
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
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" style="width:12px;height:12px;border-width:1.5px;"></span>';

    try {
        const resp = await fetch(`/email/${source}/${emailId}/archive`, { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'ok') {
            btn.innerHTML = '<i class="bi bi-check2"></i>';
            btn.classList.add('archived');
            const card = btn.closest('.email-card');
            if (card) {
                card.style.opacity = '0.3';
                setTimeout(() => card.remove(), 1000);
            }
        } else {
            btn.innerHTML = '<i class="bi bi-x"></i>';
            btn.disabled = false;
        }
    } catch (e) {
        btn.innerHTML = '<i class="bi bi-x"></i>';
        btn.disabled = false;
    }
}

// --- Análisis individual (email_detail) ---

async function analyzeEmail(source, emailId) {
    const panel = document.getElementById('ai-panel');
    const loading = document.getElementById('ai-loading');
    const result = document.getElementById('ai-result');
    const btn = document.getElementById('btn-analyze');

    panel.style.display = 'block';
    loading.style.display = 'block';
    result.style.display = 'none';
    btn.disabled = true;

    try {
        const resp = await fetch(`/email/${source}/${emailId}/analyze`, { method: 'POST' });
        const data = await resp.json();

        if (data.error) {
            loading.innerHTML = `<span class="text-danger small">${escapeHtml(data.error)}</span>`;
            return;
        }

        document.getElementById('ai-category').textContent = data.category;
        document.getElementById('ai-category').className = 'badge ' + getCategoryClass(data.category);
        document.getElementById('ai-summary').textContent = data.summary;

        if (data.draft_response) {
            document.getElementById('ai-draft').textContent = data.draft_response;
            document.getElementById('ai-draft-section').style.display = 'block';

            if (data.category && data.category.toUpperCase().includes('REQUIERE')) {
                const replyBody = document.getElementById('reply-body');
                if (replyBody && !replyBody.value.trim()) {
                    replyBody.value = data.draft_response;
                }
            }
        } else {
            document.getElementById('ai-draft-section').style.display = 'none';
        }

        loading.style.display = 'none';
        result.style.display = 'block';
    } catch (e) {
        loading.innerHTML = '<span class="text-danger small">Error al analizar.</span>';
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
            btn.innerHTML = '<i class="bi bi-check2-all"></i> Leído — redirigiendo...';
            btn.className = 'btn btn-sm btn-ghost text-success';
            setTimeout(() => { window.location.href = '/'; }, 1000);
        } else {
            btn.innerHTML = '<i class="bi bi-x"></i> Error';
            btn.disabled = false;
        }
    } catch (e) {
        btn.innerHTML = '<i class="bi bi-x"></i> Error';
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
            btn.innerHTML = '<i class="bi bi-archive-fill"></i> Archivado — redirigiendo...';
            btn.className = 'btn btn-sm btn-archive archived';
            setTimeout(() => { window.location.href = '/'; }, 1000);
        } else {
            btn.innerHTML = '<i class="bi bi-x"></i> Error';
            btn.disabled = false;
        }
    } catch (e) {
        btn.innerHTML = '<i class="bi bi-x"></i> Error';
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
            btn.innerHTML = '<i class="bi bi-check2"></i> Enviado — redirigiendo...';
            btn.className = 'btn w-100 btn-success';
            setTimeout(() => { window.location.href = '/'; }, 1500);
        } else {
            alert('Error: ' + (data.error || 'No se pudo enviar'));
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-send-fill"></i> Enviar respuesta';
        }
    } catch (e) {
        alert('Error de conexión');
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-send-fill"></i> Enviar respuesta';
    }
}

// --- Utilidades ---

function getCategoryClass(category) {
    if (!category) return 'bg-secondary';
    const c = category.toUpperCase();
    if (c.includes('REQUIERE')) return 'bg-danger';
    if (c.includes('INFORMATIVO')) return 'bg-warning text-dark';
    if (c.includes('SPAM') || c.includes('MARKETING')) return 'bg-secondary';
    return 'bg-info';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
