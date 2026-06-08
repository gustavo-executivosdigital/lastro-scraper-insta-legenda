import 'dotenv/config';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { ApifyClient } from 'apify-client';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const PORT = process.env.PORT || 3000;
const APIFY_TOKEN = process.env.APIFY_TOKEN;
const ACTOR_ID = process.env.APIFY_ACTOR_ID || 'vZaPYHqFzqndnJ2Cw';
const GROQ_API_KEY = process.env.GROQ_API_KEY || '';

const app = express();
app.use(express.json({ limit: '1mb' }));
app.use(express.static(path.join(__dirname, 'public')));

/** Build the Actor input from the panel form, dropping empty fields. */
function buildInput(body = {}) {
  const input = {};

  const keyword = (body.keyword || '').trim();
  if (!keyword) throw new Error('O campo "keyword" é obrigatório.');
  input.keyword = keyword;

  const num = (v) => (v === '' || v === null || v === undefined ? undefined : Number(v));

  if (num(body.maxPosts) !== undefined) input.maxPosts = num(body.maxPosts);
  if (body.sortBy) input.sortBy = body.sortBy;
  if (num(body.minLikes) !== undefined) input.minLikes = num(body.minLikes);
  if (num(body.minComments) !== undefined) input.minComments = num(body.minComments);
  if ((body.postedAfter || '').trim()) input.postedAfter = body.postedAfter.trim();
  if ((body.postedBefore || '').trim()) input.postedBefore = body.postedBefore.trim();
  if ((body.location || '').trim()) input.location = body.location.trim();

  if (body.enablePoliticalAnalysis) {
    input.enablePoliticalAnalysis = true;
    // Use the key typed in the panel, otherwise fall back to the server .env.
    const key = (body.groqApiKey || '').trim() || GROQ_API_KEY;
    if (!key) {
      throw new Error(
        'A análise política está ligada, mas nenhuma Groq API key foi informada ' +
          '(preencha o campo no painel ou defina GROQ_API_KEY no .env).',
      );
    }
    input.groqApiKey = key;
    if ((body.groqModel || '').trim()) input.groqModel = body.groqModel.trim();
    if (num(body.maxComments) !== undefined) input.maxComments = num(body.maxComments);
  }

  return input;
}

// Friendly aliases so /painel and /panel also open the UI.
app.get(['/painel', '/panel'], (_req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Live Groq check so the user can verify the AI integration from the panel.
app.get('/api/test-groq', async (req, res) => {
  const key = (req.query.key || '').trim() || GROQ_API_KEY;
  const model = 'llama-3.3-70b-versatile';
  if (!key) {
    return res.json({ ok: false, error: 'GROQ_API_KEY não definida no .env (nem informada no painel).' });
  }
  try {
    const r = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        messages: [{ role: 'user', content: 'Responda apenas: OK' }],
        max_tokens: 5,
        temperature: 0,
      }),
    });
    const text = await r.text();
    if (!r.ok) {
      return res.json({ ok: false, status: r.status, model, error: text.slice(0, 400) });
    }
    const reply = JSON.parse(text).choices?.[0]?.message?.content ?? '';
    res.json({ ok: true, model, reply });
  } catch (err) {
    res.json({ ok: false, error: err.message });
  }
});

app.get('/api/health', (_req, res) => {
  res.json({
    ok: Boolean(APIFY_TOKEN),
    actorId: ACTOR_ID,
    hasGroqEnvKey: Boolean(GROQ_API_KEY),
  });
});

