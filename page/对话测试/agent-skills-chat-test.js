const form = document.getElementById('chatForm');
const trace = document.getElementById('trace');
const statusEl = document.getElementById('status');
const eventCountEl = document.getElementById('eventCount');
const elapsedTimeEl = document.getElementById('elapsedTime');
const sendBtn = document.getElementById('sendBtn');
const stopBtn = document.getElementById('stopBtn');
const clearBtn = document.getElementById('clearBtn');
const sessionInput = document.getElementById('sessionId');
const promptInput = document.getElementById('prompt');

let abortController = null;
let activeRun = null;
let eventCount = 0;
let startedAt = 0;
let timerId = null;
let followLatest = true;
let pendingScrollFrame = null;

sessionInput.value = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());

trace.addEventListener('scroll', () => {
  followLatest = isTraceNearBottom();
});

function generateReqId() {
  return 'req_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
}

promptInput.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || sendBtn.disabled) {
    return;
  }
  event.preventDefault();
  form.requestSubmit();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const prompt = promptInput.value.trim();
  if (!prompt) {
    setStatus('请输入问题', 'error');
    return;
  }

  resetTraceIfEmpty();
  const userMessage = appendUserMessage(prompt);
  promptInput.value = '';
  promptInput.focus();
  followLatest = true;
  scrollTraceToLatest(true);
  stopTimer();
  eventCount = 0;
  startedAt = Date.now();
  updateEventCount();
  updateElapsedTime();

  abortController = new AbortController();
  const payload = {
    query: prompt,
    sessionId: sessionInput.value.trim() || undefined,
    userId: document.getElementById('userId').value.trim() || 'test-user',
    reqId: generateReqId()
  };
  activeRun = createAssistantRun(payload, userMessage);
  setStreaming(true);

  try {
    const response = await fetch('http://localhost:8000/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: abortController.signal
    });

    if (!response.ok || !response.body) {
      throw new Error('HTTP ' + response.status);
    }

    await readSseStream(response.body);
    setStatus('完成', 'done');
  } catch (error) {
    if (error.name === 'AbortError') {
      setStatus('已停止');
    } else {
      appendToolResult('error', error.message || String(error), 'error');
      setStatus('请求失败', 'error');
    }
  } finally {
    closeActiveSection();
    setStreaming(false);
    abortController = null;
    stopTimer();
  }
});

stopBtn.addEventListener('click', () => {
  if (abortController) {
    abortController.abort();
  }
});

clearBtn.addEventListener('click', () => {
  if (abortController) {
    abortController.abort();
  }
  trace.innerHTML = emptyStateHtml();
  activeRun = null;
  eventCount = 0;
  startedAt = 0;
  followLatest = true;
  cancelPendingScroll();
  stopTimer();
  updateEventCount();
  updateElapsedTime();
  setStatus('空闲');
});

async function readSseStream(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split(/\r?\n\r?\n/);
    buffer = chunks.pop() || '';
    chunks.forEach(handleSseChunk);
  }

  if (buffer.trim()) {
    handleSseChunk(buffer);
  }
}

function handleSseChunk(chunk) {
  const lines = chunk.split(/\r?\n/);
  const dataLines = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());
  const payloadText = dataLines.length ? dataLines.join('\n') : chunk.trim();
  if (!payloadText || payloadText === '[DONE]') {
    return;
  }

  try {
    handlePayload(JSON.parse(payloadText));
  } catch (error) {
    // Ignore non-JSON stream chunks that do not belong to displayed stages.
  }
}

function handlePayload(payload) {
  eventCount += 1;
  updateEventCount();
  const stage = normalizeStage(payload.stage || payload.event || payload.type);
  const content = normalizeContent(payload);

  if (!content.length) {
    return;
  }

  content.forEach((item) => {
    const value = pickValue(item);
    const type = item.type || item.name || item.toolName || item.functionName || stage;
    if (stage === 'think') {
      activateSection(activeRun.thinkBody);
      appendText(activeRun.thinkBody, value);
    } else if (stage === 'response') {
      closeActiveSection();
      appendMarkdownText(activeRun.responseBody, value);
    } else if (stage === 'tool') {
      appendToolCall(type, value);
    } else if (stage === 'tool_result') {
      appendToolResult(type, value);
    } else if (stage === 'card') {
      appendToolResult(type || 'card', value);
    }
  });
}

