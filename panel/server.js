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

app.get('/api/health', (_req, res) => {
  res.json({
    ok: Boolean(APIFY_TOKEN),
    actorId: ACTOR_ID,
    hasGroqEnvKey: Boolean(GROQ_API_KEY),
  });
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
