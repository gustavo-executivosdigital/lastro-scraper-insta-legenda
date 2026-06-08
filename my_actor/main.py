"""Main entry point for the Instagram Caption Keyword Search Actor.

This Actor takes a keyword (for example ``stanley`` or ``very happy``) and returns
Instagram posts whose caption contains that keyword.

It works by composing Apify's battle-tested ``apify/instagram-scraper`` Actor:

1. The keyword is turned into a hashtag seed (``very happy`` -> ``#veryhappy``) so we
   have a pool of candidate posts that are likely to mention the keyword.
2. ``apify/instagram-scraper`` scrapes those candidate posts.
3. We keep only the posts whose caption actually contains the keyword as a
   case-insensitive substring, and push them to the dataset.
"""

from __future__ import annotations

import asyncio
import re

from apify import Actor, Event

# The public Apify Store Actor we compose for the heavy lifting of scraping Instagram.
INSTAGRAM_SCRAPER_ACTOR = 'apify/instagram-scraper'


def keyword_to_hashtag(keyword: str) -> str:
    """Turn a free-text keyword into a single Instagram hashtag seed.

    Instagram hashtags cannot contain spaces or punctuation, so we strip everything
    that is not a letter or a digit. ``very happy`` -> ``veryhappy``.
    """
    return re.sub(r'[^0-9a-z]', '', keyword.lower())


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

        hashtag = keyword_to_hashtag(keyword)
        if not hashtag:
            raise ValueError(
                f'Keyword "{keyword}" has no letters or digits to build a hashtag from.'
            )

        # Scrape more candidates than requested, because the caption filter drops some.
        candidate_limit = min(max(max_posts * 3, 30), 1000)

        Actor.log.info(
            f'Searching Instagram for keyword "{keyword}" '
            f'(hashtag seed #{hashtag}, up to {max_posts} matching posts)...'
        )

        # --- Run the Instagram scraper -----------------------------------------------
        scraper_input = {
            'directUrls': [f'https://www.instagram.com/explore/tags/{hashtag}/'],
            'resultsType': 'posts',
            'resultsLimit': candidate_limit,
            'searchLimit': 1,
            'addParentData': False,
        }

        Actor.log.info(f'Calling {INSTAGRAM_SCRAPER_ACTOR} to fetch up to {candidate_limit} candidate posts...')
        run = await Actor.call(INSTAGRAM_SCRAPER_ACTOR, run_input=scraper_input)

        dataset_id = get_dataset_id(run)
        if dataset_id is None:
            raise RuntimeError(
                f'{INSTAGRAM_SCRAPER_ACTOR} did not return a dataset. '
                'Check that the Actor run succeeded and your account has access to it.'
            )

        # --- Filter candidates by caption substring ----------------------------------
        candidate_dataset = await Actor.open_dataset(id=dataset_id)

        matched = 0
        scanned = 0
        async for item in candidate_dataset.iterate_items():
            scanned += 1
            if caption_contains(item.get('caption'), keyword):
                await Actor.push_data(clean_post(item, keyword))
                matched += 1
                if matched >= max_posts:
                    break

        Actor.log.info(
            f'Done. Scanned {scanned} candidate posts, pushed {matched} matching the keyword "{keyword}".'
        )

        if matched == 0:
            Actor.log.warning(
                'No posts matched. Try a more common keyword, or note that the '
                'hashtag may have too few public posts.'
            )
