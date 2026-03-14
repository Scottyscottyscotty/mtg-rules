// MTG Rules App - Frontend

const state = {
    selectedCards: [],
    currentTab: 'board',
    players: [],   // [{name, life, permanents: [{card_name, tapped, notes}]}]
};

// --- Card Name Autocomplete ---
let acDebounceTimer = null;
let acActiveDropdown = null;

function setupAutocomplete(input, onSelect) {
    // Create dropdown
    const wrapper = document.createElement('div');
    wrapper.className = 'ac-wrapper';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const dropdown = document.createElement('div');
    dropdown.className = 'ac-dropdown';
    wrapper.appendChild(dropdown);

    let selectedIdx = -1;

    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(acDebounceTimer);
        if (q.length < 2) {
            dropdown.innerHTML = '';
            dropdown.classList.remove('visible');
            return;
        }
        acDebounceTimer = setTimeout(async () => {
            try {
                const resp = await fetch(`/api/cards/autocomplete?q=${encodeURIComponent(q)}`);
                if (!resp.ok) return;
                const names = await resp.json();
                renderAcDropdown(dropdown, names, input, onSelect);
                selectedIdx = -1;
            } catch (_) {}
        }, 150);
    });

    input.addEventListener('keydown', e => {
        const items = dropdown.querySelectorAll('.ac-item');
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
            items.forEach((el, i) => el.classList.toggle('highlighted', i === selectedIdx));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIdx = Math.max(selectedIdx - 1, 0);
            items.forEach((el, i) => el.classList.toggle('highlighted', i === selectedIdx));
        } else if (e.key === 'Enter' && selectedIdx >= 0) {
            e.preventDefault();
            const name = items[selectedIdx].textContent;
            input.value = name;
            dropdown.innerHTML = '';
            dropdown.classList.remove('visible');
            selectedIdx = -1;
            if (onSelect) onSelect(name);
        } else if (e.key === 'Escape') {
            dropdown.innerHTML = '';
            dropdown.classList.remove('visible');
            selectedIdx = -1;
        }
    });

    // Close dropdown on outside click
    document.addEventListener('click', e => {
        if (!wrapper.contains(e.target)) {
            dropdown.innerHTML = '';
            dropdown.classList.remove('visible');
        }
    });

    return wrapper;
}

function renderAcDropdown(dropdown, names, input, onSelect) {
    if (!names.length) {
        dropdown.innerHTML = '';
        dropdown.classList.remove('visible');
        return;
    }
    dropdown.innerHTML = names.slice(0, 8).map(name =>
        `<div class="ac-item">${escapeHtml(name)}</div>`
    ).join('');
    dropdown.classList.add('visible');

    dropdown.querySelectorAll('.ac-item').forEach(item => {
        item.addEventListener('mousedown', e => {
            e.preventDefault();
            input.value = item.textContent;
            dropdown.innerHTML = '';
            dropdown.classList.remove('visible');
            if (onSelect) onSelect(item.textContent);
        });
    });
}

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
        const resp = await fetch(`/api/cards/search?q=${encodeURIComponent(query)}&limit=12`);
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

// --- Board State Builder ---
const addPlayerBtn = document.getElementById('add-player-btn');
const playerNameInput = document.getElementById('player-name-input');
const playersContainer = document.getElementById('players-container');
const activePlayerSelect = document.getElementById('active-player-select');
const eventSourcePlayer = document.getElementById('event-source-player');
const runEventBtn = document.getElementById('run-event-btn');
const boardResults = document.getElementById('board-results');

addPlayerBtn.addEventListener('click', () => {
    const name = playerNameInput.value.trim();
    if (!name || state.players.find(p => p.name === name)) return;
    state.players.push({ name, life: 40, permanents: [] });
    playerNameInput.value = '';
    renderPlayers();
});
playerNameInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') addPlayerBtn.click();
});

