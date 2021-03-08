from json import load, loads
from wallabag_api.wallabag import Wallabag
import asyncio
import aiohttp
import re
import urllib.parse as urlparse
from urllib.parse import parse_qs
import os
from dataclasses import dataclass
from pathlib import Path
from bs4 import BeautifulSoup


@dataclass
class Config:
    client_secret: str
    client_id: str
    username: str
    password: str
    hostname: str


def config() -> Config:
    

    if Path('credentials.json').is_file():
        with open('credentials.json', 'r') as f:
            credentials = load(f)
            return Config(
                credentials['client_secret'],
                credentials['client_id'],
                credentials['username'],
                credentials['password'],
                credentials['host']
            )
    else:
        return Config(
            os.environ['CLIENT_SECRET'],
            os.environ['CLIENT_ID'],
            os.environ['USERNAME'],
            os.environ['PASSWORD'],
            os.environ['WALLABAG_HOST'],
        )


class YoutubeEnhancer():
    def __init__(self):
        self.matcher = re.compile(r"https?://(.*)youtube.com/(.*)")
        

    def should(self, article) -> bool:
        url = article['url'] or ""
        return self.matcher.match(url)

    async def patch(self, article, session=None) -> dict:
        url = article['url'] or ""
        parsed = urlparse.urlparse(url)
        url = parse_qs(parsed.query)['url']

        d = {}

        if url:
            d['origin_url'] = url[0]
            url = url[0]

        async with session.get(url) as resp:
            html =  await resp.text()
            soup = BeautifulSoup(html, 'html.parser')

            descriptions = [link for link in soup.find_all('meta') if "name" in link.attrs and link.attrs["name"] == "description"]
            if descriptions:
                d['content'] = descriptions[0].attrs['content']

        return d

enhancers = [YoutubeEnhancer()]

async def patch_article(wallabag, article, **modification):
    id = article['id']
    path = f'/api/entries/{id}.json'
    if 'tags' in modification:
        modification['tags'] = ",".join(modification['tags'])
    modification['access_token'] = wallabag.token
    return await wallabag.query(path, "patch", **modification)


def has_processed_tag(article):
    tags = article['tags']
    return any(map(lambda tag: tag['slug'] == 'processed', tags))


def get_tags_with_processed(article):
    print(article['tags'])
    return [tag['slug'] for tag in article['tags']] + ['processed']



async def get_articles(wallabag):
        params = {'delete': 0,
                  'sort': 'created',
                  'order': 'desc',
                  'page': 1,
                  'perPage': 3000,
                  'tags': []}
        data = await wallabag.get_entries(**params)
        return data['_embedded']['items']

async def main(config: Config, loop):    
    token = await Wallabag.get_token(
        host=config.hostname,
        client_id=config.client_id,
        client_secret=config.client_secret,
        username=config.username,
        password=config.password)

    async with aiohttp.ClientSession(loop=loop) as session:
        wallabag = Wallabag(host=config.hostname,
                        client_secret=config.client_secret,
                        client_id=config.client_id,
                        token=token,
                        extension="json",
                        aio_sess=session)

        all_article = await get_articles(wallabag)
        for article in all_article:
            is_processed = has_processed_tag(article)
            if not is_processed:
                print(f"processing {article['id']}")

                d = {
                    'tags': get_tags_with_processed(article)
                }

                for enhancer in enhancers:
                    if enhancer.should(article):
                        result = await enhancer.patch(article, session=session)
                        d = {**d, **result}

                await patch_article(wallabag, article, **d)
            else:
                print(f"skiping {article['id']}")

                    


if __name__ == '__main__':
    config = config()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(config, loop))