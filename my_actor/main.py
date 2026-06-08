"""Main entry point for the Instagram Caption Keyword Search Actor.

This Actor takes a keyword (for example ``stanley`` or ``very happy``) and returns
Instagram posts whose **caption** contains that keyword.

Instagram has no public caption full-text search, so we discover candidate posts
two complementary ways and then match purely on the real caption text:

1. **Google discovery** - we ask ``apify/google-search-scraper`` for
   ``site:instagram.com "keyword"``. Google has indexed the caption text of many
   public posts, so this finds posts by their caption even with no related hashtag.
2. **Hashtag discovery** - we seed Instagram hashtags derived from the keyword to
   widen the candidate pool.

All discovered URLs are scraped in a single ``apify/instagram-scraper`` run to get
full, accurate captions, which we then filter, de-duplicate, and store.

The design degrades gracefully: if one discovery method fails or returns nothing,
the Actor continues with the other instead of aborting the whole run.
"""

from __future__ import annotations

import asyncio
import re

from apify import Actor, Event

# Public Apify Store Actors we compose.
INSTAGRAM_SCRAPER_ACTOR = 'apify/instagram-scraper'
GOOGLE_SEARCH_ACTOR = 'apify/google-search-scraper'

# Limit how many hashtag seeds and Google URLs we feed downstream, to keep the
# Instagram scrape efficient and its cost predictable.
MAX_HASHTAG_SEEDS = 3
INSTAGRAM_POST_URL_RE = re.compile(r'https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[^/?#]+', re.IGNORECASE)


def keyword_to_hashtags(keyword: str) -> list[str]:
    """Build hashtag seeds from a keyword to gather candidate posts.

    We seed with the whole keyword as one hashtag (``very happy`` -> ``veryhappy``)
    plus each individual word (``very``, ``happy``), capped at ``MAX_HASHTAG_SEEDS``.
    """
    seeds: list[str] = []
    combined = re.sub(r'[^0-9a-z]', '', keyword.lower())
    if combined:
        seeds.append(combined)
    for word in re.split(r'\s+', keyword.lower().strip()):
        tag = re.sub(r'[^0-9a-z]', '', word)
        if tag and tag not in seeds:
            seeds.append(tag)
    return seeds[:MAX_HASHTAG_SEEDS]


def canonical_post_url(url: str) -> str | None:
    """Normalize an Instagram post URL to ``https://www.instagram.com/p/<code>/``.

    Returns ``None`` if the URL is not an individual post/reel/tv URL.
    """
    match = INSTAGRAM_POST_URL_RE.match(url or '')
    if not match:
        return None
    # Strip query string / fragment and normalize the host + trailing slash.
    base = match.group(0)
    base = re.sub(r'https?://(?:www\.)?instagram\.com', 'https://www.instagram.com', base, flags=re.IGNORECASE)
    return base.rstrip('/') + '/'


def caption_contains(caption: str | None, keyword: str) -> bool:
    """Case-insensitive substring match of ``keyword`` inside ``caption``."""
    if not caption:
        return False
    return keyword.lower() in caption.lower()


def clean_post(item: dict, keyword: str) -> dict:
    """Pick the useful fields from a raw instagram-scraper item for our dataset."""
    return {
        'keyword': keyword,
        'url': item.get('url'),
        'caption': item.get('caption'),
        'ownerUsername': item.get('ownerUsername'),
        'ownerFullName': item.get('ownerFullName'),
        'likesCount': item.get('likesCount'),
        'commentsCount': item.get('commentsCount'),
        'timestamp': item.get('timestamp'),
        'type': item.get('type'),
        'displayUrl': item.get('displayUrl'),
        'hashtags': item.get('hashtags'),
        'mentions': item.get('mentions'),
        'shortCode': item.get('shortCode'),
        'id': item.get('id'),
    }


def get_dataset_id(run: object) -> str | None:
    """Read the default dataset id from an Actor run, tolerating dict or object form."""
    if run is None:
        return None
    if isinstance(run, dict):
        return run.get('defaultDatasetId')
    # Newer SDK returns a typed ActorRun object.
    return getattr(run, 'default_dataset_id', None)


def build_google_query(keyword: str) -> str:
    """Build a surgical Google dork that targets Instagram *post* captions.

    - ``site:instagram.com`` restricts to Instagram.
    - The quoted keyword forces an exact-phrase match against the indexed caption
      (Instagram exposes the caption in each post page's title/meta description).
    - The negative ``-inurl:`` operators strip profile, explore and hashtag pages so
      more of Google's result budget is spent on actual post URLs. Individual post
      URLs (``/p/``, ``/reel/``, ``/tv/``) are then confirmed in code.
    """
    return f'site:instagram.com "{keyword}" -inurl:/accounts/ -inurl:/explore/ -inurl:/tags/'