function renderPlayers() {
    // Update player selects
    const playerNames = state.players.map(p => p.name);
    activePlayerSelect.innerHTML = '<option value="">-- select --</option>' +
        playerNames.map(n => `<option value="${n}">${n}</option>`).join('');
    eventSourcePlayer.innerHTML = '<option value="">Source player</option>' +
        playerNames.map(n => `<option value="${n}">${n}</option>`).join('');

    runEventBtn.disabled = state.players.length === 0;

    // Render player boards
    playersContainer.innerHTML = state.players.map((player, pi) => `
        <div class="results-section" style="margin-bottom: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h2 style="border-bottom: none; padding-bottom: 0; margin-bottom: 0;">
                    ${escapeHtml(player.name)}
                    <span style="font-weight: 300; font-size: 0.85rem; color: var(--text-muted);">
                        (Life:
                        <input type="number" value="${player.life}" min="0"
                               onchange="updateLife(${pi}, this.value)"
                               style="width: 50px; background: var(--bg-input); border: 1px solid var(--border);
                                      border-radius: 4px; color: var(--text); text-align: center; padding: 2px;">)
                    </span>
                </h2>
                <button onclick="removePlayer(${pi})"
                        style="background: transparent; color: var(--accent); font-size: 0.8rem; padding: 0.25rem 0.5rem;">
                    Remove
                </button>
            </div>

            <div style="margin-top: 0.75rem;">
                <div style="display: flex; gap: 0.5rem; margin-bottom: 0.5rem;" class="perm-add-row">
                    <input type="text" id="perm-input-${pi}" class="perm-ac-input" data-player="${pi}"
                           placeholder="Add permanent (card name)"
                           style="flex: 1; padding: 0.5rem; background: var(--bg-input); border: 1px solid var(--border);
                                  border-radius: 6px; color: var(--text);">
                    <button onclick="addPermanent(${pi})" style="padding: 0.5rem 1rem; font-size: 0.85rem;">Add</button>
                </div>
                <div class="card-tags">
                    ${player.permanents.map((perm, ci) => `
                        <span class="card-tag">
                            ${escapeHtml(perm.card_name)}
                            ${perm.tapped ? '<span style="color: var(--warning);">(T)</span>' : ''}
                            <span class="remove" onclick="removePermanent(${pi}, ${ci})">x</span>
                        </span>
                    `).join('')}
                </div>
            </div>
        </div>
    `).join('');

    // Attach autocomplete to each permanent input
    document.querySelectorAll('.perm-ac-input').forEach(input => {
        const pi = parseInt(input.dataset.player);
        setupAutocomplete(input, (name) => {
            // Auto-add on select
            addPermanentByName(pi, name);
        });
    });
}

function updateLife(playerIdx, value) {
    state.players[playerIdx].life = parseInt(value) || 0;
}

function removePlayer(playerIdx) {
    state.players.splice(playerIdx, 1);
    renderPlayers();
}

function addPermanent(playerIdx) {
    const input = document.getElementById(`perm-input-${playerIdx}`);
    const name = input.value.trim();
    if (!name) return;
    addPermanentByName(playerIdx, name);
}

function addPermanentByName(playerIdx, name) {
    state.players[playerIdx].permanents.push({
        card_name: name,
        owner: state.players[playerIdx].name,
        tapped: false,
    });
    renderPlayers();
}

function removePermanent(playerIdx, permIdx) {
    state.players[playerIdx].permanents.splice(permIdx, 1);
    renderPlayers();
}

runEventBtn.addEventListener('click', async () => {
    const board = {
        players: state.players.map(p => ({
            name: p.name,
            life: p.life,
            permanents: p.permanents.map(perm => ({
                card_name: perm.card_name,
                owner: p.name,
                controller: p.name,
                tapped: perm.tapped || false,
            })),
        })),
        active_player: activePlayerSelect.value || state.players[0]?.name || '',
    };
    const event = {
        event_type: document.getElementById('event-type-select').value,
        source_card: document.getElementById('event-source-card').value.trim() || null,
        source_player: eventSourcePlayer.value || null,
        details: document.getElementById('event-details').value.trim(),
    };

    boardResults.innerHTML = '<div class="loading"><span class="spinner"></span>Analyzing board event...</div>';

    try {
        const resp = await fetch('/api/board/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board, event }),
        });
        if (!resp.ok) {
            const data = await resp.json();
            throw new Error(data.detail || 'Analysis failed');
        }
        const result = await resp.json();
        renderBoardResult(result);
    } catch (err) {
        boardResults.innerHTML = `<div class="error">${err.message}</div>`;
    }
});

