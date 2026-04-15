/* ═══════════════════════════════════════════════════════════════════════════
   Bizon AI — Cockpit Chat Client
   Talks to the Bizon API server at localhost:4000/api/diagnostic/chat
   Uses cockpit.http() to comply with Cockpit's CSP (no raw fetch allowed)
   ═══════════════════════════════════════════════════════════════════════════ */

var API_PORT = 4000;
var OLLAMA_PORT = 11434;

var _messages = [];
var _busy = false;
var _backend = "claude";
var _model = "";
var _sudoPassword = "";
var _systemPrompt = "";

// Pending file attachments: { name, type, dataUrl (images), text (text files), mimeType }
var _attachments = [];

/* ─── DOM refs ───────────────────────────────────────────────────────────── */
var chatArea, chatInput, btnSend, btnSudo, btnClear, sudoRow, sudoInput, sudoStatus;
var backendSelect, modelSelect, modelWrap, apiStatus, welcome;
var btnAttach, fileInput, attachmentsRow;

/* ─── Init ───────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", function() {
    chatArea = document.getElementById("chat-area");
    chatInput = document.getElementById("chat-input");
    btnSend = document.getElementById("btn-send");
    btnSudo = document.getElementById("btn-sudo");
    btnClear = document.getElementById("btn-clear");
    sudoRow = document.getElementById("sudo-row");
    sudoInput = document.getElementById("sudo-input");
    sudoStatus = document.getElementById("sudo-status");
    backendSelect = document.getElementById("backend-select");
    modelSelect = document.getElementById("model-select");
    modelWrap = document.getElementById("model-wrap");
    apiStatus = document.getElementById("api-status");
    welcome = document.getElementById("welcome");

    btnSend.addEventListener("click", sendMessage);
    chatInput.addEventListener("keydown", function(e) {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    btnClear.addEventListener("click", clearChat);
    btnSudo.addEventListener("click", toggleSudo);
    btnAttach = document.getElementById("btn-attach");
    fileInput = document.getElementById("file-input");
    attachmentsRow = document.getElementById("attachments-row");
    btnAttach.addEventListener("click", function() { fileInput.click(); });
    fileInput.addEventListener("change", handleFileSelect);
    sudoInput.addEventListener("input", function() {
        _sudoPassword = sudoInput.value;
        if (_sudoPassword) {
            sudoStatus.textContent = "✓ Enabled";
            sudoStatus.className = "sudo-status on";
            btnSudo.classList.add("active");
        } else {
            sudoStatus.textContent = "✗ Disabled";
            sudoStatus.className = "sudo-status off";
            btnSudo.classList.remove("active");
        }
    });
    backendSelect.addEventListener("change", function() {
        _backend = backendSelect.value;
        modelWrap.style.display = _backend === "ollama" ? "" : "none";
        if (_backend === "ollama") fetchOllamaModels();
    });

    // Quick suggestion clicks
    document.querySelectorAll(".suggestion").forEach(function(el) {
        el.addEventListener("click", function() {
            chatInput.value = el.getAttribute("data-prompt");
            sendMessage();
        });
    });

    // Load system prompt
    loadSystemPrompt();
    checkApiStatus();
    setInterval(checkApiStatus, 30000);

    // Quick Actions
    initQuickActions();
});

/* ─── System prompt ──────────────────────────────────────────────────────── */
function loadSystemPrompt() {
    cockpit.file("/usr/local/share/dlbt_os/bza/bizon_app_v2/system_prompt.md").read()
        .then(function(content) { _systemPrompt = content || ""; })
        .catch(function() { _systemPrompt = ""; });
}

/* ─── API status check ───────────────────────────────────────────────────── */
function checkApiStatus() {
    var http = cockpit.http({ port: API_PORT, address: "127.0.0.1" });
    http.get("/api/diagnostic/status")
        .then(function() { apiStatus.className = "status-dot"; apiStatus.title = "API online"; })
        .catch(function() { apiStatus.className = "status-dot offline"; apiStatus.title = "API offline"; })
        .always(function() { http.close(); });
}

