"""Optional AI political-sentiment analysis powered by Groq.

This module is only used when the ``enablePoliticalAnalysis`` toggle is on. It does
two things via Groq's OpenAI-compatible chat API:

1. ``classify_polemic`` - decide whether a post caption is politically
   controversial / polemic.
2. ``analyze_sentiment`` - given the post and its (most-liked) comments, estimate
   the share of positive / negative / neutral opinions and describe the core issue.

Every call is best-effort: network or parsing errors are raised to the caller, which
logs them and continues, so the analysis never crashes the main scrape.
"""

from __future__ import annotations

import json
import re

import httpx

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
DEFAULT_MODEL = 'llama-3.3-70b-versatile'


def _safe_json(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating extra prose around it."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return {}


def _clamp_pct(value: object) -> int:
    """Coerce a percentage to an int in the 0-100 range."""
    try:
        number = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


async def groq_chat(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Call Groq chat completions in JSON mode and return the raw message content."""
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': 0.2,
        'response_format': {'type': 'json_object'},
    }
    response = await client.post(
        GROQ_URL,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return data['choices'][0]['message']['content']


async def classify_polemic(client: httpx.AsyncClient, api_key: str, model: str, caption: str) -> dict:
    """Return ``{'isPolemic': bool, 'reason': str}`` for a caption."""
    system_prompt = (
        'Voce e um analista de conteudo politico e social. Avalia se a legenda de um post '
        'do Instagram trata de tema polemico, politico ou socialmente controverso '
        '(politica, eleicoes, governo, direitos, religiao, polarizacao, denuncia, etc.). '
        'Responda SOMENTE em JSON valido.'
    )
    user_prompt = (
        'Legenda do post:\n'
        f'"""{caption or ""}"""\n\n'
        'Retorne JSON no formato: '
        '{"isPolemic": true|false, "reason": "motivo curto em portugues"}'
    )
    content = await groq_chat(client, api_key, model, system_prompt, user_prompt)
    parsed = _safe_json(content)
    return {
        'isPolemic': bool(parsed.get('isPolemic')),
        'reason': str(parsed.get('reason') or '').strip(),
    }


async def analyze_sentiment(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    caption: str,
    comments: list[str],
) -> dict:
    """Summarize the sentiment of comments about a (likely political) post."""
    numbered = '\n'.join(f'{i + 1}. {text}' for i, text in enumerate(comments))
    system_prompt = (
        'Voce e um analista de opiniao publica. Recebe a legenda de um post do Instagram '
        '(provavelmente politico) e os comentarios mais curtidos. Estime a distribuicao de '
        'opinioes (positiva, negativa, neutra) sobre o tema/post e descreva o problema ou '
        'tensao central. As porcentagens devem somar aproximadamente 100. '
        'Responda SOMENTE em JSON valido, em portugues.'
    )
    user_prompt = (
        'Legenda do post:\n'
        f'"""{caption or ""}"""\n\n'
        f'Comentarios (mais curtidos primeiro):\n{numbered}\n\n'
        'Retorne JSON no formato: {'
        '"positivePct": inteiro, "negativePct": inteiro, "neutralPct": inteiro, '
        '"problem": "qual e o problema/tensao central em uma frase", '
        '"summary": "resumo curto da percepcao geral"}'
    )
    content = await groq_chat(client, api_key, model, system_prompt, user_prompt)
    parsed = _safe_json(content)
    return {
        'positivePct': _clamp_pct(parsed.get('positivePct')),
        'negativePct': _clamp_pct(parsed.get('negativePct')),
        'neutralPct': _clamp_pct(parsed.get('neutralPct')),
        'problem': str(parsed.get('problem') or '').strip(),
        'summary': str(parsed.get('summary') or '').strip(),
    }
