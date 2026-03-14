// MTG Rules App - Frontend

const state = {
    selectedCards: [],
    currentTab: 'interactions',
};

// --- Tab switching ---
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.panel).classList.add('active');
        state.currentTab = tab.dataset.panel;
    });
});

// --- Card Search ---
const cardSearchInput = document.getElementById('card-search');
const cardSearchBtn = document.getElementById('card-search-btn');
const cardResults = document.getElementById('card-results');

async function searchCards(query) {
    cardResults.innerHTML = '<div class="loading"><span class="spinner"></span>Searching...</div>';
    try {
        const resp = await fetch(`/api/cards/?q=${encodeURIComponent(query)}&limit=12`);
        if (!resp.ok) throw new Error('Search failed');
        const cards = await resp.json();
        renderCardResults(cards);
    } catch (err) {
        cardResults.innerHTML = `<div class="error">${err.message}</div>`;
    }
}

function renderCardResults(cards) {
    if (!cards.length) {
        cardResults.innerHTML = '<div class="loading">No cards found.</div>';
        return;
    }
    cardResults.innerHTML = cards.map(card => `
        <div class="card-result ${state.selectedCards.includes(card.name) ? 'selected' : ''}"
             onclick="toggleCard('${card.name.replace(/'/g, "\\'")}')">
            ${card.image_uri ? `<img src="${card.image_uri}" alt="${card.name}" loading="lazy">` : ''}
            <h3>${card.name}</h3>
            <div class="type-line">${card.type_line}</div>
            <div class="oracle-text">${card.oracle_text || ''}</div>
        </div>
    `).join('');
}

cardSearchBtn.addEventListener('click', () => {
    const q = cardSearchInput.value.trim();
    if (q) searchCards(q);
});
cardSearchInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const q = cardSearchInput.value.trim();
        if (q) searchCards(q);
    }
});

// --- Interaction Builder ---
const interactionInput = document.getElementById('interaction-card-input');
const addCardBtn = document.getElementById('add-card-btn');
const cardTagsEl = document.getElementById('card-tags');
const analyzeBtn = document.getElementById('analyze-btn');
const interactionResults = document.getElementById('interaction-results');

function toggleCard(name) {
    const idx = state.selectedCards.indexOf(name);
    if (idx >= 0) {
        state.selectedCards.splice(idx, 1);
    } else if (state.selectedCards.length < 6) {
        state.selectedCards.push(name);
    }
    renderCardTags();
    // Re-render card results to update selection state
    document.querySelectorAll('.card-result').forEach(el => {
        const cardName = el.querySelector('h3')?.textContent;
        if (cardName) {
            el.classList.toggle('selected', state.selectedCards.includes(cardName));
        }
    });
}

function renderCardTags() {
    cardTagsEl.innerHTML = state.selectedCards.map(name => `
        <span class="card-tag">
            ${name}
            <span class="remove" onclick="toggleCard('${name.replace(/'/g, "\\'")}')">x</span>
        </span>
    `).join('');
    analyzeBtn.disabled = state.selectedCards.length < 2;
}

addCardBtn.addEventListener('click', () => {
    const name = interactionInput.value.trim();
    if (name && !state.selectedCards.includes(name) && state.selectedCards.length < 6) {
        state.selectedCards.push(name);
        interactionInput.value = '';
        renderCardTags();
    }
});
interactionInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        addCardBtn.click();
    }
});

analyzeBtn.addEventListener('click', async () => {
    if (state.selectedCards.length < 2) return;
    const format = document.getElementById('format-select').value;
    interactionResults.innerHTML = '<div class="loading"><span class="spinner"></span>Analyzing interaction...</div>';

    try {
        const resp = await fetch('/api/interactions/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ card_names: state.selectedCards, format }),
        });
        if (!resp.ok) {
            const data = await resp.json();
            throw new Error(data.detail || 'Analysis failed');
        }
        const result = await resp.json();
        renderInteractionResult(result);
    } catch (err) {
        interactionResults.innerHTML = `<div class="error">${err.message}</div>`;
    }
});

function renderInteractionResult(result) {
    let html = '';

    // Summary
    html += `<div class="summary-box">${escapeHtml(result.summary)}</div>`;

    // Stack notes
    if (result.stack_notes.length) {
        html += `<div class="results-section"><h2>Stack Interaction</h2><ul>`;
        result.stack_notes.forEach(n => { html += `<li>${escapeHtml(n)}</li>`; });
        html += '</ul></div>';
    }

    // Layer notes
    if (result.layer_notes.length) {
        html += `<div class="results-section"><h2>Layer System</h2><ul>`;
        result.layer_notes.forEach(n => { html += `<li>${escapeHtml(n)}</li>`; });
        html += '</ul></div>';
    }

    // Replacement notes
    if (result.replacement_notes.length) {
        html += `<div class="results-section"><h2>Replacement Effects</h2><ul>`;
        result.replacement_notes.forEach(n => { html += `<li>${escapeHtml(n)}</li>`; });
        html += '</ul></div>';
    }

    // Rulings
    if (result.rulings.length) {
        html += `<div class="results-section"><h2>Relevant Rulings</h2><ul>`;
        result.rulings.forEach(r => { html += `<li>${escapeHtml(r)}</li>`; });
        html += '</ul></div>';
    }

    // Card images
    const cardsWithImages = result.cards.filter(c => c.image_uri);
    if (cardsWithImages.length) {
        html += '<div class="card-grid" style="margin-top:1rem">';
        cardsWithImages.forEach(c => {
            html += `<div class="card-result">
                <img src="${c.image_uri}" alt="${c.name}" loading="lazy">
                <h3>${c.name}</h3>
            </div>`;
        });
        html += '</div>';
    }

    interactionResults.innerHTML = html;
}

// --- Rules Search ---
const rulesSearchInput = document.getElementById('rules-search');
const rulesSearchBtn = document.getElementById('rules-search-btn');
const rulesResults = document.getElementById('rules-results');

async function searchRules(query) {
    rulesResults.innerHTML = '<div class="loading"><span class="spinner"></span>Searching rules...</div>';
    try {
        const resp = await fetch(`/api/rules/search?q=${encodeURIComponent(query)}&limit=25`);
        if (!resp.ok) throw new Error('Search failed');
        const rules = await resp.json();
        renderRulesResults(rules);
    } catch (err) {
        rulesResults.innerHTML = `<div class="error">${err.message}</div>`;
    }
}

function renderRulesResults(rules) {
    if (!rules.length) {
        rulesResults.innerHTML = '<div class="loading">No rules found.</div>';
        return;
    }
    rulesResults.innerHTML = rules.map(r => `
        <div class="rules-result">
            <span class="rule-number">${r.number}</span>
            ${escapeHtml(r.text)}
        </div>
    `).join('');
}

rulesSearchBtn.addEventListener('click', () => {
    const q = rulesSearchInput.value.trim();
    if (q) searchRules(q);
});
rulesSearchInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const q = rulesSearchInput.value.trim();
        if (q) searchRules(q);
    }
});

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Init
renderCardTags();