/* ─── Ollama models ──────────────────────────────────────────────────────── */
function fetchOllamaModels() {
    var http = cockpit.http({ port: OLLAMA_PORT, address: "127.0.0.1" });
    http.get("/api/tags")
        .then(function(resp) {
            var data = JSON.parse(resp);
            var models = (data.models || []).map(function(m) { return m.name; });
            modelSelect.innerHTML = "";
            models.forEach(function(name) {
                var opt = document.createElement("option");
                opt.value = name; opt.textContent = name;
                modelSelect.appendChild(opt);
            });
            if (models.length) _model = models[0];
            modelSelect.addEventListener("change", function() { _model = modelSelect.value; });
        })
        .catch(function() {
            modelSelect.innerHTML = "<option>No models found</option>";
        })
        .always(function() { http.close(); });
}

/* ─── Send message ───────────────────────────────────────────────────────── */
function sendMessage() {
    var text = chatInput.value.trim();
    if (!text || _busy) return;

    // Hide welcome
    if (welcome) { welcome.style.display = "none"; }

    // Show user text in chat
    appendMessage("user", text);
    chatInput.value = "";
    setBusy(true);

    // Show thinking indicator
    var statusId = appendStatus("Thinking...");

    // Build the message content (may be multimodal with images)
    var contentBlocks = buildContentBlocks(text, _attachments);
    var msgForHistory = _attachments.length > 0 ? { role: "user", content: contentBlocks } : { role: "user", content: text };
    _messages.push(msgForHistory);

    // Show attachment previews in chat
    _attachments.forEach(function(att) { appendAttachmentPreview(att); });
    _attachments = [];
    renderAttachmentChips();

    // Build request
    var body = {
        messages: _messages,
        backend: _backend
    };
    if (_backend === "ollama" && _model) body.model = _model;
    if (_sudoPassword) body.sudoPassword = _sudoPassword;
    if (_systemPrompt) body.systemPrompt = _systemPrompt;

    // Stream NDJSON via cockpit.http
    var resultText = "";
    var buffer = "";
    var http = cockpit.http({ port: API_PORT, address: "127.0.0.1" });

    http.request({
        method: "POST",
        path: "/api/diagnostic/chat",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    })
    .stream(function(data) {
        buffer += data;
        var lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete last line
        lines.forEach(function(line) {
            line = line.trim();
            if (!line) return;
            try {
                var ev = JSON.parse(line);
                var t = ev.type;
                if (t === "status") {
                    updateStatus(statusId, ev.message || "Working...");
                } else if (t === "command") {
                    appendCommand(ev.command, ev.iteration);
                } else if (t === "command_done") {
                    // timing info available in ev.duration
                } else if (t === "result") {
                    removeStatus(statusId);
                    resultText = ev.result || ev.content || "";
                    appendMessage("assistant", resultText);
                } else if (t === "error") {
                    removeStatus(statusId);
                    appendError(ev.error || "Unknown error");
                }
            } catch(e) { /* partial line, ignore */ }
        });
    })
    .then(function() {
        // Process any remaining buffer
        if (buffer.trim()) {
            try {
                var ev = JSON.parse(buffer.trim());
                if (ev.type === "result") {
                    removeStatus(statusId);
                    resultText = ev.result || ev.content || "";
                    appendMessage("assistant", resultText);
                }
            } catch(e) {}
        }
        removeStatus(statusId);
        if (resultText) {
            _messages.push({ role: "assistant", content: resultText });
        }
        setBusy(false);
        http.close();
    })
    .catch(function(err) {
        removeStatus(statusId);
        appendError("Failed to connect to API: " + (err.message || err.toString()));
        setBusy(false);
        http.close();
    });
}

/* ─── UI Helpers ─────────────────────────────────────────────────────────── */

