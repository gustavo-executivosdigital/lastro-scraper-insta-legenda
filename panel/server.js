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
      keyword: 'reforma',
      url: 'https://www.instagram.com/p/CdemoAAAAA1/',
      caption:
        'A nova reforma proposta pela prefeitura está gerando muita discussão no bairro. ' +
        'Uns acham que vai melhorar o trânsito, outros dizem que é só desperdício de dinheiro público. E você?',
      ownerUsername: 'jornal.dobairro',
      ownerFullName: 'Jornal do Bairro',
      likesCount: 4820,
      commentsCount: 367,
      timestamp: '2026-05-28T14:12:00.000Z',
      type: 'Image',
      displayUrl: 'https://images.unsplash.com/photo-1517048676732-d65bc937f952?w=600&q=80',
      locationName: 'Leblon, Rio de Janeiro',
      locationId: '213385402',
      isPolemic: true,
      negativePct: 62,
      positivePct: 23,
      analysis: {
        isPolemic: true,
        reason: 'Trata de obra pública municipal, tema de forte divergência política local.',
        commentsAnalyzed: 30,
        positivePct: 23,
        negativePct: 62,
        neutralPct: 15,
        problem: 'Desconfiança sobre o uso do dinheiro público e o real benefício da obra.',
        summary: 'A maioria dos comentários critica o custo e duvida da utilidade; uma minoria apoia a melhoria do trânsito.',
      },
    },
    {
      keyword: 'reforma',
      url: 'https://www.instagram.com/p/CdemoBBBBB2/',
      caption: 'Reforma da cozinha finalmente pronta! Muito feliz com o resultado 🥰 #reforma #casanova',
      ownerUsername: 'casa.da.ana',
      ownerFullName: 'Ana Designs',
      likesCount: 980,
      commentsCount: 41,
      timestamp: '2026-06-01T09:30:00.000Z',
      type: 'Sidecar',
      displayUrl: 'https://images.unsplash.com/photo-1556909212-d5b604d0c90d?w=600&q=80',
      locationName: null,
      locationId: null,
      isPolemic: false,
      analysis: {
        isPolemic: false,
        reason: 'Conteúdo pessoal sobre reforma doméstica, sem cunho político.',
      },
    },
    {
      keyword: 'reforma',
      url: 'https://www.instagram.com/p/CdemoCCCCC3/',
      caption:
        'Reforma trabalhista volta ao debate no congresso. Categorias se mobilizam contra mudanças nas regras de jornada.',
      ownerUsername: 'politica.agora',
      ownerFullName: 'Política Agora',
      likesCount: 12750,
      commentsCount: 1894,
      timestamp: '2026-06-05T18:45:00.000Z',
      type: 'Video',
      displayUrl: 'https://images.unsplash.com/photo-1591189863430-ab87e120f312?w=600&q=80',
      locationName: 'Brasília, Distrito Federal',
      locationId: '212999109',
      isPolemic: true,
      negativePct: 71,
      positivePct: 18,
      analysis: {
        isPolemic: true,
        reason: 'Tema nacional de legislação trabalhista, alvo de intensa polarização.',
        commentsAnalyzed: 30,
        positivePct: 18,
        negativePct: 71,
        neutralPct: 11,
        problem: 'Medo de perda de direitos e aumento da jornada sem contrapartida.',
        summary: 'Predomina a rejeição, com forte temor sobre direitos; apoio minoritário cita modernização.',
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
