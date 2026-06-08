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
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

import httpx
from apify import Actor, Event

from .analysis import DEFAULT_MODEL, analyze_sentiment, classify_polemic

# Relative date inputs like "7 days", "2 weeks", "1 month", "1 year".
RELATIVE_DATE_RE = re.compile(r'^\s*(\d+)\s*(day|week|month|year)s?\s*$', re.IGNORECASE)
_RELATIVE_UNIT_DAYS = {'day': 1, 'week': 7, 'month': 30, 'year': 365}

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


def normalize_text(value: object) -> str:
    """Lowercase and strip accents/diacritics for forgiving text matching.

    "Jardim Botânico" and "jardim botanico" become the same string, so a location
    typed without accents still matches.
    """
    if not value:
        return ''
    decomposed = unicodedata.normalize('NFKD', str(value))
    without_accents = ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold().strip()


def matches_location(caption: object, location_name: object, location: str) -> bool:
    """Smart location match: the place may be in the post's location tag OR caption.

    Matching is accent- and case-insensitive. An empty ``location`` means no filter.
    """
    needle = normalize_text(location)
    if not needle:
        return True
    return needle in normalize_text(location_name) or needle in normalize_text(caption)


def coerce_count(value: object) -> int:
    """Normalize a like/comment count to a non-negative int.

    Instagram sometimes returns ``None`` or ``-1`` when a count is hidden; we treat
    those as ``0`` so the minimum filters behave predictably.
    """
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def parse_date_input(value: object) -> date | None:
    """Parse a user date bound into a ``date``.

    Accepts an absolute ISO date/datetime (``2024-01-31`` or ``2024-01-31T..``) or a
    relative form (``7 days``, ``2 weeks``, ``1 month``, ``1 year``) counted back from
    today (UTC). Returns ``None`` when the value is empty or unparseable.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    match = RELATIVE_DATE_RE.match(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        days = _RELATIVE_UNIT_DAYS[unit] * amount
        return datetime.now(timezone.utc).date() - timedelta(days=days)

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def post_date(timestamp: object) -> date | None:
    """Extract the calendar date from a post's ISO ``timestamp`` (``None`` if unknown)."""
    if not timestamp:
        return None
    try:
        return date.fromisoformat(str(timestamp)[:10])
    except ValueError:
        return None


def sort_posts(posts: list[dict], order: str) -> list[dict]:
    """Sort posts by ``timestamp``. ``order`` is ``newest`` or ``oldest``.

    Posts with a known ISO timestamp are sorted first (ISO 8601 strings sort
    chronologically as text); posts with an unknown timestamp are appended last.
    """
    known = [p for p in posts if p.get('timestamp')]
    unknown = [p for p in posts if not p.get('timestamp')]
    known.sort(key=lambda p: p['timestamp'], reverse=(order == 'newest'))
    return known + unknown


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
        'locationName': item.get('locationName'),
        'locationId': item.get('locationId'),
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


def comment_post_key(comment: dict) -> str | None:
    """Best-effort canonical post URL that a scraped comment belongs to."""
    for field in ('postUrl', 'url'):
        canonical = canonical_post_url(comment.get(field, '') or '')
        if canonical:
            return canonical
    short_code = comment.get('postShortCode') or comment.get('postShortcode')
    if short_code:
        return f'https://www.instagram.com/p/{short_code}/'
    return None