function createAssistantRun(payload, afterNode) {
  const wrap = document.createElement('div');
  wrap.className = 'message assistant';
  wrap.innerHTML = [
    runMetaHtml(payload),
    sectionHtml('think', '思考', '等待思考内容'),
    '<div class="tool-pairs" data-body="tool-pairs"></div>',
    sectionHtml('response', '回复', '等待回复内容')
  ].join('');
  trace.insertBefore(wrap, afterNode ? afterNode.nextSibling : null);
  scrollTraceToLatest(true);
  bindSectionToggles(wrap);
  return {
    thinkBody: wrap.querySelector('[data-body="think"]'),
    toolPairs: wrap.querySelector('[data-body="tool-pairs"]'),
    responseBody: wrap.querySelector('[data-body="response"]'),
    activeSection: null,
    currentToolPair: null,
    responseMarkdown: ''
  };
}

function sectionHtml(kind, title, emptyText) {
  const isList = kind === 'tool' || kind === 'tool-result';
  const bodyClass = kind === 'response' ? 'section-body empty markdown-body' : 'section-body empty';
  const body = isList
    ? '<div class="section-body" data-body="' + kind + '"><div class="event-list"><div class="section-body empty">' + escapeHtml(emptyText) + '</div></div></div>'
    : '<div class="' + bodyClass + '" data-body="' + kind + '">' + escapeHtml(emptyText) + '</div>';
  return '<section class="section ' + kind + '"><div class="section-head"><h3 class="section-title"><span class="dot"></span>' + escapeHtml(title) + '</h3><button class="section-toggle" type="button" aria-label="折叠' + escapeHtml(title) + '" aria-expanded="true">−</button></div>' + body + '</section>';
}

function runMetaHtml(payload) {
  const items = [
    ['session', payload.sessionId || '-'],
    ['user', payload.userId || '-'],
    ['reqId', payload.reqId || '-']
  ];
  return '<div class="run-meta">' + items.map(([key, value]) => '<span class="meta-pill">' + key + ': ' + escapeHtml(value) + '</span>').join('') + '</div>';
}

function appendUserMessage(text) {
  const wrap = document.createElement('div');
  wrap.className = 'message user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  wrap.appendChild(bubble);
  trace.appendChild(wrap);
  scrollTraceToLatest(true);
  return wrap;
}

function appendText(target, value) {
  const text = stringifyValue(value);
  if (!text) {
    return;
  }
  if (target.classList.contains('empty')) {
    target.textContent = '';
    target.classList.remove('empty');
  }
  target.textContent += text;
  scrollTraceToLatest();
}

function appendMarkdownText(target, value) {
  const text = stringifyValue(value);
  if (!text) {
    return;
  }
  if (target.classList.contains('empty')) {
    target.classList.remove('empty');
  }
  activeRun.responseMarkdown += text;
  target.innerHTML = renderMarkdown(activeRun.responseMarkdown);
  scrollTraceToLatest();
}

function appendToolCall(type, value) {
  closeActiveSection();
  const pair = createToolPair();
  activeRun.currentToolPair = pair;
  appendEvent(pair.toolList, type, value);
  activateSection(pair.toolList);
}

function appendToolResult(type, value, tone) {
  closeActiveSection();
  const pair = activeRun.currentToolPair || createToolPair();
  activeRun.currentToolPair = pair;
  pair.hasResult = true;
  appendEvent(pair.resultList, type, value, tone);
  activateSection(pair.resultList);
}

function createToolPair() {
  const wrap = document.createElement('div');
  wrap.className = 'tool-pair';
  wrap.innerHTML = sectionHtml('tool', '调用工具', '等待工具调用') + sectionHtml('tool-result', '工具返回', '等待工具返回');
  activeRun.toolPairs.appendChild(wrap);
  bindSectionToggles(wrap);
  return {
    toolList: wrap.querySelector('[data-body="tool"] .event-list'),
    resultList: wrap.querySelector('[data-body="tool-result"] .event-list'),
    hasResult: false
  };
}