function appendMessage(role, text) {
    var div = document.createElement("div");
    div.className = "msg " + role;

    var label = document.createElement("div");
    label.className = "msg-label";
    label.textContent = role === "user" ? "You" : "Bizon AI";

    var bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.textContent = text;

    div.appendChild(label);
    div.appendChild(bubble);
    chatArea.appendChild(div);
    scrollToBottom();
}

function appendCommand(command, iteration) {
    var div = document.createElement("div");
    div.className = "msg assistant";

    var block = document.createElement("div");
    block.className = "cmd-block";
    block.innerHTML = '<div class="cmd-label">⚡ Command #' + (iteration || 1) + '</div>'
        + '<div class="cmd-output">$ ' + escapeHtml(command) + '</div>';

    div.appendChild(block);
    chatArea.appendChild(div);
    scrollToBottom();
}

function appendError(text) {
    var div = document.createElement("div");
    div.className = "msg assistant";
    var bubble = document.createElement("div");
    bubble.className = "error-bubble";
    bubble.textContent = "⚠ " + text;
    div.appendChild(bubble);
    chatArea.appendChild(div);
    scrollToBottom();
}

var _statusCounter = 0;
function appendStatus(text) {
    var id = "status-" + (++_statusCounter);
    var div = document.createElement("div");
    div.className = "msg assistant";
    div.id = id;
    div.innerHTML = '<div class="status-bubble"><div class="spinner"></div><span>' + escapeHtml(text) + '</span></div>';
    chatArea.appendChild(div);
    scrollToBottom();
    return id;
}

function updateStatus(id, text) {
    var el = document.getElementById(id);
    if (el) {
        var span = el.querySelector("span");
        if (span) span.textContent = text;
    }
}

function removeStatus(id) {
    var el = document.getElementById(id);
    if (el) el.remove();
}

function clearChat() {
    _messages = [];
    chatArea.innerHTML = "";
    if (welcome) { welcome.style.display = ""; chatArea.appendChild(welcome); }
}

function toggleSudo() {
    var isVisible = sudoRow.classList.contains("visible");
    if (isVisible) {
        sudoRow.classList.remove("visible");
    } else {
        sudoRow.classList.add("visible");
        sudoInput.focus();
    }
}

function setBusy(busy) {
    _busy = busy;
    btnSend.disabled = busy;
    chatInput.disabled = busy;
    btnSend.textContent = busy ? "◷" : "▶";
}

function scrollToBottom() {
    requestAnimationFrame(function() {
        chatArea.scrollTop = chatArea.scrollHeight;
    });
}

function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

/* ─── File Upload ────────────────────────────────────────────────────────── */

