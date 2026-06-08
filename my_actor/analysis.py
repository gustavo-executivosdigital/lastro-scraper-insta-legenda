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
    subject: str,
) -> dict:
    """Summarize comment sentiment RELATIVE TO the search subject (the keyword).

    The key idea: opinions are measured toward ``subject`` (e.g. "bolsonaro"), not
    toward whoever else the comment mentions. A comment that attacks a third party
    ("the cop is awful") can be POSITIVE toward the subject if it sides with them.
    The model must reason about who the criticism targets and who it favors.
    """
    numbered = '\n'.join(f'{i + 1}. {text}' for i, text in enumerate(comments))
    system_prompt = (
        'Voce e um analista de opiniao publica especializado em contexto politico. '
        'Sua tarefa e medir o sentimento dos comentarios EM RELACAO AO SUJEITO pesquisado, '
        'nao em relacao a outras pessoas citadas. '
        'Exemplo critico: se o sujeito e "bolsonaro" e o post fala "policial prende bolsonaro", '
        'um comentario como "o policial e horrivel" e NEGATIVO em relacao ao policial, mas '
        'POSITIVO/favoravel em relacao ao sujeito (bolsonaro), porque defende o sujeito. '
        'Sempre raciocine: este comentario apoia ou ataca o SUJEITO? '
        'As porcentagens (positiva/negativa/neutra) se referem A POSTURA EM RELACAO AO SUJEITO e '
        'devem somar aproximadamente 100. Responda SOMENTE em JSON valido, em portugues.'
    )
    user_prompt = (
        f'SUJEITO pesquisado: "{subject}"\n\n'
        'Legenda do post:\n'
        f'"""{caption or ""}"""\n\n'
        f'Comentarios (mais curtidos primeiro):\n{numbered}\n\n'
        'Retorne JSON no formato: {'
        '"positivePct": inteiro,  // % de comentarios favoraveis AO SUJEITO\n'
        '"negativePct": inteiro,  // % de comentarios contrarios AO SUJEITO\n'
        '"neutralPct": inteiro,\n'
        '"subjectStance": "a percepcao geral em relacao ao sujeito, em uma frase",\n'
        '"criticismTarget": "contra quem/o que esta a carga negativa dos comentarios",\n'
        '"beneficiary": "a favor de quem/o que a opiniao pende",\n'
        '"context": "o que esta acontecendo na situacao mapeada (post + comentarios)",\n'
        '"problem": "qual e o problema/tensao central em uma frase",\n'
        '"summary": "resumo curto da percepcao geral"}'
    )
    content = await groq_chat(client, api_key, model, system_prompt, user_prompt)
    parsed = _safe_json(content)
    return {
        'subject': subject,
        'positivePct': _clamp_pct(parsed.get('positivePct')),
        'negativePct': _clamp_pct(parsed.get('negativePct')),
        'neutralPct': _clamp_pct(parsed.get('neutralPct')),
        'subjectStance': str(parsed.get('subjectStance') or '').strip(),
        'criticismTarget': str(parsed.get('criticismTarget') or '').strip(),
        'beneficiary': str(parsed.get('beneficiary') or '').strip(),
        'context': str(parsed.get('context') or '').strip(),
        'problem': str(parsed.get('problem') or '').strip(),
        'summary': str(parsed.get('summary') or '').strip(),
    }
