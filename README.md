# Instagram Caption Keyword Search

**Find Instagram posts by what people actually wrote.** Give this Actor a keyword like `stanley` or a phrase like `very happy`, and it returns Instagram posts whose **caption contains that keyword** — together with the author, like and comment counts, the post URL, the image, and the date. Try it by typing a keyword in the Input tab and clicking **Start**.

This Actor runs on the [Apify platform](https://apify.com), so you get API access, scheduling, integrations (Make, Zapier, Google Sheets), proxy rotation, and run monitoring out of the box.

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

Instagram has no public full-text caption search — the only public way to discover posts is through hashtags. So this Actor composes Apify's well-maintained [`apify/instagram-scraper`](https://apify.com/apify/instagram-scraper) to gather candidates, then matches purely on the **caption text**:

1. Your keyword is turned into several hashtag seeds to cast a wide net: the whole phrase (`very happy` → `#veryhappy`) **and each individual word** (`#very`, `#happy`).
2. `apify/instagram-scraper` scrapes candidate posts from all of those hashtags.
3. The Actor keeps only the posts whose **caption actually contains your keyword** (case-insensitive substring match), de-duplicates them, and saves them to the dataset.

This means a post that writes "very happy" in its caption is captured **even if it never used the `#veryhappy` hashtag**, as long as it can be reached through one of the seed hashtags.

Because it calls the underlying scraper, that run consumes its own Apify usage in addition to this Actor's compute.

## Input

| Field | Type | Description |
| --- | --- | --- |
| `keyword` | string (required) | The word or phrase to look for in captions, e.g. `stanley` or `very happy`. |
| `maxPosts` | integer | Maximum number of matching posts to return (default `50`, max `1000`). |

Example input:

```json
{
    "keyword": "very happy",
    "maxPosts": 50
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
| `hashtags` / `mentions` | Hashtags and @mentions found in the post. |
| `shortCode` / `id` | Instagram identifiers for the post. |

## Cost estimation

Most of the cost comes from the underlying `apify/instagram-scraper` run, which is billed per result. A higher `maxPosts` scrapes more candidate posts (the Actor fetches roughly 3× your `maxPosts` to allow for caption filtering). Start with a small `maxPosts` to gauge cost, then scale up. See the [Apify pricing page](https://apify.com/pricing) and the `apify/instagram-scraper` pricing for current rates.

## Tips & advanced options

- **Short, common keywords** (like `stanley`) return more matches than rare phrases.
- Multi-word keywords are searched across several hashtags (the combined phrase plus each word), but results are always filtered by the exact phrase in the caption text.
- Lower `maxPosts` for faster, cheaper runs; raise it for broader coverage.
- Schedule the Actor (Schedules tab) to monitor a keyword over time.

## FAQ, disclaimers, and support

- **Is this legal?** The Actor only collects publicly available data. You are responsible for complying with Instagram's Terms of Service and applicable laws (including data-protection rules) when using the output.
- **Why did I get no results?** The hashtag may have too few public posts, or no caption contained the exact keyword. Try a more common keyword.
- **Why are some posts missing?** Only posts surfaced through the hashtag seed are scanned. Private posts are never accessed.
- **Support / feedback:** Use the **Issues** tab on the Actor page. Custom variations (search by user, place, or comments) can be added on request.
