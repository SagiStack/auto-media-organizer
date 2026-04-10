// --- State Management ---
let socket = null;
let currentTab = 'dashboard';
let config = null;
let distributionChart = null;
let isServiceRunning = false;
let systemPaths = null;

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initWebSocket();
  fetchConfig();
  fetchSystemPaths();
  refreshDashboard();
  initControlHandlers();
  initSettingsHandlers();
  initServicePolling();
  initPathChips();
  initEngineControl();
});

// --- Tabs & Navigation ---
function initTabs() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      switchTab(tab);
    });
  });

  // Settings sub-navigation
  document.querySelectorAll('.set-nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pane = btn.dataset.set;
      document.querySelectorAll('.set-nav-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.set-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`set-pane-${pane}`).classList.add('active');
    });
  });
}

function switchTab(tabId) {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === `tab-${tabId}`);
  });
  currentTab = tabId;
  if (tabId === 'dashboard') refreshDashboard();
  if (tabId === 'library') fetchLibrary();
  if (tabId === 'duplicates') fetchDuplicates();
}

// --- Library / Gallery Logic ---
async function fetchLibrary() {
  const filter = document.getElementById('library-filter') ? document.getElementById('library-filter').value : '';
  try {
    const res = await fetch(`/api/library?category=${encodeURIComponent(filter)}`);
    const files = await res.json();
    renderLibrary(files);
  } catch (e) {
    console.error("Failed to fetch library:", e);
  }
}

function renderLibrary(files) {
  const grid = document.getElementById('library-grid');
  if (!grid) return;
  if (files.length === 0) {
    grid.innerHTML = `<div class="empty-state"><i class="bi bi-images"></i><p>Your library is empty. Organize some files to see them here!</p></div>`;
    return;
  }

  grid.innerHTML = files.map(file => {
    const name = file.file_path.split(/[\\/]/).pop();
    const isImage = ["Images", "Videos"].includes(file.category);
    const thumbUrl = isImage ? `/api/thumbnails?path=${encodeURIComponent(file.file_path)}` : '';
    
    return `
      <div class="thumb-card" title="${file.file_path}">
        ${isImage ? `<img src="${thumbUrl}" alt="${name}" loading="lazy" onerror="this.src='https://placehold.co/200?text=Error'">` : `<div class="file-placeholder" style="display:flex;align-items:center;justify-content:center;height:100%;font-size:3rem;opacity:0.2;"><i class="bi bi-file-earmark"></i></div>`}
        <div class="thumb-meta">
          <strong>${name}</strong><br>
          <span class="dim">${file.category}</span>
        </div>
      </div>
    `;
  }).join('');
}

// --- Duplicate Resolution Logic ---
async function fetchDuplicates() {
  try {
    const res = await fetch('/api/duplicates');
    const groups = await res.json();
    renderDuplicates(groups);
  } catch (e) {
    console.error("Failed to fetch duplicates:", e);
  }
}

