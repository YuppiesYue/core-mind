    const tabs = [...document.querySelectorAll('.tab')];
    const panels = [...document.querySelectorAll('.panel')];

    const dashboardPreset = document.getElementById('dashboardPreset');
    const dashboardStart = document.getElementById('dashboardStart');
    const dashboardEnd = document.getElementById('dashboardEnd');
    const dashboardRefresh = document.getElementById('dashboardRefresh');

    const metricRequests = document.getElementById('metricRequests');
    const metricSessions = document.getElementById('metricSessions');
    const metricUsers = document.getElementById('metricUsers');

    const agentName = document.getElementById('agentName');
    const agentMaxIters = document.getElementById('agentMaxIters');
    const agentEnableSessionMemory = document.getElementById('agentEnableSessionMemory');
    const llmProvider = document.getElementById('llmProvider');
    const llmModel = document.getElementById('llmModel');
    const llmApiKey = document.getElementById('llmApiKey');
    const llmBaseUrl = document.getElementById('llmBaseUrl');
    const llmStream = document.getElementById('llmStream');
    const llmEnableThinking = document.getElementById('llmEnableThinking');
    const llmContextSize = document.getElementById('llmContextSize');
    const agentReset = document.getElementById('agentReset');
    const agentSave = document.getElementById('agentSave');

    const summaryName = document.getElementById('summaryName');
    const summaryModel = document.getElementById('summaryModel');
    const summaryMemory = document.getElementById('summaryMemory');
    const summaryStream = document.getElementById('summaryStream');
    const summaryThink = document.getElementById('summaryThink');
    const summaryContext = document.getElementById('summaryContext');

    const logSearch = document.getElementById('logSearch');
    const filterUserId = document.getElementById('filterUserId');
    const filterSessionId = document.getElementById('filterSessionId');
    const logSearchBtn = document.getElementById('logSearchBtn');
    const logClearBtn = document.getElementById('logClearBtn');
    const logTbody = document.getElementById('logTbody');
    const drawerBody = document.getElementById('drawerBody');
    const drawerBadge = document.getElementById('drawerBadge');
    const chatForm = document.getElementById('chatForm');
    const trace = document.getElementById('trace');
    const elapsedTimeEl = document.getElementById('elapsedTime');
    const eventCountEl = document.getElementById('eventCount');
    const statusEl = document.getElementById('status');
    const clearBtn = document.getElementById('clearBtn');
    const sendBtn = document.getElementById('sendBtn');
    const stopBtn = document.getElementById('stopBtn');
    const sessionIdInput = document.getElementById('sessionId');
    const userIdInput = document.getElementById('userId');
    const promptInput = document.getElementById('prompt');
    const chatAgentName = document.getElementById('chatAgentName');
    const chatModelSummary = document.getElementById('chatModelSummary');
    const chatMemorySummary = document.getElementById('chatMemorySummary');
    const chatPresetButtons = [...document.querySelectorAll('[data-chat-prompt]')];

    let chartDau = null;
    let chartRequestsSessions = null;
    let chartTurns = null;
    let chartQueryTop = null;
    let chartUserTop = null;
    let chatAbortController = null;
    let chatEventCount = 0;
    let chatStartedAt = 0;
    let chatTimerId = null;
    let activeChatRun = null;
    let followLatestChat = true;
    let pendingChatScrollFrame = null;

    const today = new Date();
    const formatDate = (date) => date.toISOString().slice(0, 10);
    const formatNumber = (num) => num.toLocaleString('zh-CN');
    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
    const storageKey = 'assistant-admin-console-config';
    let echartsReady = false;

    const baseConfig = {
      agentName: '智能问答助手',
      agentMaxIters: 6,
      agentEnableSessionMemory: true,
      llmProvider: 'openai',
      llmModel: 'gpt-4.1-mini',
      llmApiKey: 'sk-mock-xxxxxxxxxxxxxxxx',
      llmBaseUrl: 'https://api.openai.com/v1',
      llmStream: true,
      llmEnableThinking: true,
      llmContextSize: 131072
    };

    function shiftDate(date, days) {
      const next = new Date(date);
      next.setDate(next.getDate() + days);
      return next;
    }

    function seededRandom(seed) {
      const x = Math.sin(seed) * 10000;
      return x - Math.floor(x);
    }

    function generateReqId() {
      return `req_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    }

    function createSessionId() {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
      }
      return `session_${Date.now()}`;
    }

    function getErrorMessage(error) {
      return error && error.message ? error.message : String(error);
    }

    function createMockMetrics(date, index) {
      const base = 420 + Math.round(seededRandom(index + 10) * 260);
      const sessions = 110 + Math.round(seededRandom(index + 20) * 90);
      const users = 60 + Math.round(seededRandom(index + 30) * 55);
      const turns = 3 + Math.round(seededRandom(index + 40) * 3) + (index % 4 === 0 ? 1 : 0);
      return {
        date: formatDate(date),
        dau: users,
        requests: base,
        sessions,
        avgTurns: Number((turns + seededRandom(index + 50) * 0.8).toFixed(1))
      };
    }

    function generateDataset(days = 30) {
      const list = [];
      for (let i = days - 1; i >= 0; i -= 1) {
        list.push(createMockMetrics(shiftDate(today, -i), i));
      }
      return list;
    }

    const trendData = generateDataset(120);

    const queryPool = [
      '怎么给知识库做分片？',
      '帮我总结一下这个合同的风险点',
      '如何提升智能体回答准确率',
      '请给我一版客服话术',
      '模型选择 openai 还是 deepseek 更合适',
      'RAG 检索失败时怎么办',
      '对话记忆如何设计',
      '如何控制回答长度',
      '知识库更新后怎么热刷新',
      '如何减少幻觉'
    ];

    const answerPool = [
      '建议先抽取关键信息，再做结构化输出。',
      '可以从召回、重排、提示词和兜底策略四个方向优化。',
      '请结合业务场景、成本和响应延迟进行选型。',
      '推荐保留会话记忆，但需要加上清理策略。',
      '建议使用简洁模板，突出步骤和注意事项。'
    ];

    function createMockLog(index) {
      const date = shiftDate(today, -index);
      const userId = `user_${String((index % 12) + 1).padStart(4, '0')}`;
      const sessionId = `session_${202607 - Math.floor(index / 2)}_${String((index % 7) + 1).padStart(2, '0')}`;
      const requestId = `req_${date.getTime().toString(36)}_${index.toString(36)}`;
      const query = queryPool[index % queryPool.length];
      const answer = answerPool[index % answerPool.length];
      return {
        time: date.toLocaleString('zh-CN'),
        request_id: requestId,
        user_id: userId,
        session_id: sessionId,
        user_query: query,
        query_body: {
          message: query,
          agent: '智能问答助手',
          params: {
            top_k: 5,
            temperature: 0.2,
            enable_memory: index % 2 === 0
          }
        },
        answer_list: [
          { role: 'assistant', text: answer, score: Number((0.86 + seededRandom(index + 7) * 0.1).toFixed(2)) },
          { role: 'tool', name: 'knowledge_search', hit_count: 3 + (index % 4) }
        ],
        answer_text: `${answer} 这是一个较长的对话回复示例，用于演示列表展示和详情查看。`,
        created_at: date.getTime()
      };
    }

    const logsData = Array.from({ length: 42 }, (_, i) => createMockLog(i));
    let filteredLogs = [...logsData];
    let activeLog = filteredLogs[0] || null;

    function switchTab(tabName) {
      tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.tab === tabName));
      panels.forEach((panel) => panel.classList.toggle('active', panel.id === tabName));
      if (tabName === 'dashboard') setTimeout(() => resizeCharts(), 50);
      if (tabName === 'chat') {
        syncChatSidebar();
        scrollChatToLatest(true);
      }
    }

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    function getDashboardRange() {
      const days = Number(dashboardPreset.value || 30);
      const end = dashboardEnd.value ? new Date(dashboardEnd.value + 'T23:59:59') : today;
      const start = dashboardStart.value ? new Date(dashboardStart.value + 'T00:00:00') : shiftDate(end, -(days - 1));
      if (start > end) return { start: end, end: start };
      return { start, end };
    }

    function filterTrendData() {
      const { start, end } = getDashboardRange();
      return trendData.filter((item) => {
        const dt = new Date(item.date + 'T00:00:00');
        return dt >= start && dt <= end;
      });
    }

    function calcDashboard() {
      const data = filterTrendData();
      const requests = data.reduce((sum, item) => sum + item.requests, 0);
      const sessions = data.reduce((sum, item) => sum + item.sessions, 0);
      const users = data.reduce((sum, item) => sum + item.dau, 0);

      metricRequests.textContent = formatNumber(requests);
      metricSessions.textContent = formatNumber(sessions);
      metricUsers.textContent = formatNumber(users);

      const dates = data.map((item) => item.date.slice(5));
      if (!echartsReady) return;

      chartDau.setOption(buildLineOption(dates, [
        { name: 'DAU', data: data.map((item) => item.dau), color: '#2563eb' }
      ]));
      chartRequestsSessions.setOption(buildLineOption(dates, [
        { name: '总请求数', data: data.map((item) => item.requests), color: '#2563eb' },
        { name: '会话数', data: data.map((item) => item.sessions), color: '#0ea5e9' }
      ]));
      chartTurns.setOption(buildLineOption(dates, [
        { name: '平均轮次', data: data.map((item) => item.avgTurns), color: '#8b5cf6' }
      ], true));

      const queryTop = queryPool.map((name, index) => ({
        name,
        value: 42 - index * 2 + Math.round(seededRandom(index + data.length) * 10)
      })).sort((a, b) => b.value - a.value).slice(0, 10).reverse();

      const userTop = Array.from({ length: 10 }, (_, index) => ({
        name: `user_${String(index + 1).padStart(4, '0')}`,
        value: 28 + Math.round(seededRandom(index + data.length + 4) * 40)
      })).sort((a, b) => b.value - a.value).slice(0, 10).reverse();

      chartQueryTop.setOption(buildBarOption(queryTop, '#2563eb'));
      chartUserTop.setOption(buildBarOption(userTop, '#0ea5e9'));
    }

    function buildLineOption(categories, series, isSmooth = false) {
      return {
        animationDuration: 500,
        tooltip: { trigger: 'axis' },
        legend: { top: 6, right: 12, icon: 'roundRect', itemWidth: 12, itemHeight: 8 },
        grid: { left: 18, right: 18, top: 58, bottom: 24, containLabel: true },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: categories,
          axisLine: { lineStyle: { color: '#cbd5e1' } },
          axisLabel: { color: '#64748b' }
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: '#64748b' },
          splitLine: { lineStyle: { color: '#e5edf7' } }
        },
        series: series.map((item) => ({
          name: item.name,
          type: 'line',
          smooth: isSmooth,
          symbol: 'circle',
          symbolSize: 8,
          lineStyle: { width: 3, color: item.color },
          itemStyle: { color: item.color },
          emphasis: { focus: 'series' },
          data: item.data
        }))
      };
    }

    function buildBarOption(data, color) {
      return {
        animationDuration: 500,
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 18, right: 18, top: 18, bottom: 16, containLabel: true },
        xAxis: {
          type: 'value',
          axisLabel: { color: '#64748b' },
          splitLine: { lineStyle: { color: '#e5edf7' } }
        },
        yAxis: {
          type: 'category',
          data: data.map((item) => item.name),
          axisLabel: { color: '#334155' },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: '#cbd5e1' } }
        },
        series: [{
          type: 'bar',
          data: data.map((item) => item.value),
          barWidth: 14,
          itemStyle: {
            borderRadius: [0, 8, 8, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: '#bfdbfe' },
              { offset: 1, color }
            ])
          }
        }]
      };
    }

    function renderChartFallback(message) {
      ['chartDau', 'chartRequestsSessions', 'chartTurns', 'chartQueryTop', 'chartUserTop'].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = `<div class="chart-fallback">${message}</div>`;
      });
    }

    function initCharts() {
      if (!window.echarts) {
        renderChartFallback('ECharts 加载失败，当前保留图表占位。前端接入正式工程时可改为本地静态资源或 npm 依赖。');
        echartsReady = false;
        return;
      }

      chartDau = window.echarts.init(document.getElementById('chartDau'));
      chartRequestsSessions = window.echarts.init(document.getElementById('chartRequestsSessions'));
      chartTurns = window.echarts.init(document.getElementById('chartTurns'));
      chartQueryTop = window.echarts.init(document.getElementById('chartQueryTop'));
      chartUserTop = window.echarts.init(document.getElementById('chartUserTop'));
      echartsReady = true;
    }

    function loadECharts() {
      if (window.echarts) return Promise.resolve(window.echarts);

      return new Promise((resolve, reject) => {
        const existing = document.querySelector('script[data-echarts-loader="true"]');
        if (existing) {
          existing.addEventListener('load', () => resolve(window.echarts), { once: true });
          existing.addEventListener('error', () => reject(new Error('ECharts load failed')), { once: true });
          return;
        }

        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js';
        script.async = true;
        script.defer = true;
        script.dataset.echartsLoader = 'true';
        script.onload = () => resolve(window.echarts);
        script.onerror = () => reject(new Error('ECharts load failed'));
        document.head.appendChild(script);
      });
    }

    function resizeCharts() {
      [chartDau, chartRequestsSessions, chartTurns, chartQueryTop, chartUserTop]
        .filter(Boolean)
        .forEach((chart) => chart.resize());
    }

    function updateAgentSummary() {
      summaryName.textContent = agentName.value.trim() || '-';
      summaryModel.textContent = `${llmProvider.value} · ${llmModel.value.trim() || '-'}`;
      summaryMemory.textContent = agentEnableSessionMemory.checked ? '开启' : '关闭';
      summaryStream.textContent = llmStream.checked ? '开启' : '关闭';
      summaryThink.textContent = llmEnableThinking.checked ? '开启' : '关闭';
      summaryContext.textContent = formatNumber(Number(llmContextSize.value || 0));
      syncChatSidebar();
    }

    function syncConfigFields(config) {
      agentName.value = config.agentName;
      agentMaxIters.value = config.agentMaxIters;
      agentEnableSessionMemory.checked = config.agentEnableSessionMemory;
      llmProvider.value = config.llmProvider;
      llmModel.value = config.llmModel;
      llmApiKey.value = config.llmApiKey;
      llmBaseUrl.value = config.llmBaseUrl;
      llmStream.checked = config.llmStream;
      llmEnableThinking.checked = config.llmEnableThinking;
      llmContextSize.value = config.llmContextSize;
      updateAgentSummary();
    }

    function readConfigFromForm() {
      return {
        agentName: agentName.value.trim(),
        agentMaxIters: clamp(Number(agentMaxIters.value || 1), 1, 64),
        agentEnableSessionMemory: agentEnableSessionMemory.checked,
        llmProvider: llmProvider.value,
        llmModel: llmModel.value.trim(),
        llmApiKey: llmApiKey.value.trim(),
        llmBaseUrl: llmBaseUrl.value.trim(),
        llmStream: llmStream.checked,
        llmEnableThinking: llmEnableThinking.checked,
        llmContextSize: clamp(Number(llmContextSize.value || 1024), 1024, 1048576)
      };
    }

    function renderLogs(list) {
      if (!list.length) {
        logTbody.innerHTML = `
          <tr>
            <td colspan="7" style="padding: 24px; color: #64748b; text-align: center;">没有匹配到日志</td>
          </tr>`;
        drawerBody.innerHTML = `
          <div class="drawer-empty">
            <div>
              <strong>无结果</strong>
              <div style="height: 6px;"></div>
              <div>请调整查询条件后再试。</div>
            </div>
          </div>`;
        drawerBadge.textContent = '无数据';
        return;
      }

      logTbody.innerHTML = list.map((item, index) => `
        <tr>
          <td>${item.time}</td>
          <td><span class="ellipsis" title="${item.request_id}">${item.request_id}</span></td>
          <td>${item.user_id}</td>
          <td>${item.session_id}</td>
          <td class="ellipsis" title="${escapeHtml(item.user_query)}">${escapeHtml(item.user_query)}</td>
          <td class="ellipsis" title="${escapeHtml(item.answer_text)}">${escapeHtml(item.answer_text)}</td>
          <td><button class="action-link" type="button" data-index="${index}">详情</button></td>
        </tr>
      `).join('');

      [...logTbody.querySelectorAll('.action-link')].forEach((button) => {
        button.addEventListener('click', () => {
          activeLog = list[Number(button.dataset.index)];
          renderDrawer(activeLog);
        });
      });

      if (!activeLog || !list.some((item) => item.request_id === activeLog.request_id)) {
        activeLog = list[0];
      }
      renderDrawer(activeLog);
    }

    function renderDrawer(item) {
      if (!item) return;
      drawerBadge.textContent = item.request_id;
      drawerBody.innerHTML = `
        <div class="detail-grid">
          <div class="detail-card">
            <h4>基础信息</h4>
            <div class="kv"><div class="key">时间</div><div class="val">${item.time}</div></div>
            <div class="kv"><div class="key">request_id</div><div class="val">${item.request_id}</div></div>
            <div class="kv"><div class="key">user_id</div><div class="val">${item.user_id}</div></div>
            <div class="kv"><div class="key">session_id</div><div class="val">${item.session_id}</div></div>
          </div>
          <div class="detail-card">
            <h4>user_query</h4>
            <div class="footer-note">${escapeHtml(item.user_query)}</div>
          </div>
          <div class="detail-card">
            <h4>query_body (JSON)</h4>
            <pre>${escapeHtml(JSON.stringify(item.query_body, null, 2))}</pre>
          </div>
          <div class="detail-card">
            <h4>answer_list (JSON Array)</h4>
            <pre>${escapeHtml(JSON.stringify(item.answer_list, null, 2))}</pre>
          </div>
          <div class="detail-card">
            <h4>answer_text</h4>
            <div class="footer-note">${escapeHtml(item.answer_text)}</div>
          </div>
        </div>
      `;
    }

    function escapeHtml(text) {
      return String(text)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function applyLogFilters() {
      const keyword = logSearch.value.trim().toLowerCase();
      const userId = filterUserId.value.trim().toLowerCase();
      const sessionId = filterSessionId.value.trim().toLowerCase();

      filteredLogs = logsData.filter((item) => {
        const haystack = [
          item.user_query,
          item.request_id,
          item.user_id,
          item.session_id,
          JSON.stringify(item.query_body),
          JSON.stringify(item.answer_list),
          item.answer_text
        ].join(' ').toLowerCase();
        const matchesKeyword = !keyword || haystack.includes(keyword);
        const matchesUser = !userId || item.user_id.toLowerCase().includes(userId);
        const matchesSession = !sessionId || item.session_id.toLowerCase().includes(sessionId);
        return matchesKeyword && matchesUser && matchesSession;
      });

      renderLogs(filteredLogs);
    }

    function resetLogFilters() {
      logSearch.value = '';
      filterUserId.value = '';
      filterSessionId.value = '';
      filteredLogs = [...logsData];
      renderLogs(filteredLogs);
    }

    function resetAgentConfig() {
      syncConfigFields(baseConfig);
      localStorage.removeItem(storageKey);
    }

    function saveAgentConfig() {
      const config = readConfigFromForm();
      localStorage.setItem(storageKey, JSON.stringify(config));
      updateAgentSummary();
      agentSave.textContent = '已保存';
      window.setTimeout(() => (agentSave.textContent = '保存配置'), 1200);
    }

    function initDashboardRange() {
      const end = formatDate(today);
      const start = formatDate(shiftDate(today, -29));
      dashboardEnd.value = end;
      dashboardStart.value = start;
    }

    function loadConfig() {
      try {
        const stored = localStorage.getItem(storageKey);
        if (!stored) return syncConfigFields(baseConfig);
        syncConfigFields({ ...baseConfig, ...JSON.parse(stored) });
      } catch (error) {
        syncConfigFields(baseConfig);
      }
    }

    function isChatTraceNearBottom() {
      return trace.scrollHeight - trace.scrollTop - trace.clientHeight < 32;
    }

    function scrollChatToLatest(force = false) {
      if (!force && !followLatestChat) return;
      if (pendingChatScrollFrame) window.cancelAnimationFrame(pendingChatScrollFrame);
      pendingChatScrollFrame = window.requestAnimationFrame(() => {
        trace.scrollTop = trace.scrollHeight;
      });
    }

    function updateChatStatus(text, kind = '') {
      statusEl.className = kind ? `status ${kind}` : 'status';
      statusEl.textContent = text;
    }

    function updateChatCounters() {
      eventCountEl.textContent = `${chatEventCount} events`;
      if (!chatStartedAt) {
        elapsedTimeEl.textContent = '0.0s';
        return;
      }
      const elapsed = (Date.now() - chatStartedAt) / 1000;
      elapsedTimeEl.textContent = `${elapsed.toFixed(1)}s`;
    }

    function startChatTimer() {
      stopChatTimer();
      chatStartedAt = Date.now();
      updateChatCounters();
      chatTimerId = window.setInterval(updateChatCounters, 100);
    }

    function stopChatTimer() {
      if (chatTimerId) {
        window.clearInterval(chatTimerId);
        chatTimerId = null;
      }
      updateChatCounters();
    }

    function renderChatEmptyState() {
      trace.innerHTML = `
        <div class="empty-state">
          <div>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 9h8"/><path d="M8 13h5"/></svg>
            <strong>尝试在下方输入内容进行提问</strong>
            <div style="height: 6px;"></div>
            <span>这里会演示思考、工具调用、工具返回与回复的 mock 流程。</span>
          </div>
        </div>
      `;
    }

    function resetChatTrace() {
      if (chatAbortController) {
        chatAbortController.abort();
        chatAbortController = null;
      }
      activeChatRun = null;
      chatEventCount = 0;
      chatStartedAt = 0;
      followLatestChat = true;
      stopChatTimer();
      renderChatEmptyState();
      updateChatStatus('空闲');
      updateChatCounters();
    }

    function appendChatUserMessage(text) {
      const wrap = document.createElement('div');
      wrap.className = 'message user';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = text;
      wrap.appendChild(bubble);
      trace.appendChild(wrap);
      scrollChatToLatest(true);
      return wrap;
    }

    function splitText(text, size = 12) {
      const chunks = [];
      for (let i = 0; i < text.length; i += size) chunks.push(text.slice(i, i + size));
      return chunks;
    }

    function buildMockReply(prompt) {
      const content = prompt.toLowerCase();
      if (content.includes('合同')) {
        return '可以先提取合同主体、金额、期限、违约责任和争议解决条款，再按风险等级输出。建议重点关注付款节点、赔偿上限和模糊表述。';
      }
      if (content.includes('rag') || content.includes('检索')) {
        return 'RAG 失败时通常从召回、切分、重排、提示词和兜底策略五个层面排查。可以先确认检索结果是否命中，再检查上下文是否被截断。';
      }
      if (content.includes('话术') || content.includes('客服')) {
        return '建议先建立「问候 - 识别诉求 - 解决方案 - 结束确认」四段式话术，并给出一版简洁、礼貌、可追踪的标准回复。';
      }
      if (content.includes('宝马') || content.includes('买车')) {
        return '可以从预算、动力、油耗、保值率和试驾体验五个维度来筛选。若你更看重城市通勤，我会优先建议你看 3 系 / X1 一类更均衡的车型。';
      }
      return '我已经整理了问题的关键信息。建议先给出结论，再补充步骤和注意事项，最后加一个可执行的下一步建议。';
    }

    function createChatAssistantRun(payload) {
      const wrap = document.createElement('div');
      wrap.className = 'message assistant';
      wrap.innerHTML = `
        <div class="assistant-card">
          <div class="message-meta">
            <span class="chip">session: ${escapeHtml(payload.sessionId)}</span>
            <span class="chip">user: ${escapeHtml(payload.userId)}</span>
            <span class="chip">req: ${escapeHtml(payload.reqId)}</span>
          </div>
          <section class="phase think">
            <div class="phase-head"><span>思考</span><span class="chip">thinking</span></div>
            <div class="phase-body" data-body="think" data-empty="true">等待思考内容…</div>
          </section>
          <section class="phase tool">
            <div class="phase-head"><span>工具调用</span><span class="chip">tool</span></div>
            <div class="phase-body" data-body="tool" data-empty="true">等待工具调用…</div>
          </section>
          <section class="phase tool-result">
            <div class="phase-head"><span>工具返回</span><span class="chip">result</span></div>
            <div class="phase-body" data-body="tool-result" data-empty="true">等待工具返回…</div>
          </section>
          <section class="phase response">
            <div class="phase-head"><span>回复</span><span class="chip">assistant</span></div>
            <div class="phase-body" data-body="response" data-empty="true">等待回复内容…</div>
          </section>
        </div>
      `;
      trace.appendChild(wrap);
      scrollChatToLatest(true);
      return {
        thinkBody: wrap.querySelector('[data-body="think"]'),
        toolBody: wrap.querySelector('[data-body="tool"]'),
        toolResultBody: wrap.querySelector('[data-body="tool-result"]'),
        responseBody: wrap.querySelector('[data-body="response"]')
      };
    }

    function appendChatText(target, text) {
      if (!text) return;
      if (target.dataset.empty === 'true') {
        target.textContent = '';
        target.dataset.empty = 'false';
      }
      target.textContent += text;
      scrollChatToLatest();
    }

    async function pause(ms, signal) {
      await new Promise((resolve, reject) => {
        const timer = window.setTimeout(resolve, ms);
        const onAbort = () => {
          window.clearTimeout(timer);
          reject(new DOMException('Aborted', 'AbortError'));
        };
        if (signal.aborted) {
          onAbort();
          return;
        }
        signal.addEventListener('abort', onAbort, { once: true });
      });
    }

    async function playMockChat(payload, run, signal) {
      const thinkLines = [
        `正在分析问题：${payload.prompt}`,
        '已识别为多轮问答测试场景，准备模拟知识检索与生成。'
      ];

      updateChatStatus('流式中', 'streaming');
      for (const line of thinkLines) {
        await pause(180, signal);
        chatEventCount += 1;
        appendChatText(run.thinkBody, `${line}\n`);
        updateChatCounters();
      }

      await pause(220, signal);
      chatEventCount += 1;
      appendChatText(run.toolBody, `knowledge_search(query="${payload.prompt.slice(0, 24)}")`);
      updateChatCounters();

      await pause(220, signal);
      chatEventCount += 1;
      appendChatText(run.toolResultBody, '检索结果：命中 3 条相关知识，最高相关度 0.91。');
      updateChatCounters();

      const replyChunks = splitText(buildMockReply(payload.prompt), 10);
      for (const chunk of replyChunks) {
        await pause(70, signal);
        chatEventCount += 1;
        appendChatText(run.responseBody, chunk);
        updateChatCounters();
      }

      updateChatStatus('完成', 'done');
    }

    function syncChatSidebar() {
      chatAgentName.textContent = agentName.value.trim() || '智能问答助手';
      chatModelSummary.textContent = `${llmProvider.value} · ${llmModel.value.trim() || '-'}`;
      chatMemorySummary.textContent = agentEnableSessionMemory.checked ? '开启' : '关闭';
    }

    async function handleChatSubmit(event) {
      event.preventDefault();
      const prompt = promptInput.value.trim();
      if (!prompt) {
        updateChatStatus('请输入问题', 'error');
        return;
      }

      if (chatAbortController) chatAbortController.abort();
      trace.innerHTML = '';
      appendChatUserMessage(prompt);
      promptInput.value = '';
      promptInput.focus();

      chatEventCount = 0;
      updateChatCounters();
      startChatTimer();
      chatAbortController = new AbortController();

      const payload = {
        prompt,
        userId: userIdInput.value.trim() || 'test-user',
        sessionId: sessionIdInput.value.trim() || (sessionIdInput.value = createSessionId()),
        reqId: generateReqId()
      };

      activeChatRun = createChatAssistantRun(payload);
      updateChatStatus('流式中', 'streaming');
      sendBtn.disabled = true;
      stopBtn.hidden = false;
      stopBtn.disabled = false;

      try {
        await playMockChat(payload, activeChatRun, chatAbortController.signal);
      } catch (error) {
        if (error && error.name === 'AbortError') {
          updateChatStatus('已停止', 'error');
        } else {
          updateChatStatus('请求失败', 'error');
          appendChatText(activeChatRun.responseBody, `\n${getErrorMessage(error)}`);
          chatEventCount += 1;
          updateChatCounters();
        }
      } finally {
        stopChatTimer();
        sendBtn.disabled = false;
        stopBtn.hidden = true;
        stopBtn.disabled = true;
        chatAbortController = null;
        activeChatRun = null;
      }
    }

    dashboardPreset.addEventListener('change', () => {
      const days = Number(dashboardPreset.value || 30);
      dashboardStart.value = formatDate(shiftDate(today, -(days - 1)));
      dashboardEnd.value = formatDate(today);
      calcDashboard();
    });

    [dashboardStart, dashboardEnd].forEach((el) => el.addEventListener('change', () => {
      dashboardPreset.value = '30';
      calcDashboard();
    }));

    dashboardRefresh.addEventListener('click', calcDashboard);
    agentReset.addEventListener('click', resetAgentConfig);
    agentSave.addEventListener('click', saveAgentConfig);
    chatForm.addEventListener('submit', handleChatSubmit);
    clearBtn.addEventListener('click', resetChatTrace);
    stopBtn.addEventListener('click', () => {
      if (chatAbortController) chatAbortController.abort();
    });
    trace.addEventListener('scroll', () => {
      followLatestChat = isChatTraceNearBottom();
    });
    promptInput.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing || sendBtn.disabled) return;
      event.preventDefault();
      chatForm.requestSubmit();
    });
    chatPresetButtons.forEach((button) => {
      button.addEventListener('click', () => {
        promptInput.value = button.dataset.chatPrompt || '';
        promptInput.focus();
      });
    });

    [agentName, agentMaxIters, agentEnableSessionMemory, llmProvider, llmModel, llmApiKey, llmBaseUrl, llmStream, llmEnableThinking, llmContextSize]
      .forEach((el) => el.addEventListener('input', updateAgentSummary));
    [agentEnableSessionMemory, llmStream, llmEnableThinking, llmProvider].forEach((el) => el.addEventListener('change', updateAgentSummary));

    logSearchBtn.addEventListener('click', applyLogFilters);
    logClearBtn.addEventListener('click', resetLogFilters);
    [logSearch, filterUserId, filterSessionId].forEach((el) => el.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') applyLogFilters();
    }));

    window.addEventListener('resize', resizeCharts);

    async function bootstrap() {
      initDashboardRange();
      loadConfig();
      applyLogFilters();
      sessionIdInput.value = createSessionId();
      resetChatTrace();
      syncChatSidebar();
      calcDashboard();

      try {
        await loadECharts();
      } catch (error) {
        renderChartFallback('ECharts CDN 暂时不可用，但页面结构和交互已经完整保留。');
      }

      initCharts();
      calcDashboard();
      resizeCharts();
    }

    bootstrap();