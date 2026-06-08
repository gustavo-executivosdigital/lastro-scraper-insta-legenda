# Instagram Caption Keyword Search

**Find Instagram posts by what people actually wrote.** Give this Actor a keyword like `stanley` or a phrase like `very happy`, and it returns Instagram posts whose **caption contains that keyword** — together with the author, like and comment counts, the post URL, the image, and the date. Try it by typing a keyword in the Input tab and clicking **Start**.

This Actor runs on the [Apify platform](https://apify.com), so you get API access, scheduling, integrations (Make, Zapier, Google Sheets), proxy rotation, and run monitoring out of the box.

> **This repository contains two things:** the **Apify Actor** (the scraper itself) and a **local web panel** to run it from your browser. See [Repository structure](#repository-structure) and [Local web panel](#local-web-panel).

## Repository structure

```
.
├── .actor/            # Apify Actor config (input/output/dataset schemas)
├── my_actor/          # Actor source code (Python)
│   ├── main.py        # Orchestration: discovery → filters → sort → output
│   ├── analysis.py    # Optional Groq AI political-sentiment analysis
│   └── ...
├── panel/             # Local web panel (Node + Express) to run the Actor
│   ├── server.js      # API server (keeps your Apify token server-side)
│   └── public/        # Browser UI
├── Dockerfile         # Actor container image
├── requirements.txt   # Python dependencies
└── README.md
```

## Why use Instagram Caption Keyword Search?

- **Social listening** — track every public post mentioning your brand, product, or campaign phrase.
- **Influencer & UGC discovery** — find creators already talking about a topic in their own words.
- **Trend research** — see how a keyword or slogan is being used across captions.
- **Lead and content sourcing** — collect captions, authors, and engagement metrics into a structured dataset you can export.

## How to use Instagram Caption Keyword Search

1. Open the **Input** tab.
2. Type your **Keyword** (for example `stanley` or `very happy`).
3. Optionally set **Max matching posts** (default `50`).
4. Click **Start** and wait for the run to finish.
5. Open the **Output**/Storage tab and download the results as JSON, CSV, Excel, or HTML.

## How it works

Instagram has no public full-text caption search, so this Actor discovers candidate posts two complementary ways and then matches purely on the **caption text**:

1. **Google discovery (real caption search).** It runs [`apify/google-search-scraper`](https://apify.com/apify/google-search-scraper) with a surgical dork — `site:instagram.com "your keyword" -inurl:/accounts/ -inurl:/explore/ -inurl:/tags/` — that targets actual post pages. Google has indexed the caption text of many public posts (it sits in each post's title/meta description), so this finds posts by their caption **even when they used no related hashtag**.
2. **Hashtag discovery (extra coverage).** Your keyword also becomes hashtag seeds — the whole phrase (`very happy` → `#veryhappy`) plus each word (`#very`, `#happy`) — to widen the pool.
3. **One accurate caption scrape.** All discovered URLs are scraped in a single [`apify/instagram-scraper`](https://apify.com/apify/instagram-scraper) run to get full, accurate captions.
4. **Caption filter.** The Actor keeps only posts whose **caption actually contains your keyword** (case-insensitive substring match), de-duplicates them, and saves them to the dataset.

The design **degrades gracefully**: if Google discovery fails or returns nothing, the run continues with hashtag discovery (and vice versa), so a single failure never aborts the whole job.

Because it calls the underlying scraper, that run consumes its own Apify usage in addition to this Actor's compute.

## Input

| Field | Type | Description |
| --- | --- | --- |
| `keyword` | string (required) | The word or phrase to look for in captions, e.g. `stanley` or `very happy`. |
| `maxPosts` | integer | Maximum number of matching posts to return (default `50`, max `1000`). |
| `sortBy` | string | Order of results by publish date: `newest` (default) or `oldest`. |
| `minLikes` | integer | Only keep posts with at least this many likes (default `0`). |
| `minComments` | integer | Only keep posts with at least this many comments (default `0`). |
| `postedAfter` | string | Only posts on/after this date. Absolute (`2024-01-31`) or relative (`7 days`, `1 month`). Empty = no lower bound. |
| `postedBefore` | string | Only posts on/before this date. Absolute (`2024-12-31`) or relative (`7 days`). Empty = no upper bound. |
| `location` | string | Only posts tied to this place (e.g. `Leblon`). Matches the post's location tag **or** a mention in the caption. Accent- and case-insensitive. Empty = no filter. |
| `enablePoliticalAnalysis` | boolean | Toggle the AI political-sentiment scanner (default `false`). |
| `groqApiKey` | string (secret) | Free [Groq](https://console.groq.com) API key — required when the toggle is ON (or set `GROQ_API_KEY`). |
| `groqModel` | string | Groq chat model (default `llama-3.3-70b-versatile`). |
| `maxComments` | integer | Most-liked comments to scrape & analyze per polemic post (default `30`). |

### AI political analysis (optional)

When `enablePoliticalAnalysis` is ON, each matching post goes through an extra pipeline powered by [Groq](https://groq.com):

1. **Classify** — the AI reads the caption and decides if it is polemic/political.
2. **Scrape comments** — for polemic posts, the most-liked comments are scraped (`maxComments`).
3. **Sentiment** — the AI summarizes those comments into `positivePct`, `negativePct`, `neutralPct`, the core `problem`, and a short `summary`.

The result is attached to each post under an `analysis` object, with `isPolemic`, `negativePct` and `positivePct` also surfaced as top-level columns. This step is best-effort: any AI or comment-scrape failure is logged and skipped without aborting the run.

Filters are applied **after** the caption match: posts must contain the keyword **and** match the location **and** fall inside the date range **and** meet the minimum likes/comments, and are then sorted by date before the `maxPosts` cap is applied. Posts with hidden like/comment counts are treated as `0`; posts with an unknown date are excluded when a date range is set.

Example input:

```json
{
    "keyword": "very happy",
    "maxPosts": 50,
    "sortBy": "newest",
    "minLikes": 100,
    "minComments": 5,
    "postedAfter": "30 days",
    "location": "Leblon"
}
```

## Output

Each item in the dataset is one matching post. You can download the dataset in various formats such as JSON, HTML, CSV, or Excel.

```json
{
    "keyword": "very happy",
    "url": "https://www.instagram.com/p/Cxxxxxxxxxx/",
    "caption": "We are very happy to share our new collection! #veryhappy",
    "ownerUsername": "examplebrand",
    "ownerFullName": "Example Brand",
    "likesCount": 1234,
    "commentsCount": 56,
    "timestamp": "2026-05-30T12:00:00.000Z",
    "type": "Image",
    "displayUrl": "https://instagram.com/.../image.jpg",
    "locationName": "Leblon, Rio de Janeiro",
    "locationId": "213385402",
    "hashtags": ["veryhappy"],
    "mentions": [],
    "shortCode": "Cxxxxxxxxxx",
    "id": "1234567890"
}
```

### Data fields

| Field | Description |
| --- | --- |
| `keyword` | The keyword that was searched. |
| `url` | Direct link to the Instagram post. |
| `caption` | Full caption text (contains your keyword). |
| `ownerUsername` / `ownerFullName` | The post author. |
| `likesCount` / `commentsCount` | Engagement metrics. |
| `timestamp` | When the post was published. |
| `type` | Post type (Image, Video, Sidecar). |
| `displayUrl` | URL of the post's main image. |
| `locationName` / `locationId` | The place tagged on the post (if any). |
| `hashtags` / `mentions` | Hashtags and @mentions found in the post. |
| `shortCode` / `id` | Instagram identifiers for the post. |

## Cost estimation

This Actor composes two underlying Actors: `apify/google-search-scraper` (one lightweight search to discover post URLs) and `apify/instagram-scraper` (billed per scraped post — the main cost). A higher `maxPosts` scrapes more candidate posts (the Actor fetches roughly 3× your `maxPosts` to allow for caption filtering). Start with a small `maxPosts` to gauge cost, then scale up. See the [Apify pricing page](https://apify.com/pricing) and each underlying Actor's pricing for current rates.

## Tips & advanced options

- **Short, common keywords** (like `stanley`) return more matches than rare phrases.
- Discovery uses Google's caption index plus hashtags; results are always filtered by the exact phrase in the caption text.
- Use **exact phrases** for precision (`very happy` matches captions containing those words together). Common phrases return more, indexed results.
- Lower `maxPosts` for faster, cheaper runs; raise it for broader coverage.
- Schedule the Actor (Schedules tab) to monitor a keyword over time.

## Local web panel

The [`panel/`](./panel) folder is a small **Node + Express** app that runs this Actor from your browser, with a form for every input field and the AI toggle. Your Apify token stays **server-side** in a `.env` file (never exposed to the browser or committed to Git).

```bash
cd panel
npm install
copy .env.example .env      # Windows  ·  cp on macOS/Linux
# edit .env and set APIFY_TOKEN=apify_api_...
npm start                   # open http://localhost:3000
```

It includes a **demo mode** (preview the AI output without a token) and a **"Test AI" button** that verifies the Groq connection live. Full details in [`panel/README.md`](./panel/README.md).

> **Security:** never put real keys in `.env.example` or any tracked file — only in `.env`, which is git-ignored. The repository ships with no secrets.

## FAQ, disclaimers, and support

- **Is this legal?** The Actor only collects publicly available data. You are responsible for complying with Instagram's Terms of Service and applicable laws (including data-protection rules) when using the output.
- **Why did I get no results?** The hashtag may have too few public posts, or no caption contained the exact keyword. Try a more common keyword.
- **Why are some posts missing?** Only posts surfaced through the hashtag seed are scanned. Private posts are never accessed.
- **Support / feedback:** Use the **Issues** tab on the Actor page. Custom variations (search by user, place, or comments) can be added on request.