function renderDuplicates(groups) {
  const container = document.getElementById('duplicates-container');
  if (!container) return;
  if (groups.length === 0) {
    container.innerHTML = `<div class="empty-state"><i class="bi bi-check-circle"></i><p>No duplicates found! Your library is clean.</p></div>`;
    return;
  }

  container.innerHTML = groups.map(group => `
    <div class="duplicate-group" id="group-${group.hash}">
      <div class="dup-header">
        <h4><i class="bi bi-files"></i> Duplicate Collision Group</h4>
        <span class="badge-online" style="background:rgba(0,210,255,0.1);padding:2px 8px;border-radius:4px;">${group.files.length} Copies</span>
      </div>
      <div class="dup-items">
        ${group.files.map(file => `
          <div class="dup-file-card">
            <span class="dup-path">${file.file_path}</span>
            <div style="display:flex; justify-content:space-between; margin-top:0.5rem; font-size:0.8rem;">
               <span>${(file.size / 1024).toFixed(1)} KB</span>
               <span class="dim">${file.subcategory}</span>
            </div>
            <div class="dup-actions">
               <button class="btn btn-outline btn-sm" onclick="resolveDuplicate('${file.file_path.replace(/\\/g, '\\\\')}', '${group.hash}')">Delete This Copy</button>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}

window.resolveDuplicate = async function(path, groupHash) {
  if (!confirm("Are you sure you want to delete this specific copy? This action cannot be undone.")) return;
  
  try {
    const res = await fetch(`/api/files?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.status === 'success') {
      fetchDuplicates(); // Refresh
      fetchLibrary();    // Update gallery too
    } else {
      alert("Error: " + data.message);
    }
  } catch (e) {
    alert("Request failed: " + e);
  }
}

// --- WebSocket Logic ---
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

  socket.onopen = () => {
    logToTerminal("System: Connection established with backend.", "sys");
    document.getElementById('status-badge').className = 'badge-online';
  };

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleSocketMessage(data);
  };

  socket.onclose = () => {
    logToTerminal("System: Connection lost. Retrying...", "error");
    document.getElementById('status-badge').className = 'badge-offline';
    setTimeout(initWebSocket, 5000);
  };
}

function handleSocketMessage(msg) {
  if (msg.type === 'progress') {
    updateProgressBar(msg.current, msg.total, msg.description);
    logToTerminal(`${msg.phase.toUpperCase()}: ${msg.description}`);
  } else if (msg.type === 'complete') {
    updateProgressBar(1, 1, "Task Complete");
    logToTerminal(`System: ${msg.phase} completed successfully.`, "success");
    setTimeout(refreshDashboard, 1500);
  } else if (msg.type === 'error') {
    logToTerminal(`ERROR: ${msg.message}`, "error");
    updateProgressBar(0, 1, "Failed");
  }
}

// --- Service Management ---
function initServicePolling() {
  const poll = async () => {
    try {
      const res = await fetch('/api/service/status');
      const data = await res.json();
      updateServiceUI(data.running);
    } catch (e) { console.error("Poll failed", e); }
  };
  setInterval(poll, 3000);
  poll();

  document.getElementById('btn-toggle-service').addEventListener('click', async () => {
    const source = document.getElementById('input-source').value;
    const res = await fetch(`/api/service/toggle?path=${source}`, { method: 'POST' });
    const data = await res.json();
    updateServiceUI(data.status === 'started');
    logToTerminal(`System: Watchdog ${data.status}`, "sys");
  });
}

function updateServiceUI(running) {
  isServiceRunning = running;
  const stateEl = document.getElementById('service-state');
  const btn = document.getElementById('btn-toggle-service');
  stateEl.textContent = running ? 'RUNNING' : 'OFF';
  stateEl.className = running ? 'state-on' : 'state-off';
  btn.classList.toggle('active', running);
}

// --- History & Undo ---
async function refreshDashboard() {
  try {
    const statsRes = await fetch('/api/stats');
    const stats = await statsRes.json();
    document.getElementById('count-files').textContent = stats.total_organized;
    document.getElementById('count-sessions').textContent = stats.total_sessions;
    
    // Auto-calibrate sliders based on real system capability
    const maxThreads = Math.max(stats.system_cpus || 4, 16);
    const dashSlider = document.getElementById('dash-worker-slider');
    const setSlider = document.getElementById('input-workers');
    const coreLabel = document.getElementById('engine-cores');
    
    if (dashSlider && setSlider) {
      dashSlider.max = maxThreads;
      setSlider.max = maxThreads;
      coreLabel.textContent = `/ ${stats.system_cpus || 4} Cores`;
    }

    const sessRes = await fetch('/api/history/sessions');
    const sessions = await sessRes.json();
    renderSessions(sessions);
    updateCharts(sessions);
  } catch (e) {
    console.error("Failed to refresh dashboard:", e);
  }
}

// --- Engine Power Controls ---
function initEngineControl() {
  const dashSlider = document.getElementById('dash-worker-slider');
  const setSlider = document.getElementById('input-workers');

  const handleUpdate = (val) => {
    updateEngineUI(val);
    if (setSlider) {
      setSlider.value = val;
      document.getElementById('val-workers').textContent = val;
    }
    if (config) {
      config.performance.max_workers = parseInt(val);
    }
  };

  if (dashSlider) {
    dashSlider.addEventListener('input', (e) => handleUpdate(e.target.value));
    dashSlider.addEventListener('change', () => saveConfig());
  }

  if (setSlider) {
    setSlider.addEventListener('input', (e) => {
      dashSlider.value = e.target.value;
      updateEngineUI(e.target.value);
    });
  }
}

function updateEngineUI(val) {
  const threads = parseInt(val);
  const modeEl = document.getElementById('engine-mode');
  const threadLabel = document.getElementById('engine-threads');
  const slider = document.getElementById('dash-worker-slider');
  
  threadLabel.textContent = `${threads} Worker${threads > 1 ? 's' : ''}`;

  // Mode mapping logic based on typical CPU counts
  let mode = 'Standard';
  let colorClass = 'mode-standard';
  const cpuCount = parseInt(document.getElementById('engine-cores').textContent.replace(/\D/g, '')) || 4;

  if (threads <= 2) {
    mode = 'Eco';
    colorClass = 'mode-eco';
  } else if (threads > cpuCount) {
    mode = 'Nitro';
    colorClass = 'mode-nitro';
  } else if (threads >= cpuCount * 0.75) {
    mode = 'Turbo';
    colorClass = 'mode-turbo';
  }

  modeEl.textContent = mode;
  modeEl.className = `mode-badge ${colorClass}`;
  
  // Set slider glow color dynamically
  const colors = { 'Eco': '#34d399', 'Standard': '#00d2ff', 'Turbo': '#9333ea', 'Nitro': '#ff4757' };
  slider.style.boxShadow = `0 0 15px ${colors[mode]}44`;
}

function renderSessions(sessions) {
  const container = document.getElementById('session-container');
  container.innerHTML = sessions.map(sess => `
    <div class="session-card">
      <div class="session-meta">
        <h4>Session ${sess.session_id.substring(0,8)}</h4>
        <p>${sess.count} files • ${new Date(sess.timestamp).toLocaleString()}</p>
      </div>
      <button class="btn-undo" onclick="undoSession('${sess.session_id}')">Revert</button>
    </div>
  `).join('');
}

async function undoSession(sid) {
  if (!confirm(`Are you sure you want to revert all changes from session ${sid.substring(0,8)}?`)) return;
  
  try {
    const res = await fetch(`/api/history/undo?session_id=${sid}`, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'success') {
      logToTerminal(`System: Reverted ${data.undone} files.`, "success");
      refreshDashboard();
    } else {
      logToTerminal(`Undo failed: ${data.message || data.errors.join(', ')}`, "error");
    }
  } catch (e) {
    logToTerminal(`Error during undo: ${e}`, "error");
  }
}

async function fetchSystemPaths() {
  try {
    const res = await fetch('/api/utils/paths');
    systemPaths = await res.json();
  } catch (e) { console.error("Could not fetch system paths"); }
}

function initPathChips() {
  document.querySelectorAll('.path-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const type = chip.dataset.path;
      if (systemPaths && systemPaths[type]) {
        document.getElementById('input-source').value = systemPaths[type];
        logToTerminal(`Quick Access: Switched to ${type} folder.`, "sys");
      }
    });
  });
}

// --- Control Center ---
function initControlHandlers() {
  document.getElementById('btn-analyze').addEventListener('click', () => triggerTask('analyze'));
  document.getElementById('btn-organize').addEventListener('click', () => triggerTask('organize'));
}

async function triggerTask(endpoint) {
  const source = document.getElementById('input-source').value;
  const target = document.getElementById('input-target').value;
  
  if (!source) return alert("Please specify a source directory.");

  // Clear feed for a new task to make it readable
  const feed = document.getElementById('terminal-feed');
  feed.innerHTML = '';
  
  logToTerminal(`System: Starting ${endpoint} task...`, "sys");
  document.getElementById('progress-container').style.display = 'flex';
  
  try {
    const res = await fetch(`/api/${endpoint}?path=${encodeURIComponent(source)}&target=${encodeURIComponent(target)}`, {
      method: 'POST'
    });
    const data = await res.json();
    if (data.status === 'error') {
      logToTerminal(`Failed: ${data.message}`, "error");
    } else if (data.path) {
      logToTerminal(`Targeting: ${data.path}`, "sys");
      
      // UX Hardening: If the path contains "Public" but the user likely meant their own profile
      if (data.path.toLowerCase().includes('public') && systemPaths) {
         logToTerminal(`TIP: Scanning 'Public' downloads often yields nothing. Did you mean: ${systemPaths.downloads}?`, "sys");
      }
    }
  } catch (e) {
    logToTerminal(`Error triggering task: ${e}`, "error");
  }
}

// --- Settings & Config ---
function initSettingsHandlers() {
  document.getElementById('btn-save-config').addEventListener('click', saveConfig);
  
  // Sync workers slider label
  document.getElementById('input-workers').addEventListener('input', (e) => {
    document.getElementById('val-workers').textContent = e.target.value;
  });
}

async function fetchConfig() {
  try {
    const res = await fetch('/api/config');
    config = await res.json();
    renderConfigForm(config);
    document.getElementById('config-textarea').value = JSON.stringify(config, null, 2);
  } catch (e) {
    console.error("Failed to fetch config:", e);
  }
}

function renderConfigForm(cfg) {
  // Sync Performance inputs
  document.getElementById('input-workers').value = cfg.performance.max_workers;
  document.getElementById('val-workers').textContent = cfg.performance.max_workers;
  document.getElementById('input-mp').checked = cfg.performance.use_multiprocessing;

  // Render Categories
  const container = document.getElementById('categories-form');
  container.innerHTML = '';
  
  for (const [cat, rules] of Object.entries(cfg.categories)) {
    const card = document.createElement('div');
    card.className = 'category-card';
    card.innerHTML = `
      <div class="category-header">
        <input type="text" value="${cat}" readonly>
        <span class="dim">${rules.extensions.length} extensions</span>
      </div>
      <div class="ext-tags">
        ${rules.extensions.map(ext => `<span class="ext-tag">${ext}</span>`).join('')}
      </div>
    `;
    container.appendChild(card);
  }
}

async function saveConfig() {
  // Merge form data back into config
  config.performance.max_workers = parseInt(document.getElementById('input-workers').value);
  config.performance.use_multiprocessing = document.getElementById('input-mp').checked;

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    const data = await res.json();
    if (data.status === 'success') {
      logToTerminal("System: Configuration updated.", "success");
      fetchConfig();
    }
  } catch (e) {
    logToTerminal(`Failed to save config: ${e}`, "error");
  }
}

// --- UI Helpers ---
function logToTerminal(message, type = '') {
  const feed = document.getElementById('terminal-feed');
  const entry = document.createElement('div');
  const time = new Date().toLocaleTimeString();
  entry.className = `log-entry ${type}`;
  entry.textContent = `[${time}] ${message}`;
  feed.appendChild(entry);
  feed.scrollTop = feed.scrollHeight;
}

function updateProgressBar(current, total, text) {
  const fill = document.getElementById('progress-bar-fill');
  const textEl = document.getElementById('progress-text');
  const percent = (current / total) * 100;
  fill.style.width = `${percent}%`;
  textEl.textContent = text ? `${text} (${Math.round(percent)}%)` : `${Math.round(percent)}%`;
}

function updateCharts(sessions) {
  // Simple summary of extensions across last few sessions
  const extCounts = {};
  sessions.forEach(s => {
    s.files.forEach(f => {
      const ext = f.split('.').pop().toLowerCase();
      extCounts[ext] = (extCounts[ext] || 0) + 1;
    });
  });

  const ctx = document.getElementById('distributionChart').getContext('2d');
  if (distributionChart) distributionChart.destroy();

  distributionChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: Object.keys(extCounts),
      datasets: [{
        data: Object.values(extCounts),
        backgroundColor: ['#00d2ff', '#9333ea', '#34d399', '#f87171', '#fbbf24'],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#a0a0a0' } }
      }
    }
  });
}

// Global expose for onclick
window.undoSession = undoSession;
