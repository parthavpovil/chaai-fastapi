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

  function injectStyles(primaryColor) {
    var css = [
      '#chatsaas-root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; position: fixed; bottom: 20px; right: 20px; z-index: 999999; }',
      '#chatsaas-bubble { width: 56px; height: 56px; border-radius: 50%; background: ' + primaryColor + '; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(0,0,0,0.2); transition: transform 0.15s; }',
      '#chatsaas-bubble:hover { transform: scale(1.08); }',
      '#chatsaas-bubble svg { fill: #fff; width: 26px; height: 26px; }',
      '#chatsaas-panel { display: none; flex-direction: column; width: 340px; height: 480px; background: #fff; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.18); overflow: hidden; margin-bottom: 12px; }',
      '#chatsaas-panel.open { display: flex; }',
      '#chatsaas-header { background: ' + primaryColor + '; color: #fff; padding: 14px 16px; font-size: 15px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }',
      '#chatsaas-close { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; line-height: 1; padding: 0; }',
      '#chatsaas-messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }',
      '.cs-msg { max-width: 80%; padding: 8px 12px; border-radius: 12px; font-size: 14px; line-height: 1.45; word-break: break-word; }',
      '.cs-msg.user { background: ' + primaryColor + '; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }',
      '.cs-msg.assistant { background: #f1f1f1; color: #222; align-self: flex-start; border-bottom-left-radius: 4px; }',
      '#chatsaas-input-area { border-top: 1px solid #eee; display: flex; padding: 8px; gap: 8px; align-items: center; }',
      '#chatsaas-input { flex: 1; border: 1px solid #ddd; border-radius: 20px; padding: 8px 14px; font-size: 14px; outline: none; resize: none; font-family: inherit; }',
      '#chatsaas-input:focus { border-color: ' + primaryColor + '; }',
      '#chatsaas-send { background: ' + primaryColor + '; color: #fff; border: none; border-radius: 50%; width: 38px; height: 38px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }',
      '#chatsaas-send:disabled { opacity: 0.5; cursor: default; }',
      '#chatsaas-send svg { fill: #fff; width: 18px; height: 18px; }',
      '.cs-typing { font-size: 12px; color: #999; padding: 0 4px; }',
      // Media / attachment styles
      '#chatsaas-attach { background: none; border: none; cursor: pointer; padding: 4px; color: #888; display: flex; align-items: center; flex-shrink: 0; }',
      '#chatsaas-attach:hover { color: #555; }',
      '#chatsaas-attach svg { width: 20px; height: 20px; fill: currentColor; }',
      '#chatsaas-file-input { display: none; }',
      '.cs-upload-progress { font-size: 12px; color: #999; font-style: italic; padding: 4px 12px; align-self: flex-end; }',
      '.cs-msg img { max-width: 220px; border-radius: 8px; display: block; margin-top: 4px; cursor: pointer; }',
      '.cs-msg a.doc-link { color: inherit; text-decoration: underline; font-size: 13px; display: block; margin-top: 2px; }'
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
    inputArea.innerHTML =
      '<input type="file" id="chatsaas-file-input" accept="image/jpeg,image/png,image/webp,application/pdf,video/mp4,audio/mpeg,audio/ogg,audio/aac">' +
      '<button id="chatsaas-attach" title="Attach file"><svg viewBox="0 0 24 24"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 0 1 5 0v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6h-1.5v9.5a2.5 2.5 0 0 0 5 0V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6H16.5z"/></svg></button>' +
      '<textarea id="chatsaas-input" rows="1" placeholder="Type a message..."></textarea>' +
      '<button id="chatsaas-send"><svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg></button>';

    panel.appendChild(header);
    panel.appendChild(messages);
    panel.appendChild(inputArea);

    var bubble = document.createElement('button');
    bubble.id = 'chatsaas-bubble';
    bubble.setAttribute('aria-label', 'Open chat');
    bubble.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4C2.9 2 2 2.9 2 4v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>';

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
        if (sendData.response) {
          appendMessage(sendData.response, 'assistant');
          last_message_count += 1;
        }
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
    startPolling();
  }

  function closePanel() {
    var panel = document.getElementById('chatsaas-panel');
    if (panel) panel.classList.remove('open');
    is_open = false;
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
        }
        if (data.response) appendMessage(data.response, 'assistant');
        last_message_count += (data.response ? 2 : 1);
      })
      .catch(function (err) {
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
        (data.messages || []).forEach(function (msg) {
          renderMessage(msg);
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

        injectStyles(data.primary_color || '#4f46e5');
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
