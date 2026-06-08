const form = document.getElementById('run-form');
const runBtn = document.getElementById('run-btn');
const btnLabel = runBtn.querySelector('.btn-label');
const spinner = runBtn.querySelector('.spinner');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const emptyEl = document.getElementById('empty');
const countBadge = document.getElementById('count-badge');
const aiToggle = document.getElementById('ai-toggle');
const aiFields = document.getElementById('ai-fields');

// Show/hide AI fields with the toggle.
aiToggle.addEventListener('change', () => {
  aiFields.hidden = !aiToggle.checked;
});

function setStatus(msg, kind = '') {
  statusEl.textContent = msg;
  statusEl.className = 'status' + (kind ? ' ' + kind : '');
}

function setLoading(loading) {
  runBtn.disabled = loading;
  spinner.hidden = !loading;
  btnLabel.textContent = loading ? 'Rodando…' : 'Rodar scraper';
}

function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  );
}

function fmtNumber(n) {
  if (n === null || n === undefined || n === -1) return '–';
  return Number(n).toLocaleString('pt-BR');
}

function fmtDate(ts) {
  if (!ts) return '–';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '–';
  return d.toLocaleDateString('pt-BR');
}

function analysisBlock(item) {
  const a = item.analysis;
  if (!a) return '';

  if (a.error) {
    return `<div class="analysis"><span class="reason">Análise falhou: ${esc(a.error)}</span></div>`;
  }

  const polemic = a.isPolemic === true;
  const badge = polemic
    ? '<span class="badge polemic">⚠ Polêmico</span>'
    : '<span class="badge calm">✓ Não polêmico</span>';

  let sentiment = '';
  if (polemic && typeof a.negativePct === 'number') {
    const pos = a.positivePct || 0;
    const neu = a.neutralPct || 0;
    const neg = a.negativePct || 0;
    const subj = a.subject ? ` em relação a <strong>${esc(a.subject)}</strong>` : '';
    sentiment = `
      <div class="rel-note">Sentimento${subj}</div>
      <div class="sentiment-bar">
        <span class="s-pos" style="width:${pos}%"></span>
        <span class="s-neu" style="width:${neu}%"></span>
        <span class="s-neg" style="width:${neg}%"></span>
      </div>
      <div class="sentiment-legend">
        <span>👍 ${pos}%</span><span>😐 ${neu}%</span><span>👎 ${neg}%</span>
      </div>
      ${a.subjectStance ? `<div class="stance">🎯 ${esc(a.subjectStance)}</div>` : ''}
      ${a.criticismTarget ? `<div class="rel-line"><b>Crítica contra:</b> ${esc(a.criticismTarget)}</div>` : ''}
      ${a.beneficiary ? `<div class="rel-line"><b>Favorece:</b> ${esc(a.beneficiary)}</div>` : ''}
      ${a.context ? `<div class="rel-line"><b>Contexto:</b> ${esc(a.context)}</div>` : ''}
      ${a.problem ? `<div class="problem">⚡ ${esc(a.problem)}</div>` : ''}
      ${a.summary ? `<div class="reason">${esc(a.summary)}</div>` : ''}
      ${typeof a.commentsAnalyzed === 'number' ? `<div class="reason">${a.commentsAnalyzed} comentários analisados</div>` : ''}
    `;
  } else if (a.reason) {
    sentiment = `<div class="reason">${esc(a.reason)}</div>`;
  }

  return `<div class="analysis">${badge}${sentiment}</div>`;
}

function cardHtml(item) {
  const img = item.displayUrl
    ? `<img class="card-img" src="${esc(item.displayUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'" />`
    : '';

  const meta = [
    `❤ ${fmtNumber(item.likesCount)}`,
    `💬 ${fmtNumber(item.commentsCount)}`,
    `🗓 ${fmtDate(item.timestamp)}`,
  ];
  if (item.locationName) meta.push(`📍 ${esc(item.locationName)}`);

  return `
    <article class="card">
      ${img}
      <div class="card-body">
        <div class="card-top">
          <span class="author">@${esc(item.ownerUsername || '—')}</span>
        </div>
        <div class="card-caption">${esc(item.caption || '(sem legenda)')}</div>
        <div class="meta">${meta.map((m) => `<span class="chip">${m}</span>`).join('')}</div>
        ${analysisBlock(item)}
        ${item.url ? `<a class="card-link" href="${esc(item.url)}" target="_blank" rel="noopener">Ver no Instagram ↗</a>` : ''}
      </div>
    </article>
  `;
}

function render(items) {
  if (!items.length) {
    resultsEl.innerHTML = '';
    emptyEl.hidden = false;
    emptyEl.innerHTML = '<p>Nenhum post encontrado com esses filtros.</p>';
    return;
  }
  emptyEl.hidden = true;
  resultsEl.innerHTML = items.map(cardHtml).join('');
}

const demoBtn = document.getElementById('demo-btn');
demoBtn.addEventListener('click', async () => {
  setStatus('Carregando demonstração…', '');
  countBadge.hidden = true;
  try {
    const resp = await fetch('/api/demo');
    const json = await resp.json();
    render(json.items || []);
    countBadge.textContent = `${json.count} posts (demo)`;
    countBadge.hidden = false;
    setStatus('Demonstração com dados de exemplo (inclui análise de IA).', 'ok');
  } catch (err) {
    setStatus(err.message, 'error');
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form).entries());
  data.enablePoliticalAnalysis = aiToggle.checked;

  setLoading(true);
  setStatus('Executando o Actor na Apify… isso pode levar alguns minutos.', '');
  countBadge.hidden = true;

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const json = await resp.json();
    if (!resp.ok) throw new Error(json.error || 'Erro desconhecido.');

    render(json.items || []);
    countBadge.textContent = `${json.count} posts`;
    countBadge.hidden = false;
    setStatus(`Concluído · run ${json.runId} · status ${json.status}`, 'ok');
  } catch (err) {
    setStatus(err.message, 'error');
  } finally {
    setLoading(false);
  }
});