async def scrape_comments_for_posts(post_urls: list[str], max_comments: int) -> dict[str, list[dict]]:
    """Scrape comments for the given post URLs and group them by canonical post URL.

    A single ``instagram-scraper`` run (resultsType=comments) handles every URL. When
    only one post is requested, all returned comments are attributed to it directly,
    which is both correct and robust.
    """
    grouped: dict[str, list[dict]] = {}
    urls = [u for u in (canonical_post_url(u) or u for u in post_urls) if u]
    if not urls:
        return grouped

    comments_input = {
        'directUrls': urls,
        'resultsType': 'comments',
        'resultsLimit': max_comments,
        'addParentData': True,
    }
    Actor.log.info(f'Scraping up to {max_comments} comments for {len(urls)} polemic post(s)...')
    run = await Actor.call(INSTAGRAM_SCRAPER_ACTOR, run_input=comments_input)

    dataset_id = get_dataset_id(run)
    if dataset_id is None:
        Actor.log.warning('Comment scrape returned no dataset; skipping sentiment for these posts.')
        return grouped

    single_key = canonical_post_url(urls[0]) if len(urls) == 1 else None
    dataset = await Actor.open_dataset(id=dataset_id)
    async for comment in dataset.iterate_items():
        key = single_key or comment_post_key(comment)
        if key:
            grouped.setdefault(key, []).append(comment)
    return grouped