function appendEvent(target, type, value, tone) {
  const empty = target.querySelector('.empty');
  if (empty) {
    empty.remove();
  }
  const item = document.createElement('div');
  item.className = 'event-item' + (tone ? ' ' + tone : '');
  const typeEl = document.createElement('div');
  typeEl.className = 'event-type';
  typeEl.textContent = type || 'event';
  const valueEl = document.createElement('div');
  valueEl.className = 'event-value';
  valueEl.textContent = stringifyValue(value);
  item.append(typeEl, valueEl);
  target.appendChild(item);
  scrollTraceToLatest();
}

function bindSectionToggles(scope) {
  scope.querySelectorAll('.section-toggle').forEach((button) => {
    button.addEventListener('click', () => {
      const section = button.closest('.section');
      setSectionCollapsed(section, !section.classList.contains('collapsed'));
    });
  });
}

function collapseSection(target) {
  const section = target.closest('.section');
  setSectionCollapsed(section, true);
}

function activateSection(target) {
  const section = target.closest('.section');
  if (!section || activeRun.activeSection === section) {
    setSectionCollapsed(section, false);
    return;
  }
  closeActiveSection();
  activeRun.activeSection = section;
  setSectionCollapsed(section, false);
}

function closeActiveSection() {
  if (activeRun && activeRun.activeSection) {
    setSectionCollapsed(activeRun.activeSection, true);
    activeRun.activeSection = null;
  }
}

function setSectionCollapsed(section, collapsed) {
  if (!section) {
    return;
  }
  section.classList.toggle('collapsed', collapsed);
  const button = section.querySelector('.section-toggle');
  if (button) {
    button.textContent = collapsed ? '+' : '−';
    button.setAttribute('aria-expanded', String(!collapsed));
  }
  scrollTraceToLatest();
}

function normalizeStage(stage) {
  const value = String(stage || 'unknown').toLowerCase().replace(/[-\s]/g, '_');
  if (value === 'thinking' || value === 'reasoning') {
    return 'think';
  }
  if (value === 'answer' || value === 'message' || value === 'reply') {
    return 'response';
  }
  if (value === 'tool_call' || value === 'tool_calls' || value === 'function_call') {
    return 'tool';
  }
  if (value === 'tool_result' || value === 'tool_response' || value === 'function_result') {
    return 'tool_result';
  }
  return value;
}

function normalizeContent(payload) {
  const source = payload.content ?? payload.contents ?? payload.data ?? payload.msg ?? payload.message;
  if (Array.isArray(source)) {
    return source;
  }
  if (source === undefined || source === null) {
    return [];
  }
  return [typeof source === 'object' ? source : { msg: source }];
}

function pickValue(item) {
  if (item === null || item === undefined || typeof item !== 'object') {
    return item;
  }
  if (item.msg !== undefined) {
    return item.msg;
  }
  if (item.data !== undefined) {
    return item.data;
  }
  if (item.content !== undefined) {
    return item.content;
  }
  if (item.arguments !== undefined) {
    return item.arguments;
  }
  if (item.result !== undefined) {
    return item.result;
  }
  return item;
}