async def discover_post_urls_via_google(keyword: str, limit: int) -> list[str]:
    """Find Instagram post URLs whose indexed caption contains the keyword.

    Uses Google as a caption index. Any failure is swallowed and logged - the
    caller falls back to hashtag discovery.
    """
    urls: list[str] = []
    try:
        query = build_google_query(keyword)
        google_input = {
            'queries': query,
            'resultsPerPage': 100,
            # Pull deeper only when the user asks for more posts (1-2 pages).
            'maxPagesPerQuery': 1 if limit <= 100 else 2,
            'mobileResults': False,
        }
        Actor.log.info(f'Calling {GOOGLE_SEARCH_ACTOR} for caption discovery: {query}')
        run = await Actor.call(GOOGLE_SEARCH_ACTOR, run_input=google_input)

        dataset_id = get_dataset_id(run)
        if dataset_id is None:
            Actor.log.warning('Google discovery returned no dataset; continuing with hashtags only.')
            return urls

        seen: set[str] = set()
        dataset = await Actor.open_dataset(id=dataset_id)
        async for item in dataset.iterate_items():
            for result in (item.get('organicResults') or []):
                canonical = canonical_post_url(result.get('url', ''))
                if canonical and canonical not in seen:
                    seen.add(canonical)
                    urls.append(canonical)
                    if len(urls) >= limit:
                        break
            if len(urls) >= limit:
                break
        Actor.log.info(f'Google discovery found {len(urls)} Instagram post URLs.')
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort by design
        Actor.log.warning(f'Google discovery failed ({exc}); continuing with hashtags only.')
    return urls


async def main() -> None:
    """Define the main entry point for the Apify Actor."""
    async with Actor:
        # Handle graceful abort - Actor is being stopped by the user or platform.
        async def on_aborting() -> None:
            await asyncio.sleep(1)
            await Actor.exit()

        Actor.on(Event.ABORTING, on_aborting)

        # --- Read and validate input -------------------------------------------------
        actor_input = await Actor.get_input() or {}
        keyword = (actor_input.get('keyword') or '').strip()
        max_posts = int(actor_input.get('maxPosts') or 50)

        if not keyword:
            raise ValueError('Input "keyword" is required, e.g. "stanley" or "very happy".')
        if max_posts <= 0:
            raise ValueError('Input "maxPosts" must be a positive integer.')

        hashtags = keyword_to_hashtags(keyword)

        Actor.log.info(f'Searching Instagram captions for keyword "{keyword}" (up to {max_posts} posts)...')

        # --- Discovery: Google (caption index) + hashtags ----------------------------
        # Pull a few times more URLs than requested so the caption filter still has
        # enough to reach max_posts.
        google_urls = await discover_post_urls_via_google(keyword, limit=min(max(max_posts * 3, 30), 100))

        per_source_limit = min(max(max_posts * 3, 30), 1000)
        hashtag_urls = [f'https://www.instagram.com/explore/tags/{tag}/' for tag in hashtags]

        direct_urls = google_urls + hashtag_urls
        if not direct_urls:
            raise ValueError(
                f'Could not build any search source from keyword "{keyword}". '
                'It needs at least one letter or digit.'
            )

        Actor.log.info(
            f'Scraping captions from {len(google_urls)} Google-found posts '
            f'and {len(hashtag_urls)} hashtag pages ({", ".join("#" + t for t in hashtags) or "none"})...'
        )

        # --- Single Instagram scrape for accurate captions ---------------------------
        scraper_input = {
            'directUrls': direct_urls,
            'resultsType': 'posts',
            'resultsLimit': per_source_limit,
            'searchLimit': 1,
            'addParentData': False,
        }

        run = await Actor.call(INSTAGRAM_SCRAPER_ACTOR, run_input=scraper_input)

        dataset_id = get_dataset_id(run)
        if dataset_id is None:
            raise RuntimeError(
                f'{INSTAGRAM_SCRAPER_ACTOR} did not return a dataset. '
                'Check that the Actor run succeeded and your account has access to it.'
            )

        # --- Filter candidates by caption substring ----------------------------------
        # We match purely on the caption text and de-duplicate posts (the same post
        # can arrive from both Google and a hashtag page).
        candidate_dataset = await Actor.open_dataset(id=dataset_id)

        matched = 0
        scanned = 0
        seen: set[str] = set()
        async for item in candidate_dataset.iterate_items():
            scanned += 1
            if not caption_contains(item.get('caption'), keyword):
                continue
            post_key = item.get('id') or item.get('shortCode') or item.get('url')
            if post_key in seen:
                continue
            seen.add(post_key)
            await Actor.push_data(clean_post(item, keyword))
            matched += 1
            if matched >= max_posts:
                break

        Actor.log.info(
            f'Done. Scanned {scanned} candidate posts, pushed {matched} whose caption '
            f'contains "{keyword}".'
        )

        if matched == 0:
            Actor.log.warning(
                'No posts matched. Try a more common keyword - the phrase may be rare '
                'in public captions, or not indexed by Google.'
            )
