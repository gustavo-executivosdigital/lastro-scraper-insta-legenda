# Lastro · Painel web local

Painel simples para rodar o Actor **Instagram Caption Keyword Search** na Apify a
partir do seu PC, com todos os campos do scraper e o toggle de análise política (IA).

O token da Apify fica **no servidor** (`.env`), nunca no navegador.

## Pré-requisitos

- [Node.js](https://nodejs.org) 18 ou superior.
- Um token da Apify: https://console.apify.com/account/integrations

## Como rodar

```bash
cd panel
npm install

# Crie o .env a partir do exemplo e preencha o APIFY_TOKEN
copy .env.example .env      # Windows (PowerShell/CMD)
# cp .env.example .env      # macOS/Linux

npm start
```

Abra **http://localhost:3000**.

## Configuração (.env)

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `APIFY_TOKEN` | ✅ | Seu token da Apify. |
| `APIFY_ACTOR_ID` | ❌ | Id do Actor (padrão `vZaPYHqFzqndnJ2Cw`). |
| `GROQ_API_KEY` | ❌ | Chave Groq padrão para a análise de IA (também pode ser digitada no painel). |
| `PORT` | ❌ | Porta do painel (padrão `3000`). |

## Campos do painel

- **Palavra-chave** (obrigatório), **máx. de posts**, **ordenação** (recentes/antigos)
- **Mín. curtidas**, **mín. comentários**
- **Postado depois/antes de** (data `2024-01-01` ou relativa `30 days`)
- **Localização** (bairro/cidade — casa na tag do post ou na legenda)
- **Toggle Análise política (IA)** → revela: Groq API key, modelo e máx. de comentários

## Como funciona

O painel envia os campos para `POST /api/run`. O servidor monta o input, chama o
Actor na Apify (`client.actor(ACTOR_ID).call(input)`), espera terminar e devolve os
itens do dataset, que são renderizados como cards (imagem, legenda, autor,
curtidas, comentários, localização, data e — quando a IA está ligada — o veredito
de polêmica e o sentimento dos comentários).

> A chamada é síncrona: enquanto o Actor roda na nuvem, o painel mostra "Rodando…".
> Runs grandes podem levar alguns minutos.