function renderBoardResult(result) {
    let html = '';

    // View toggle
    html += `<div class="view-toggle">
        <button class="view-btn active" onclick="switchBoardView('plain')">Plain English</button>
        <button class="view-btn" onclick="switchBoardView('technical')">Technical Details</button>
    </div>`;

    // Plain English view (shown by default)
    html += `<div id="board-view-plain" class="board-view active">`;
    html += `<div class="summary-box plain-english-box">${escapeHtml(result.plain_english)}</div>`;
    if (result.did_not_trigger && result.did_not_trigger.length) {
        html += '<div class="results-section" style="margin-top: 1rem;"><h2 style="color: #f0a040;">⚠ Did NOT Trigger</h2>';
        result.did_not_trigger.forEach(d => {
            html += `<div style="margin-bottom: 0.75rem; padding: 0.75rem; background: rgba(240, 160, 64, 0.08); border-left: 3px solid #f0a040; border-radius: 4px;">
                <strong>${escapeHtml(d.permanent_name)}</strong>
                <span style="color: var(--text-muted);"> (${escapeHtml(d.controller)})</span>
                <div style="margin-top: 0.25rem; color: var(--text-muted);">${escapeHtml(d.reason)}</div>
            </div>`;
        });
        html += '</div>';
    }
    if (result.warnings.length) {
        html += '<div class="results-section" style="margin-top: 1rem;"><h2>Heads Up</h2><ul>';
        result.warnings.forEach(w => {
            html += `<li style="color: var(--warning);">${escapeHtml(w)}</li>`;
        });
        html += '</ul></div>';
    }
    html += '</div>';

    // Technical view (hidden by default)
    html += `<div id="board-view-technical" class="board-view">`;

    // Summary
    html += `<div class="summary-box">${escapeHtml(result.summary)}</div>`;

    // Stack order
    if (result.stack_order.length) {
        html += '<div class="results-section"><h2>Stack (resolves top-down)</h2><ul>';
        result.stack_order.forEach((item, i) => {
            html += `<li><strong>${i + 1}.</strong> ${escapeHtml(item)}</li>`;
        });
        html += '</ul></div>';
    }

    // Cascade steps
    if (result.cascade.length) {
        html += '<div class="results-section"><h2>Cascade Steps</h2>';
        result.cascade.forEach(step => {
            html += `<div class="rules-result" style="margin-bottom: 0.75rem;">`;
            html += `<span class="rule-number">Step ${step.step_number}</span>`;
            html += `<strong>${escapeHtml(step.event.event_type)}</strong>`;
            if (step.event.source_card) {
                html += ` (${escapeHtml(step.event.source_card)})`;
            }
            if (step.triggers_fired.length) {
                html += `<div style="margin-top: 0.5rem; padding-left: 1rem; border-left: 2px solid var(--accent);">`;
                step.triggers_fired.forEach(t => {
                    html += `<div style="margin-bottom: 0.25rem;">
                        <strong>${escapeHtml(t.permanent_name)}</strong>
                        <span style="color: var(--text-muted);">(${escapeHtml(t.controller)})</span>:
                        ${escapeHtml(t.trigger_text)}
                    </div>`;
                });
                html += '</div>';
            }
            if (step.replacements_applied.length) {
                html += `<div style="margin-top: 0.5rem; padding-left: 1rem; border-left: 2px solid var(--warning);">`;
                step.replacements_applied.forEach(r => {
                    html += `<div style="margin-bottom: 0.25rem;">
                        <strong>${escapeHtml(r.permanent_name)}</strong> replaces:
                        ${escapeHtml(r.replacement_text)}
                    </div>`;
                });
                html += '</div>';
            }
            if (step.notes.length) {
                html += '<ul style="margin-top: 0.5rem; padding-left: 1.5rem; list-style: disc;">';
                step.notes.forEach(n => { html += `<li>${escapeHtml(n)}</li>`; });
                html += '</ul>';
            }
            html += '</div>';
        });
        html += '</div>';
    }

    // Warnings
    if (result.warnings.length) {
        html += '<div class="results-section"><h2>Warnings</h2><ul>';
        result.warnings.forEach(w => {
            html += `<li style="color: var(--warning);">${escapeHtml(w)}</li>`;
        });
        html += '</ul></div>';
    }

    html += '</div>';

    boardResults.innerHTML = html;
}

function switchBoardView(view) {
    document.querySelectorAll('.board-view').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.view-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`board-view-${view}`).classList.add('active');
    // Find the clicked button
    document.querySelectorAll('.view-btn').forEach(btn => {
        if (btn.textContent.toLowerCase().includes(view === 'plain' ? 'plain' : 'technical')) {
            btn.classList.add('active');
        }
    });
}

// --- Rules Chat ---
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send-btn');
const chatHistory = []; // {role, content} pairs for API

function addChatMessage(role, content) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-msg ${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.innerHTML = role === 'assistant' ? formatMarkdown(content) : escapeHtml(content);
    msgDiv.appendChild(bubble);
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addChatThinking() {
    const el = document.createElement('div');
    el.className = 'chat-msg assistant';
    el.id = 'chat-thinking';
    el.innerHTML = '<div class="chat-thinking"><span class="spinner"></span>Looking up rules...</div>';
    chatMessages.appendChild(el);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function removeChatThinking() {
    const el = document.getElementById('chat-thinking');
    if (el) el.remove();
}

async function sendChatMessage() {
    const question = chatInput.value.trim();
    if (!question) return;

    chatInput.value = '';
    chatSendBtn.disabled = true;
    addChatMessage('user', question);
    addChatThinking();

    try {
        const resp = await fetch('/api/chat/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, history: chatHistory }),
        });
        removeChatThinking();

        if (!resp.ok) {
            const data = await resp.json();
            throw new Error(data.detail || 'Chat request failed');
        }

        const result = await resp.json();
        addChatMessage('assistant', result.answer);

        // Update history for follow-ups
        chatHistory.push({ role: 'user', content: question });
        chatHistory.push({ role: 'assistant', content: result.answer });
    } catch (err) {
        removeChatThinking();
        addChatMessage('assistant', `Error: ${err.message}`);
    }

    chatSendBtn.disabled = false;
    chatInput.focus();
}

chatSendBtn.addEventListener('click', sendChatMessage);
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});

function formatMarkdown(text) {
    // Basic markdown: bold, italic, code, lists
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/`(.+?)`/g, '<code style="background:rgba(255,255,255,0.1);padding:0.1rem 0.3rem;border-radius:3px;">$1</code>');
    html = html.replace(/^- (.+)$/gm, '<li style="margin-left:1rem;">$1</li>');
    return html;
}

// Init
renderCardTags();
renderPlayers();

// Set up autocomplete on static card inputs
setupAutocomplete(interactionInput, null);
setupAutocomplete(document.getElementById('event-source-card'), null);
