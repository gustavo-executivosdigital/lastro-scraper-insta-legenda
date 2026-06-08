# Changelog

All notable changes to this project are documented here.

## [0.1.0]

### Actor
- **Caption keyword search** — find Instagram posts whose caption contains a keyword
  or phrase (e.g. `stanley`, `very happy`).
- **Hybrid discovery** — Google caption index (`site:instagram.com "keyword"` with a
  surgical dork) plus hashtag seeds, scraped in a single `apify/instagram-scraper`
  run and filtered by the real caption text, with graceful degradation.
- **Filters** — sort by date (newest/oldest), minimum likes, minimum comments,
  date range (`postedAfter`/`postedBefore`, absolute or relative), and a smart
  **location** filter (matches the post's location tag or a mention in the caption,
  accent- and case-insensitive).
- **Optional AI political analysis (Groq)** — classifies whether a caption is
  polemic, scrapes the most-liked comments, and summarizes sentiment **relative to
  the searched subject** (who the criticism targets, who it favors, the context),
  with automatic model fallback on a 404.

### Panel
- Local **Node + Express** web panel with a form for every input field and the AI
  toggle; the Apify token stays server-side in `.env`.
- **Demo mode** to preview the UI (including AI output) without a token.
- **Test AI** button and `/api/test-groq` endpoint to verify the Groq connection.