/** Sample dataset so the UI (including the AI block) can be previewed without a token. */
app.get('/api/demo', (_req, res) => {
  const items = [
    {
      keyword: 'bolsonaro',
      url: 'https://www.instagram.com/p/CdemoAAAAA1/',
      caption: 'Policial prende Bolsonaro em operação; veja o vídeo da abordagem.',
      ownerUsername: 'jornal.nacional',
      ownerFullName: 'Jornal Nacional',
      likesCount: 18420,
      commentsCount: 3267,
      timestamp: '2026-05-28T14:12:00.000Z',
      type: 'Video',
      displayUrl: 'https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?w=600&q=80',
      locationName: 'Brasília, Distrito Federal',
      locationId: '212999109',
      isPolemic: true,
      negativePct: 24,
      positivePct: 61,
      analysis: {
        isPolemic: true,
        reason: 'Prisão de figura política de altíssima exposição — tema fortemente polarizado.',
        commentsAnalyzed: 30,
        subject: 'bolsonaro',
        positivePct: 61,
        negativePct: 24,
        neutralPct: 15,
        subjectStance: 'A maioria dos comentários se solidariza com Bolsonaro e critica a ação policial.',
        criticismTarget: 'O policial e a operação que fez a prisão.',
        beneficiary: 'Bolsonaro (visto como injustiçado pela maioria dos comentaristas).',
        context:
          'O post noticia a prisão; nos comentários, falas como "o policial é horrível" atacam a polícia, ' +
          'mas demonstram apoio ao sujeito pesquisado — por isso contam como positivas em relação a Bolsonaro.',
        problem: 'Percepção de perseguição política; a revolta é direcionada à autoridade, não ao sujeito.',
        summary: 'Predomina a defesa de Bolsonaro; a carga negativa recai sobre o policial, não sobre ele.',
      },
    },
    {
      keyword: 'bolsonaro',
      url: 'https://www.instagram.com/p/CdemoBBBBB2/',
      caption: 'Encontrei meu cachorro Bolsonaro! Ele fugiu ontem e voltou pra casa hoje 🐶❤️ #bolsonaro',
      ownerUsername: 'familia.silva',
      ownerFullName: 'Família Silva',
      likesCount: 540,
      commentsCount: 22,
      timestamp: '2026-06-01T09:30:00.000Z',
      type: 'Image',
      displayUrl: 'https://images.unsplash.com/photo-1543466835-00a7907e9de1?w=600&q=80',
      locationName: null,
      locationId: null,
      isPolemic: false,
      analysis: {
        isPolemic: false,
        reason: 'Uso do termo como nome de animal de estimação — sem teor político.',
      },
    },
    {
      keyword: 'bolsonaro',
      url: 'https://www.instagram.com/p/CdemoCCCCC3/',
      caption: 'Bolsonaro discursa em ato e defende novas pautas; oposição reage duramente.',
      ownerUsername: 'politica.agora',
      ownerFullName: 'Política Agora',
      likesCount: 12750,
      commentsCount: 1894,
      timestamp: '2026-06-05T18:45:00.000Z',
      type: 'Image',
      displayUrl: 'https://images.unsplash.com/photo-1591189863430-ab87e120f312?w=600&q=80',
      locationName: 'São Paulo, Brasil',
      locationId: '212988192',
      isPolemic: true,
      negativePct: 58,
      positivePct: 33,
      analysis: {
        isPolemic: true,
        reason: 'Discurso político de figura polarizadora, alvo direto de apoio e rejeição.',
        commentsAnalyzed: 30,
        subject: 'bolsonaro',
        positivePct: 33,
        negativePct: 58,
        neutralPct: 9,
        subjectStance: 'A maioria critica diretamente o sujeito e suas pautas.',
        criticismTarget: 'O próprio Bolsonaro e o conteúdo do discurso.',
        beneficiary: 'A oposição e quem discorda das pautas apresentadas.',
        context: 'Aqui a carga negativa recai sobre o próprio sujeito, ao contrário do primeiro caso.',
        problem: 'Rejeição às pautas defendidas e desconfiança sobre as intenções.',
        summary: 'Maioria contrária ao sujeito; apoio minoritário mais entusiasmado.',
      },
    },
  ];
  res.json({ runId: 'DEMO', status: 'SUCCEEDED', datasetId: 'demo', count: items.length, items });
});

app.post('/api/run', async (req, res) => {
  if (!APIFY_TOKEN) {
    return res.status(500).json({ error: 'APIFY_TOKEN ausente. Crie um arquivo .env (veja .env.example).' });
  }

  let input;
  try {
    input = buildInput(req.body);
  } catch (err) {
    return res.status(400).json({ error: err.message });
  }

  try {
    const client = new ApifyClient({ token: APIFY_TOKEN });
    console.log(`[run] Actor ${ACTOR_ID} input:`, { ...input, groqApiKey: input.groqApiKey ? '***' : undefined });

    const run = await client.actor(ACTOR_ID).call(input);
    const { items } = await client.dataset(run.defaultDatasetId).listItems();

    res.json({
      runId: run.id,
      status: run.status,
      datasetId: run.defaultDatasetId,
      count: items.length,
      items,
    });
  } catch (err) {
    console.error('[run] error:', err);
    res.status(500).json({ error: err.message || 'Falha ao executar o Actor.' });
  }
});

app.listen(PORT, () => {
  console.log(`\n  Painel rodando em  http://localhost:${PORT}`);
  console.log(`  Actor:             ${ACTOR_ID}`);
  console.log(`  APIFY_TOKEN:       ${APIFY_TOKEN ? 'OK' : 'AUSENTE (configure o .env)'}`);
  console.log(`  GROQ_API_KEY:      ${GROQ_API_KEY ? 'OK (.env)' : 'não definida (pode preencher no painel)'}\n`);
});