function handleFileSelect(e) {
    var files = Array.from(e.target.files);
    if (!files.length) return;

    var pending = files.length;
    files.forEach(function(file) {
        var ext = file.name.split('.').pop().toLowerCase();
        var isImage = file.type.startsWith('image/');
        var isText = ['txt', 'csv'].indexOf(ext) >= 0;
        var isPdf = ext === 'pdf';
        var isDoc = ['doc', 'docx'].indexOf(ext) >= 0;

        if (isImage) {
            var reader = new FileReader();
            reader.onload = function(ev) {
                _attachments.push({ name: file.name, type: 'image', dataUrl: ev.target.result, mimeType: file.type });
                renderAttachmentChips();
            };
            reader.readAsDataURL(file);
        } else if (isText) {
            var reader = new FileReader();
            reader.onload = function(ev) {
                _attachments.push({ name: file.name, type: 'text', text: ev.target.result });
                renderAttachmentChips();
            };
            reader.readAsText(file);
        } else if (isPdf) {
            // Save to temp, extract text via python
            var reader = new FileReader();
            reader.onload = function(ev) {
                var bytes = new Uint8Array(ev.target.result);
                var tmpPath = '/tmp/cockpit_upload_' + Date.now() + '.pdf';
                cockpit.file(tmpPath, { binary: true }).replace(bytes)
                    .then(function() {
                        return cockpit.spawn(['/home/bizon/anaconda3/bin/python3', '-c',
                            'import sys; ' +
                            'try:\n' +
                            '    import PyPDF2; r=PyPDF2.PdfReader(sys.argv[1]); print(chr(10).join(p.extract_text() or "" for p in r.pages))\n' +
                            'except:\n' +
                            '    import subprocess; print(subprocess.run(["pdftotext",sys.argv[1],"-"],capture_output=True,text=True).stdout)',
                            tmpPath]);
                    })
                    .then(function(output) {
                        _attachments.push({ name: file.name, type: 'text', text: output || '(could not extract PDF text)' });
                        renderAttachmentChips();
                        cockpit.spawn(['rm', '-f', tmpPath]);
                    })
                    .catch(function() {
                        _attachments.push({ name: file.name, type: 'text', text: '(failed to read PDF)' });
                        renderAttachmentChips();
                    });
            };
            reader.readAsArrayBuffer(file);
        } else if (isDoc) {
            // Use libreoffice or catdoc to extract text
            var reader = new FileReader();
            reader.onload = function(ev) {
                var bytes = new Uint8Array(ev.target.result);
                var tmpPath = '/tmp/cockpit_upload_' + Date.now() + '.' + ext;
                cockpit.file(tmpPath, { binary: true }).replace(bytes)
                    .then(function() {
                        return cockpit.spawn(['bash', '-c',
                            'if command -v libreoffice &>/dev/null; then ' +
                            'libreoffice --headless --convert-to txt --outdir /tmp "' + tmpPath + '" 2>/dev/null && cat "' + tmpPath.replace('.' + ext, '.txt') + '"; ' +
                            'elif command -v catdoc &>/dev/null; then catdoc "' + tmpPath + '"; ' +
                            'else echo "(install libreoffice or catdoc to read .doc files)"; fi']);
                    })
                    .then(function(output) {
                        _attachments.push({ name: file.name, type: 'text', text: output || '(could not extract text)' });
                        renderAttachmentChips();
                        cockpit.spawn(['rm', '-f', tmpPath]);
                    })
                    .catch(function() {
                        _attachments.push({ name: file.name, type: 'text', text: '(failed to read document)' });
                        renderAttachmentChips();
                    });
            };
            reader.readAsArrayBuffer(file);
        }
    });
    fileInput.value = ''; // reset
}

function renderAttachmentChips() {
    if (!_attachments.length) {
        attachmentsRow.className = 'attachments-row';
        attachmentsRow.innerHTML = '';
        return;
    }
    attachmentsRow.className = 'attachments-row visible';
    var html = '';
    _attachments.forEach(function(att, idx) {
        var icon = att.type === 'image' ? '' : (att.name.endsWith('.pdf') ? '📄' : (att.name.endsWith('.csv') ? '📊' : '📝'));
        var preview = att.type === 'image' ? '<img src="' + att.dataUrl + '">' : '<span class="file-icon">' + icon + '</span>';
        html += '<div class="attach-chip">' + preview
            + '<span class="file-name">' + escapeHtml(att.name) + '</span>'
            + '<button class="remove-btn" data-idx="' + idx + '">✕</button></div>';
    });
    attachmentsRow.innerHTML = html;
    attachmentsRow.querySelectorAll('.remove-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            _attachments.splice(parseInt(btn.getAttribute('data-idx')), 1);
            renderAttachmentChips();
        });
    });
}

