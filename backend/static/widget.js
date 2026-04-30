/**
 * ChatSaaS WebChat Widget
 * Embed: <script src="/static/widget.js" data-workspace="your-workspace-slug"></script>
 */
(function () {
  'use strict';

  var API_BASE = '';
  var widget_id = null;
  var session_token = null;
  var poll_interval = null;
  var last_message_count = 0;
  var is_open = false;
  var config = {};

  // ── WebSocket state ─────────────────────────────────────────────────────────
  var ws = null;
  var ws_retry_count = 0;
  var ws_retry_timer = null;
  var ws_ping_interval = null;
  var WS_MAX_RETRIES = 5;
  var ws_enabled = (typeof WebSocket !== 'undefined');
  var rendered_message_ids = {}; // {message_id: true} — dedup guard

  // ── Resolve API base from script tag src ──────────────────────────────────

  function getApiBase() {
    var scripts = document.querySelectorAll('script[data-workspace]');
    if (!scripts.length) return '';
    var src = scripts[scripts.length - 1].src;
    var url = new URL(src);
    return url.origin;
  }

  function getWorkspaceSlug() {
    var scripts = document.querySelectorAll('script[data-workspace]');
    if (!scripts.length) return null;
    return scripts[scripts.length - 1].getAttribute('data-workspace');
  }

  // ── Storage helpers ────────────────────────────────────────────────────────

  function getStorageKey() {
    return 'chatsaas_session_' + (config.widget_id || 'default');
  }

  function saveSession(token) {
    try { localStorage.setItem(getStorageKey(), token); } catch (e) {}
  }

  function loadSession() {
    try { return localStorage.getItem(getStorageKey()); } catch (e) { return null; }
  }

  // ── API helpers ────────────────────────────────────────────────────────────

  function apiFetch(path, options) {
    return fetch(API_BASE + path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, options || {}));
  }

  // ── CSS injection ──────────────────────────────────────────────────────────

  function _resolveFont(fontFamily) {
    if (!fontFamily || fontFamily === 'System Default') {
      return '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    }
    return '"' + fontFamily + '", sans-serif';
  }

  function _bubbleSize(launcherSize) {
    if (launcherSize === 'small') return '48px';
    if (launcherSize === 'large') return '64px';
    return '56px'; // medium (default)
  }

  function _bubbleRadius(launcherShape) {
    return launcherShape === 'rounded-rectangle' ? '16px' : '50%';
  }

  function _rootPosition(cfg) {
    var h = (cfg.horizontal_offset != null ? cfg.horizontal_offset : 20) + 'px';
    var v = (cfg.vertical_offset != null ? cfg.vertical_offset : 20) + 'px';
    var pos = cfg.position || 'bottom-right';
    var parts = pos.split('-'); // ['bottom','right'] etc.
    var vert = parts[0] || 'bottom';
    var horiz = parts[1] || 'right';
    return vert + ': ' + v + '; ' + horiz + ': ' + h + ';';
  }

  function injectStyles(cfg) {
    var primary = cfg.primary_color || '#4F46E5';
    var userBubble = cfg.user_bubble_color || primary;
    var agentBubble = cfg.agent_bubble_color || '#F3F4F6';
    var textColor = cfg.text_color || '#FFFFFF';
    var fontSize = cfg.base_font_size || '13px';
    var fontFamily = _resolveFont(cfg.font_family);
    var bubbleSz = _bubbleSize(cfg.launcher_size);
    var bubbleRadius = _bubbleRadius(cfg.launcher_shape);
    var windowW = (cfg.chat_window_width || 360) + 'px';
    var windowH = (cfg.chat_window_height || 520) + 'px';
    var rootPos = _rootPosition(cfg);
    var pulseAnim = cfg.pulse_animation
      ? '@keyframes chatsaas-pulse { 0%,100%{box-shadow:0 4px 12px rgba(0,0,0,0.2),0 0 0 0 ' + primary + '66} 50%{box-shadow:0 4px 12px rgba(0,0,0,0.2),0 0 0 8px transparent} }'
        + ' #chatsaas-bubble { animation: chatsaas-pulse 2s infinite; }'
      : '';

    var css = [
      '#chatsaas-root { font-family: ' + fontFamily + '; font-size: ' + fontSize + '; position: fixed; ' + rootPos + ' z-index: 999999; }',
      '#chatsaas-bubble { width: ' + bubbleSz + '; height: ' + bubbleSz + '; border-radius: ' + bubbleRadius + '; background: ' + primary + '; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(0,0,0,0.2); transition: transform 0.15s; }',
      '#chatsaas-bubble:hover { transform: scale(1.08); }',
      '#chatsaas-bubble svg { fill: ' + textColor + '; width: 26px; height: 26px; }',
      '#chatsaas-panel { display: none; flex-direction: column; width: ' + windowW + '; height: ' + windowH + '; background: #fff; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.18); overflow: hidden; margin-bottom: 12px; }',
      '#chatsaas-panel.open { display: flex; }',
      '#chatsaas-header { background: ' + primary + '; color: ' + textColor + '; padding: 14px 16px; font-size: 15px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }',
      '#chatsaas-close { background: none; border: none; color: ' + textColor + '; font-size: 20px; cursor: pointer; line-height: 1; padding: 0; }',
      '#chatsaas-messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }',
      '.cs-msg { max-width: 80%; padding: 8px 12px; border-radius: 12px; font-size: inherit; line-height: 1.45; word-break: break-word; }',
      '.cs-msg.user { background: ' + userBubble + '; color: ' + textColor + '; align-self: flex-end; border-bottom-right-radius: 4px; }',
      '.cs-msg.assistant { background: ' + agentBubble + '; color: #222; align-self: flex-start; border-bottom-left-radius: 4px; }',
      '#chatsaas-input-area { border-top: 1px solid #eee; display: flex; padding: 8px; gap: 8px; align-items: center; }',
      '#chatsaas-input { flex: 1; border: 1px solid #ddd; border-radius: 20px; padding: 8px 14px; font-size: inherit; outline: none; resize: none; font-family: inherit; }',
      '#chatsaas-input:focus { border-color: ' + primary + '; }',
      '#chatsaas-send { background: ' + primary + '; color: ' + textColor + '; border: none; border-radius: 50%; width: 38px; height: 38px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }',
      '#chatsaas-send:disabled { opacity: 0.5; cursor: default; }',
      '#chatsaas-send svg { fill: ' + textColor + '; width: 18px; height: 18px; }',
      '.cs-typing { font-size: 12px; color: #999; padding: 0 4px; }',
      // Media / attachment styles
      '#chatsaas-attach { background: none; border: none; cursor: pointer; padding: 4px; color: #888; display: flex; align-items: center; flex-shrink: 0; }',
      '#chatsaas-attach:hover { color: #555; }',
      '#chatsaas-attach svg { width: 20px; height: 20px; fill: currentColor; }',
      '#chatsaas-file-input { display: none; }',
      '.cs-upload-progress { font-size: 12px; color: #999; font-style: italic; padding: 4px 12px; align-self: flex-end; }',
      '.cs-msg img { max-width: 220px; border-radius: 8px; display: block; margin-top: 4px; cursor: pointer; }',
      '.cs-msg a.doc-link { color: inherit; text-decoration: underline; font-size: 13px; display: block; margin-top: 2px; }',
      pulseAnim,
    ].join('\n');

    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ── DOM construction ───────────────────────────────────────────────────────

  function buildWidget() {
    var root = document.createElement('div');
    root.id = 'chatsaas-root';

    var panel = document.createElement('div');
    panel.id = 'chatsaas-panel';

    var header = document.createElement('div');
    header.id = 'chatsaas-header';
    header.innerHTML = '<span>' + escapeHtml(config.business_name || 'Chat') + '</span><button id="chatsaas-close">&times;</button>';

    var messages = document.createElement('div');
    messages.id = 'chatsaas-messages';

    var inputArea = document.createElement('div');
    inputArea.id = 'chatsaas-input-area';
    var placeholder = escapeHtml(config.placeholder_text || 'Type a message\u2026');
    inputArea.innerHTML =
      '<input type="file" id="chatsaas-file-input" accept="image/jpeg,image/png,image/webp,application/pdf,video/mp4,audio/mpeg,audio/ogg,audio/aac">' +
      '<button id="chatsaas-attach" title="Attach file"><svg viewBox="0 0 24 24"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 0 1 5 0v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6h-1.5v9.5a2.5 2.5 0 0 0 5 0V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6H16.5z"/></svg></button>' +
      '<textarea id="chatsaas-input" rows="1" placeholder="' + placeholder + '"></textarea>' +
      '<button id="chatsaas-send"><svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg></button>';

    panel.appendChild(header);
    panel.appendChild(messages);
    panel.appendChild(inputArea);

    var bubble = document.createElement('button');
    bubble.id = 'chatsaas-bubble';
    bubble.setAttribute('aria-label', 'Open chat');
    // Launcher icon SVG paths
    var iconSvgs = {
      'chat-bubble': '<svg viewBox="0 0 24 24"><path d="M20 2H4C2.9 2 2 2.9 2 4v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>',
      'message-circle': '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
      'headset': '<svg viewBox="0 0 24 24"><path d="M12 1a9 9 0 0 0-9 9v7a3 3 0 0 0 3 3h2v-8H6v-2a6 6 0 0 1 12 0v2h-2v8h2a3 3 0 0 0 3-3v-7a9 9 0 0 0-9-9z"/></svg>',
      'question-mark': '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z"/></svg>',
    };
    var launcherIcon = config.launcher_icon || 'chat-bubble';
    var iconHtml;
    if (launcherIcon === 'custom-image' && config.launcher_icon_url) {
      iconHtml = '<img src="' + escapeHtml(config.launcher_icon_url) + '" alt="" style="width:28px;height:28px;object-fit:contain;">';
    } else {
      iconHtml = iconSvgs[launcherIcon] || iconSvgs['chat-bubble'];
    }
    var launcherLabel = config.launcher_label ? '<span style="margin-left:6px;font-size:13px;font-weight:600;white-space:nowrap;">' + escapeHtml(config.launcher_label) + '</span>' : '';
    bubble.innerHTML = iconHtml + launcherLabel;
    if (launcherLabel) {
      bubble.style.borderRadius = '999px';
      bubble.style.padding = '0 16px';
      bubble.style.width = 'auto';
    }

    root.appendChild(panel);
    root.appendChild(bubble);
    document.body.appendChild(root);

    // Event listeners
    bubble.addEventListener('click', togglePanel);
    document.getElementById('chatsaas-close').addEventListener('click', closePanel);
    document.getElementById('chatsaas-send').addEventListener('click', sendMessage);
    document.getElementById('chatsaas-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    document.getElementById('chatsaas-attach').addEventListener('click', function () {
      document.getElementById('chatsaas-file-input').click();
    });
    document.getElementById('chatsaas-file-input').addEventListener('change', handleFileSelect);
  }

  function escapeHtml(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function appendMessage(content, role) {
    var container = document.getElementById('chatsaas-messages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'cs-msg ' + (role === 'user' ? 'user' : 'assistant');
    div.textContent = content;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function appendMediaMessage(mediaData, role) {
    var container = document.getElementById('chatsaas-messages');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'cs-msg ' + (role === 'user' ? 'user' : 'assistant');

    if (mediaData.message_type === 'image') {
      var img = document.createElement('img');
      img.src = mediaData.url;
      img.alt = escapeHtml(mediaData.filename || 'Image');
      img.addEventListener('click', function () { window.open(mediaData.url, '_blank'); });
      div.appendChild(img);
    } else {
      var prefix = mediaData.message_type === 'audio' ? 'Audio: '
                 : mediaData.message_type === 'video' ? 'Video: '
                 : 'File: ';
      var a = document.createElement('a');
      a.href = mediaData.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.className = 'doc-link';
      a.textContent = prefix + escapeHtml(mediaData.filename || 'download');
      div.appendChild(a);
    }

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function renderMessage(msg) {
    var role = msg.sender_type === 'user' ? 'user' : 'assistant';
    if (msg.msg_type && msg.msg_type !== 'text' && msg.media_url) {
      appendMediaMessage({
        url: msg.media_url,
        filename: msg.media_filename,
        message_type: msg.msg_type,
      }, role);
      if (msg.content && msg.content !== '[User sent a file]') {
        appendMessage(msg.content, role);
      }
    } else {
      appendMessage(msg.content || '', role);
    }
  }

  function renderCsatPrompt(token) {
    var container = document.getElementById('chatsaas-messages');
    if (!container) return;

    var wrap = document.createElement('div');
    wrap.className = 'cs-msg assistant';
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = '6px';

    var label = document.createElement('div');
    label.textContent = 'How would you rate your experience?';
    wrap.appendChild(label);

    var stars = document.createElement('div');
    stars.style.display = 'flex';
    stars.style.gap = '4px';

    [1, 2, 3, 4, 5].forEach(function (n) {
      var btn = document.createElement('button');
      btn.textContent = '★';
      btn.style.cssText = 'background:none;border:none;font-size:22px;cursor:pointer;color:#ccc;padding:0;';
      btn.addEventListener('mouseover', function () {
        Array.from(stars.children).forEach(function (b, i) {
          b.style.color = i < n ? '#f5a623' : '#ccc';
        });
      });
      btn.addEventListener('mouseout', function () {
        Array.from(stars.children).forEach(function (b) { b.style.color = '#ccc'; });
      });
      btn.addEventListener('click', function () {
        wrap.innerHTML = '';
        var thanks = document.createElement('div');
        thanks.textContent = 'Thanks for your feedback!';
        wrap.appendChild(thanks);
        apiFetch('/api/webchat/csat', {
          method: 'POST',
          body: JSON.stringify({ token: token, rating: n })
        }).catch(function () {});
      });
      stars.appendChild(btn);
    });

    wrap.appendChild(stars);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // ── File upload ────────────────────────────────────────────────────────────

  function handleFileSelect(e) {
    var file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file || !widget_id || !session_token) {
      if (!session_token) {
        appendMessage('Please send a text message first to start a conversation before attaching files.', 'assistant');
      }
      return;
    }

    var progressId = 'upload-' + Date.now();
    var container = document.getElementById('chatsaas-messages');
    var prog = document.createElement('div');
    prog.id = progressId;
    prog.className = 'cs-upload-progress';
    prog.textContent = 'Uploading ' + escapeHtml(file.name) + '...';
    if (container) {
      container.appendChild(prog);
      container.scrollTop = container.scrollHeight;
    }

    var formData = new FormData();
    formData.append('widget_id', widget_id);
    formData.append('session_token', session_token);
    formData.append('file', file);

    fetch(API_BASE + '/api/webchat/upload', { method: 'POST', body: formData })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || 'Upload failed'); });
        return r.json();
      })
      .then(function (uploadData) {
        var p = document.getElementById(progressId);
        if (p) p.remove();

        // Optimistic local display
        appendMediaMessage(uploadData, 'user');
        last_message_count += 1;

        // Send the message referencing the uploaded media
        var body = {
          widget_id: widget_id,
          session_token: session_token,
          media_url: uploadData.url,
          media_mime_type: uploadData.mime_type,
          media_filename: uploadData.filename,
          media_size: uploadData.size,
          message_type: uploadData.message_type,
        };

        return apiFetch('/api/webchat/send', { method: 'POST', body: JSON.stringify(body) })
          .then(function (r) { return r.json(); });
      })
      .then(function (sendData) {
        if (sendData.session_token) {
          session_token = sendData.session_token;
          saveSession(session_token);
        }
        // Assistant replies are rendered only from WebSocket/polling,
        // never from the HTTP /send response.
      })
      .catch(function (err) {
        var p = document.getElementById(progressId);
        if (p) p.remove();
        appendMessage('Upload failed: ' + (err.message || 'Unknown error'), 'assistant');
      });
  }

  // ── Panel controls ─────────────────────────────────────────────────────────

  function togglePanel() {
    if (is_open) closePanel(); else openPanel();
  }

  function openPanel() {
    var panel = document.getElementById('chatsaas-panel');
    if (panel) panel.classList.add('open');
    is_open = true;
    loadHistory();
    if (ws_enabled && session_token && config.workspace_id) {
      connectWebSocket();
    } else {
      startPolling();
    }
  }

  function closePanel() {
    var panel = document.getElementById('chatsaas-panel');
    if (panel) panel.classList.remove('open');
    is_open = false;
    disconnectWebSocket();
    stopPolling();
  }

  // ── Message sending ────────────────────────────────────────────────────────

  function sendMessage() {
    var input = document.getElementById('chatsaas-input');
    var send = document.getElementById('chatsaas-send');
    if (!input || !widget_id) return;

    var text = input.value.trim();
    if (!text) return;

    input.value = '';
    send.disabled = true;
    appendMessage(text, 'user');

    var body = { widget_id: widget_id, message: text };
    if (session_token) body.session_token = session_token;

    apiFetch('/api/webchat/send', { method: 'POST', body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.session_token) {
          session_token = data.session_token;
          saveSession(session_token);
          // Now that we have a session_token, connect WS if not already connected
          if (ws_enabled && config.workspace_id && (!ws || ws.readyState !== WebSocket.OPEN)) {
            connectWebSocket();
          }
        }
        // Mark the user message id as rendered to prevent double-render from WS push
        if (data.message_id) rendered_message_ids[data.message_id] = true;
        // Assistant replies are rendered only from WebSocket/polling,
        // never from the HTTP /send response.
        last_message_count += 1;
      })
      .catch(function () {
        appendMessage('Sorry, something went wrong. Please try again.', 'assistant');
      })
      .finally(function () { send.disabled = false; });
  }

  // ── History loading ────────────────────────────────────────────────────────

  function loadHistory() {
    if (!widget_id || !session_token) return;
    var url = '/api/webchat/messages?widget_id=' + encodeURIComponent(widget_id) + '&session_token=' + encodeURIComponent(session_token);
    apiFetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var container = document.getElementById('chatsaas-messages');
        if (!container) return;
        container.innerHTML = '';
        rendered_message_ids = {}; // reset on full reload
        (data.messages || []).forEach(function (msg) {
          renderMessage(msg);
          if (msg.id) rendered_message_ids[msg.id] = true;
        });
        last_message_count = (data.messages || []).length;
      })
      .catch(function () {});
  }

  // ── Polling for new messages ───────────────────────────────────────────────

  function startPolling() {
    stopPolling();
    poll_interval = setInterval(function () {
      if (!is_open || !widget_id || !session_token) return;
      var url = '/api/webchat/messages?widget_id=' + encodeURIComponent(widget_id) + '&session_token=' + encodeURIComponent(session_token);
      apiFetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var msgs = data.messages || [];
          if (msgs.length > last_message_count) {
            var container = document.getElementById('chatsaas-messages');
            if (!container) return;
            container.innerHTML = '';
            msgs.forEach(function (msg) {
              renderMessage(msg);
            });
            last_message_count = msgs.length;
          }
        })
        .catch(function () {});
    }, 3000);
  }

  function stopPolling() {
    if (poll_interval) { clearInterval(poll_interval); poll_interval = null; }
  }

  // ── WebSocket (primary real-time channel) ──────────────────────────────────

  function connectWebSocket() {
    if (!ws_enabled || !widget_id || !session_token || !config.workspace_id) return;
    if (ws && ws.readyState === WebSocket.OPEN) return;

    var wsBase = API_BASE.replace(/^http/, 'ws');
    var url = wsBase + '/ws/webchat/' + encodeURIComponent(config.workspace_id)
      + '?widget_id=' + encodeURIComponent(widget_id)
      + '&session_token=' + encodeURIComponent(session_token);

    try {
      ws = new WebSocket(url);
    } catch (e) {
      fallbackToPolling();
      return;
    }

    ws.onopen = function () {
      ws_retry_count = 0;
      stopPolling(); // WS is up — no need to poll
      startWsPing();
    };

    ws.onmessage = function (event) {
      try {
        handleServerPush(JSON.parse(event.data));
      } catch (e) {}
    };

    ws.onerror = function () {
      // onclose fires after onerror — handle reconnect there
    };

    ws.onclose = function () {
      ws = null;
      stopWsPing();
      if (ws_retry_count < WS_MAX_RETRIES) {
        ws_retry_count++;
        var delay = Math.min(1000 * Math.pow(2, ws_retry_count - 1), 30000);
        ws_retry_timer = setTimeout(function () {
          if (is_open) connectWebSocket();
        }, delay);
      } else {
        fallbackToPolling();
      }
    };
  }

  function disconnectWebSocket() {
    if (ws_retry_timer) { clearTimeout(ws_retry_timer); ws_retry_timer = null; }
    stopWsPing();
    if (ws) {
      ws.onclose = null; // prevent reconnect loop on intentional close
      ws.close(1000, 'Panel closed');
      ws = null;
    }
  }

  function fallbackToPolling() {
    ws_enabled = false;
    if (is_open && !poll_interval) startPolling();
  }

  function startWsPing() {
    stopWsPing();
    ws_ping_interval = setInterval(function () {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 25000);
  }

  function stopWsPing() {
    if (ws_ping_interval) { clearInterval(ws_ping_interval); ws_ping_interval = null; }
  }

  function handleServerPush(msg) {
    if (!msg || !msg.type) return;

    if (msg.type === 'pong') return; // keepalive, ignore

    if (msg.type === 'new_message') {
      // Dedup: skip if already rendered (history load or HTTP response)
      if (msg.message_id && rendered_message_ids[msg.message_id]) return;

      // Only render server-pushed replies (assistant / agent)
      // Customer's own messages are rendered optimistically in sendMessage()
      if (msg.role === 'assistant' || msg.role === 'agent') {
        if (msg.message_id) rendered_message_ids[msg.message_id] = true;
        if (msg.msg_type && msg.msg_type !== 'text' && msg.media_url) {
          appendMediaMessage({ url: msg.media_url, filename: msg.media_filename, message_type: msg.msg_type }, 'assistant');
          if (msg.content && msg.content !== '[User sent a file]') {
            appendMessage(msg.content, 'assistant');
          }
        } else {
          appendMessage(msg.content || '', 'assistant');
        }
        last_message_count += 1;
      } else if (msg.message_id) {
        rendered_message_ids[msg.message_id] = true;
      }
      return;
    }

    if (msg.type === 'conversation_status_changed') {
      if (msg.new_status === 'agent' && msg.agent_name) {
        appendMessage('You are now connected with ' + escapeHtml(msg.agent_name) + '.', 'assistant');
      } else if (msg.new_status === 'agent') {
        appendMessage('You are now connected with a support agent.', 'assistant');
      } else if (msg.new_status === 'escalated') {
        appendMessage('Your request has been escalated to our support team.', 'assistant');
      } else if (msg.new_status === 'resolved') {
        appendMessage('This conversation has been resolved. Thank you!', 'assistant');
      }
      return;
    }

    if (msg.type === 'csat_prompt' && msg.token) {
      renderCsatPrompt(msg.token);
      return;
    }
  }

  // ── Welcome message ────────────────────────────────────────────────────────

  function showWelcome() {
    if (config.welcome_message) appendMessage(config.welcome_message, 'assistant');
  }

  // ── Initialisation ─────────────────────────────────────────────────────────

  function init() {
    API_BASE = getApiBase();
    var slug = getWorkspaceSlug();
    if (!slug) return;

    apiFetch('/api/webchat/config/' + encodeURIComponent(slug))
      .then(function (r) {
        if (!r.ok) throw new Error('Widget config not found');
        return r.json();
      })
      .then(function (data) {
        config = data;
        widget_id = data.widget_id;
        session_token = loadSession();

        injectStyles(config);
        buildWidget();

        if (!session_token) showWelcome();
      })
      .catch(function (err) {
        console.warn('[ChatSaaS] Widget failed to load:', err.message);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