function stringifyValue(value) {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function renderMarkdown(text) {
  const blocks = [];
  let listType = null;
  let paragraph = [];
  let inCode = false;
  let code = [];
  const closeParagraph = () => {
    if (paragraph.length) {
      blocks.push('<p>' + renderInlineMarkdown(paragraph.join(' ')) + '</p>');
      paragraph = [];
    }
  };
  const closeList = () => {
    if (listType) {
      blocks.push('</' + listType + '>');
      listType = null;
    }
  };
  const lines = text.split(/\r?\n/);
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const fence = line.match(/^```\s*(.*)$/);
    if (fence) {
      if (inCode) {
        blocks.push('<pre><code>' + escapeHtml(code.join('\n')) + '</code></pre>');
        inCode = false;
        code = [];
      } else {
        closeParagraph();
        closeList();
        inCode = true;
      }
      index += 1;
      continue;
    }
    if (inCode) {
      code.push(line);
      index += 1;
      continue;
    }
    if (!line.trim()) {
      closeParagraph();
      closeList();
      index += 1;
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeParagraph();
      closeList();
      blocks.push('<h' + heading[1].length + '>' + renderInlineMarkdown(heading[2]) + '</h' + heading[1].length + '>');
      index += 1;
      continue;
    }
    if (isMarkdownTable(lines, index)) {
      closeParagraph();
      closeList();
      const table = collectMarkdownTable(lines, index);
      blocks.push(renderMarkdownTable(table.rows));
      index = table.nextIndex;
      continue;
    }
    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      closeParagraph();
      const nextType = unordered ? 'ul' : 'ol';
      if (listType !== nextType) {
        closeList();
        blocks.push('<' + nextType + '>');
        listType = nextType;
      }
      blocks.push('<li>' + renderInlineMarkdown((unordered || ordered)[1]) + '</li>');
      index += 1;
      continue;
    }
    const quote = line.match(/^>\s?(.+)$/);
    if (quote) {
      closeParagraph();
      closeList();
      blocks.push('<blockquote>' + renderInlineMarkdown(quote[1]) + '</blockquote>');
      index += 1;
      continue;
    }
    paragraph.push(line.trim());
    index += 1;
  }
  if (inCode) {
    blocks.push('<pre><code>' + escapeHtml(code.join('\n')) + '</code></pre>');
  }
  closeParagraph();
  closeList();
  return blocks.join('');
}

function isMarkdownTable(lines, index) {
  return lines[index] && lines[index + 1] && /^\s*\|.+\|\s*$/.test(lines[index]) && /^\s*\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1]);
}

function collectMarkdownTable(lines, index) {
  const rows = [lines[index]];
  let nextIndex = index + 2;
  while (nextIndex < lines.length && /^\s*\|.+\|\s*$/.test(lines[nextIndex])) {
    rows.push(lines[nextIndex]);
    nextIndex += 1;
  }
  return { rows, nextIndex };
}

function renderMarkdownTable(rows) {
  const cells = rows.map(parseMarkdownTableRow);
  const header = cells[0] || [];
  const body = cells.slice(1);
  return '<table><thead><tr>' + header.map((cell) => '<th>' + renderInlineMarkdown(cell) + '</th>').join('') + '</tr></thead><tbody>' + body.map((row) => '<tr>' + row.map((cell) => '<td>' + renderInlineMarkdown(cell) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
}

function parseMarkdownTableRow(row) {
  return row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/_([^_]+)_/g, '<em>$1</em>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function emptyStateHtml() {
  return '<div class="empty-state"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 9h8"/><path d="M8 13h5"/></svg><span>发送问题后，这里会展示接口流式返回。</span></div>';
}

function resetTraceIfEmpty() {
  const empty = trace.querySelector('.empty-state');
  if (empty) {
    trace.innerHTML = '';
  }
}

function scrollTraceToLatest(force) {
  if (!force && !followLatest) {
    return;
  }
  cancelPendingScroll();
  pendingScrollFrame = window.requestAnimationFrame(() => {
    trace.scrollTop = trace.scrollHeight;
    pendingScrollFrame = null;
  });
}

function cancelPendingScroll() {
  if (pendingScrollFrame !== null) {
    window.cancelAnimationFrame(pendingScrollFrame);
    pendingScrollFrame = null;
  }
}

function isTraceNearBottom() {
  const threshold = 24;
  return trace.scrollHeight - trace.clientHeight - trace.scrollTop <= threshold;
}

function setStreaming(streaming) {
  sendBtn.disabled = streaming;
  sendBtn.hidden = streaming;
  stopBtn.disabled = !streaming;
  stopBtn.hidden = !streaming;
  if (streaming) {
    setStatus('流式接收中', 'streaming');
    timerId = window.setInterval(updateElapsedTime, 200);
  }
}

function setStatus(text, mode) {
  statusEl.textContent = text;
  statusEl.className = 'status' + (mode ? ' ' + mode : '');
}

function updateEventCount() {
  eventCountEl.textContent = eventCount + ' events';
}

function updateElapsedTime() {
  if (!startedAt) {
    elapsedTimeEl.textContent = '0.0s';
    return;
  }
  elapsedTimeEl.textContent = ((Date.now() - startedAt) / 1000).toFixed(1) + 's';
}

function stopTimer() {
  if (timerId) {
    window.clearInterval(timerId);
    timerId = null;
  }
  updateElapsedTime();
}