function buildContentBlocks(text, attachments) {
    if (!attachments.length) return text;

    var blocks = [];
    // Add images as image blocks
    attachments.forEach(function(att) {
        if (att.type === 'image') {
            var parts = att.dataUrl.split(',');
            var mimeMatch = parts[0].match(/data:(.*?);/);
            var mime = mimeMatch ? mimeMatch[1] : 'image/jpeg';
            blocks.push({
                type: 'image',
                source: { type: 'base64', media_type: mime, data: parts[1] }
            });
        }
    });

    // Add text from text files prepended to user message
    var textParts = [];
    attachments.forEach(function(att) {
        if (att.type === 'text') {
            textParts.push('[Attached file: ' + att.name + ']\n' + att.text);
        }
    });
    var fullText = textParts.length ? textParts.join('\n\n') + '\n\n' + text : text;
    blocks.push({ type: 'text', text: fullText });

    return blocks;
}

function appendAttachmentPreview(att) {
    var div = document.createElement('div');
    div.className = 'msg user';
    if (att.type === 'image') {
        var img = document.createElement('img');
        img.className = 'msg-image';
        img.src = att.dataUrl;
        div.appendChild(img);
    } else {
        var badge = document.createElement('div');
        badge.className = 'msg-file-badge';
        badge.textContent = '📎 ' + att.name;
        div.appendChild(badge);
    }
    chatArea.appendChild(div);
    scrollToBottom();
}

/* ═══════════════════════════════════════════════════════════════════════════
   Quick Actions Sidebar
   ═══════════════════════════════════════════════════════════════════════════ */

var QA_FILE = "/usr/local/share/dlbt_os/cockpit_bizon_ai/quick_actions.json";
var _quickActions = [];
var _qaEditMode = false;
var _qaEditIndex = -1; // -1 = adding new, >= 0 = editing existing

var DEFAULT_QUICK_ACTIONS = [
    { label: "Full Diagnostic", desc: "Run complete health check", icon: "🔍", prompt: "Run a full system diagnostic — check GPUs, CPU, memory, storage, and system logs for any errors or issues." },
    { label: "GPU Status", desc: "Check NVIDIA GPUs", icon: "🖥", prompt: "Check GPU health: temperatures, utilization, memory usage, power draw, and any errors." },
    { label: "Memory Check", desc: "Check RAM & ECC errors", icon: "🧠", prompt: "Check system memory: total RAM, usage, and check for any ECC/memory errors." },
    { label: "CPU Status", desc: "Check CPU & temps", icon: "⚙", prompt: "Check CPU status: model, core count, temperatures, and utilization." },
    { label: "Error Logs", desc: "Check dmesg for errors", icon: "⚠", prompt: "Check system logs (dmesg, journalctl) for any recent errors, warnings, or hardware failures." },
    { label: "Storage", desc: "Check disks & space", icon: "💾", prompt: "Check storage health: disk space, SMART data, and any disk errors." },
    { label: "IPMI Sensors", desc: "Hardware sensors", icon: "🌡", prompt: "Check IPMI sensor readings if available: temperatures, voltages, fan speeds." },
    { label: "Docker Status", desc: "Container status", icon: "🐳", prompt: "List all Docker containers with their status, resource usage, and any issues." },
    { label: "Network Info", desc: "Check connectivity", icon: "🌐", prompt: "Check network configuration: interfaces, IP addresses, DNS, and test connectivity." },
    { label: "Update System", desc: "Check for updates", icon: "⬆", prompt: "Check if there are any system package updates available (apt)." }
];

function initQuickActions() {
    // Load from file
    cockpit.file(QA_FILE).read()
        .then(function(content) {
            if (content && content.trim()) {
                try {
                    _quickActions = JSON.parse(content);
                } catch(e) {
                    _quickActions = DEFAULT_QUICK_ACTIONS.slice();
                }
            } else {
                _quickActions = DEFAULT_QUICK_ACTIONS.slice();
                saveQuickActions();
            }
            renderQuickActions();
        })
        .catch(function() {
            _quickActions = DEFAULT_QUICK_ACTIONS.slice();
            saveQuickActions();
            renderQuickActions();
        });

    // Buttons
    document.getElementById("qa-add").addEventListener("click", function() {
        openQAModal(-1);
    });
    document.getElementById("qa-edit-mode").addEventListener("click", function() {
        _qaEditMode = !_qaEditMode;
        var btn = document.getElementById("qa-edit-mode");
        btn.style.borderColor = _qaEditMode ? "var(--accent)" : "";
        btn.style.color = _qaEditMode ? "var(--accent)" : "";
        renderQuickActions();
    });

    // Modal buttons
    document.getElementById("qa-save").addEventListener("click", saveQAFromModal);
    document.getElementById("qa-cancel").addEventListener("click", closeQAModal);
    document.getElementById("qa-modal").addEventListener("click", function(e) {
        if (e.target === this) closeQAModal();
    });
}