async def run_political_analysis(
    posts: list[dict],
    *,
    subject: str,
    api_key: str,
    model: str,
    max_comments: int,
) -> None:
    """Enrich each post in-place with an ``analysis`` object (best-effort).

    Step 1: classify every post's caption as polemic or not.
    Step 2: scrape comments for the polemic posts (most-liked first).
    Step 3: ask the AI to summarize the sentiment of those comments.
    """
    async with httpx.AsyncClient() as client:
        # Step 1 - classify captions.
        polemic: list[dict] = []
        for post in posts:
            try:
                verdict = await classify_polemic(client, api_key, model, post.get('caption') or '')
            except Exception as exc:  # noqa: BLE001 - analysis is best-effort
                Actor.log.warning(f'Caption classification failed for {post.get("url")}: {exc}')
                post['isPolemic'] = None
                post['analysis'] = {'error': f'classification failed: {exc}'}
                continue
            post['isPolemic'] = verdict['isPolemic']
            post['analysis'] = {'isPolemic': verdict['isPolemic'], 'reason': verdict['reason']}
            if verdict['isPolemic']:
                polemic.append(post)

        Actor.log.info(f'AI classified {len(polemic)}/{len(posts)} posts as polemic.')
        if not polemic:
            return

        # Step 2 - scrape comments for polemic posts.
        try:
            comments_by_post = await scrape_comments_for_posts(
                [p['url'] for p in polemic if p.get('url')], max_comments
            )
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            Actor.log.warning(f'Comment scrape failed; sentiment will be skipped: {exc}')
            comments_by_post = {}

        # Step 3 - sentiment per polemic post.
        for post in polemic:
            key = canonical_post_url(post.get('url', '') or '')
            raw_comments = comments_by_post.get(key, [])
            # Sort by likes (most-liked first), then keep the requested amount.
            raw_comments.sort(key=lambda c: coerce_count(c.get('likesCount')), reverse=True)
            texts = [c.get('text') for c in raw_comments[:max_comments] if c.get('text')]

            if not texts:
                post['analysis']['commentsAnalyzed'] = 0
                post['analysis']['note'] = 'No comments available to analyze.'
                continue

            try:
                sentiment = await analyze_sentiment(
                    client, api_key, model, post.get('caption') or '', texts, subject
                )
            except Exception as exc:  # noqa: BLE001 - best-effort
                Actor.log.warning(f'Sentiment analysis failed for {post.get("url")}: {exc}')
                post['analysis']['commentsAnalyzed'] = len(texts)
                post['analysis']['note'] = f'sentiment failed: {exc}'
                continue

            post['analysis']['commentsAnalyzed'] = len(texts)
            post['analysis'].update(sentiment)
            post['negativePct'] = sentiment['negativePct']
            post['positivePct'] = sentiment['positivePct']


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
        sort_by = (actor_input.get('sortBy') or 'newest').strip().lower()
        min_likes = coerce_count(actor_input.get('minLikes'))
        min_comments = coerce_count(actor_input.get('minComments'))
        posted_after = parse_date_input(actor_input.get('postedAfter'))
        posted_before = parse_date_input(actor_input.get('postedBefore'))
        location = (actor_input.get('location') or '').strip()
        enable_analysis = bool(actor_input.get('enablePoliticalAnalysis'))
        groq_api_key = (actor_input.get('groqApiKey') or os.environ.get('GROQ_API_KEY') or '').strip()
        groq_model = (actor_input.get('groqModel') or DEFAULT_MODEL).strip()
        max_comments = int(actor_input.get('maxComments') or 30)

        if not keyword:
            raise ValueError('Input "keyword" is required, e.g. "stanley" or "very happy".')
        if max_posts <= 0:
            raise ValueError('Input "maxPosts" must be a positive integer.')
        if sort_by not in ('newest', 'oldest'):
            raise ValueError('Input "sortBy" must be either "newest" or "oldest".')
        if max_comments <= 0:
            raise ValueError('Input "maxComments" must be a positive integer.')
        if posted_after and posted_before and posted_after > posted_before:
            raise ValueError('Input "postedAfter" must not be later than "postedBefore".')

        if posted_after or posted_before:
            Actor.log.info(
                f'Date filter: from {posted_after or "any"} to {posted_before or "any"}.'
            )
        if location:
            Actor.log.info(f'Location filter: "{location}" (matched in the post location tag or caption).')

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

        # --- Filter candidates, then sort and store ----------------------------------
        # We match purely on the caption text, apply the engagement minimums, and
        # de-duplicate posts (the same post can arrive from both Google and a hashtag
        # page). All matches are collected first so we can sort before applying the
        # max_posts cap - otherwise the ordering would be wrong.
        candidate_dataset = await Actor.open_dataset(id=dataset_id)

        scanned = 0
        dropped_engagement = 0
        dropped_date = 0
        dropped_location = 0
        seen: set[str] = set()
        matches: list[dict] = []
        async for item in candidate_dataset.iterate_items():
            scanned += 1
            if not caption_contains(item.get('caption'), keyword):
                continue
            post_key = item.get('id') or item.get('shortCode') or item.get('url')
            if post_key in seen:
                continue
            seen.add(post_key)

            post = clean_post(item, keyword)

            # Location filter (place tagged on the post OR mentioned in the caption).
            if not matches_location(post['caption'], post['locationName'], location):
                dropped_location += 1
                continue

            # Date range filter (uses the post's real publish date).
            if posted_after or posted_before:
                pd = post_date(post['timestamp'])
                if pd is None or (posted_after and pd < posted_after) or (posted_before and pd > posted_before):
                    dropped_date += 1
                    continue

            # Engagement filter.
            if coerce_count(post['likesCount']) < min_likes or coerce_count(post['commentsCount']) < min_comments:
                dropped_engagement += 1
                continue

            matches.append(post)

        # Sort by date, then keep only the requested number of posts.
        ordered = sort_posts(matches, sort_by)[:max_posts]

        # Optional AI political-sentiment analysis (toggle).
        if enable_analysis:
            if not groq_api_key:
                Actor.log.warning(
                    'Political analysis is enabled but no Groq API key was provided '
                    '(input "groqApiKey" or env GROQ_API_KEY). Skipping analysis.'
                )
            elif not ordered:
                Actor.log.info('No posts to analyze.')
            else:
                Actor.log.info(f'Running AI political analysis on {len(ordered)} posts with model "{groq_model}"...')
                await run_political_analysis(
                    ordered,
                    subject=keyword,
                    api_key=groq_api_key,
                    model=groq_model,
                    max_comments=max_comments,
                )

        for post in ordered:
            await Actor.push_data(post)

        Actor.log.info(
            f'Done. Scanned {scanned} candidate posts; {len(matches)} passed all filters '
            f'({dropped_location} dropped by location, {dropped_date} by date range, '
            f'{dropped_engagement} by low likes/comments); stored {len(ordered)} sorted by "{sort_by}".'
        )

        if not ordered:
            Actor.log.warning(
                'No posts matched. Try a more common keyword, broaden the location, widen '
                'the date range, or lower the minimum likes/comments - the phrase may be '
                'rare in public captions, or not indexed by Google.'
            )