function saveQuickActions() {
    cockpit.file(QA_FILE).replace(JSON.stringify(_quickActions, null, 2))
        .catch(function(err) { console.log("Failed to save quick actions:", err); });
}

function renderQuickActions() {
    var list = document.getElementById("qa-list");
    if (!_quickActions.length) {
        list.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text3);font-size:12px;">No quick actions yet.<br>Click + to add one.</div>';
        return;
    }
    var html = "";
    _quickActions.forEach(function(qa, idx) {
        html += '<div class="qa-card" data-idx="' + idx + '">'
            + '<div class="qa-card-label">' + (qa.icon || '⚡') + ' ' + escapeHtml(qa.label) + '</div>'
            + (qa.desc ? '<div class="qa-card-desc">' + escapeHtml(qa.desc) + '</div>' : '')
            + '<button class="qa-delete" data-idx="' + idx + '" title="Delete">✕</button>'
            + '</div>';
    });
    list.innerHTML = html;

    // Click handlers
    list.querySelectorAll(".qa-card").forEach(function(card) {
        card.addEventListener("click", function(e) {
            if (e.target.classList.contains("qa-delete")) return;
            var idx = parseInt(card.getAttribute("data-idx"));
            var qa = _quickActions[idx];
            if (_qaEditMode) {
                openQAModal(idx);
            } else {
                chatInput.value = qa.prompt;
                chatInput.focus();
            }
        });
    });

    // Delete handlers
    list.querySelectorAll(".qa-delete").forEach(function(btn) {
        btn.addEventListener("click", function(e) {
            e.stopPropagation();
            var idx = parseInt(btn.getAttribute("data-idx"));
            _quickActions.splice(idx, 1);
            saveQuickActions();
            renderQuickActions();
        });
    });
}

function openQAModal(editIdx) {
    _qaEditIndex = editIdx;
    var modal = document.getElementById("qa-modal");
    var title = document.getElementById("qa-modal-title");
    var labelInput = document.getElementById("qa-label");
    var descInput = document.getElementById("qa-desc");
    var promptInput = document.getElementById("qa-prompt");

    if (editIdx >= 0) {
        title.textContent = "Edit Quick Action";
        var qa = _quickActions[editIdx];
        labelInput.value = qa.label || "";
        descInput.value = qa.desc || "";
        promptInput.value = qa.prompt || "";
    } else {
        title.textContent = "Add Quick Action";
        labelInput.value = "";
        descInput.value = "";
        promptInput.value = "";
    }
    modal.classList.add("show");
    labelInput.focus();
}

function closeQAModal() {
    document.getElementById("qa-modal").classList.remove("show");
}

function saveQAFromModal() {
    var label = document.getElementById("qa-label").value.trim();
    var desc = document.getElementById("qa-desc").value.trim();
    var prompt = document.getElementById("qa-prompt").value.trim();

    if (!label || !prompt) return;

    var qa = { label: label, desc: desc, icon: "⚡", prompt: prompt };

    if (_qaEditIndex >= 0) {
        qa.icon = _quickActions[_qaEditIndex].icon || "⚡";
        _quickActions[_qaEditIndex] = qa;
    } else {
        _quickActions.push(qa);
    }

    saveQuickActions();
    renderQuickActions();
    closeQAModal();
}
