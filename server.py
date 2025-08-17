from flask import Flask, render_template, request
import requests
import os
import json
import random
import arrow
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from atproto import Client, models

session = requests.Session()
retries = Retry(total=10, backoff_factor=2, status_forcelist=[502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))
session.mount('http://', HTTPAdapter(max_retries=retries))

with open('stopwords.json', 'r') as stopwords_file:
    STOPWORDS = json.load(stopwords_file)

app = Flask(__name__)

APP_KEY = os.environ.get('APP_KEY')
TOKEN = os.environ.get('TOKEN')
INSTANCE = os.environ.get('INSTANCE')
API_KEY = os.environ.get('TROVE_API_KEY')
KEYWORDS = os.environ.get('KEYWORDS')
API_URL = 'https://api.trove.nla.gov.au/v3/result'
BLUESKY_EMAIL = os.environ.get('BLUESKY_EMAIL')
BLUESKY_PASSWORD = os.environ.get('BLUESKY_PASSWORD')
BLUESKY_CHARACTER_LIMIT = 300
MASTODON_CHARACTER_LIMIT = 500

START_YEAR = os.environ.get('START_YEAR')
END_YEAR = os.environ.get('END_YEAR')

def mastodon_post(message):
    mastodon_url = "https://" + INSTANCE + "/api/v1/statuses"
    headers = {
        'Accept': 'application/json',
        'Content-type': 'application/json',
        'Authorization': 'Bearer ' + TOKEN
    }
    data = {'status': message}
    response = requests.request(method="POST", url=mastodon_url, data=json.dumps(data), headers=headers)

def bluesky_post(message, item):
    bluesky_client = Client()
    bluesky_client.login(BLUESKY_EMAIL, BLUESKY_PASSWORD)

    article_url = f'http://nla.gov.au/nla.news-article{item["id"]}'
    article_title = truncate_text(item['heading'], 200)
    article_snippet = item['snippet']
    newspaper_title = item['title']['title']
    date = arrow.get(item['date'], 'YYYY-MM-DD').format('D MMM YYYY')

    embed_external = models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(
            title=article_title,
            description=article_snippet,
            uri=article_url,
        ),
        **{"$type": "app.bsky.embed.external"}
    )

    record = models.AppBskyFeedPost.Record(
        createdAt=bluesky_client.get_current_time_iso(),
        text=message,
        embed=embed_external
    )

    bluesky_client.com.atproto.repo.create_record(
        data=models.ComAtprotoRepoCreateRecord.Data(
            repo=bluesky_client.me.did,
            collection=models.ids.AppBskyFeedPost,
            record=record
        )
    )

def truncate_text(text, length):
    if len(text) > length:
        text = '{}...'.format(text[:length])
    return text

def clean_newspaper_title(title):
    title = re.sub(r'\s*\(.*?\)', '', title).strip()
    return title.rstrip('.')

def clean_article_heading(heading):
    return heading.rstrip('.')

def truncate_message(message, limit):
    if len(message) > limit:
        return '{}...'.format(message[:limit - 3])
    return message

def prepare_mastodon_post(item, key):
    greeting = 'This historical Australian newspaper article contains the keyword ' + key + ':'
    date = arrow.get(item['date'], 'YYYY-MM-DD').format('D MMM YYYY')
    title = clean_article_heading(truncate_text(item['heading'], 200))
    newspaper_title = clean_newspaper_title(item['title']['title'])
    url = f'http://nla.gov.au/nla.news-article{item["id"]}'
    message = f'{greeting} "{title}", {newspaper_title}, {date} {url}'
    return truncate_message(message, MASTODON_CHARACTER_LIMIT)
    
def prepare_bluesky_post(item, key):
    greeting = 'This historical Australian newspaper article contains the keyword ' + key + ':'
    date = arrow.get(item['date'], 'YYYY-MM-DD').format('D MMM YYYY')
    title = clean_article_heading(truncate_text(item['heading'], 200))
    newspaper_title = clean_newspaper_title(item['title']['title'])
    message = f'{greeting} "{title}", {newspaper_title}, {date}'
    return truncate_message(message, BLUESKY_CHARACTER_LIMIT)

def is_authorized(request):
    return request.args.get('key') == APP_KEY

@app.route('/')
def home():
    return 'hello, I\'m ready to post'

def get_random_facet_value(params, facet):
    facet_params = params.copy()
    facet_params.append(('facet', facet))
    facet_params.append(('category', 'newspaper'))
    try:
        response = session.get(API_URL, params=facet_params)
        data = response.json()
        try:
            values = [t['search'] for t in data['category'][0]['facets'][facet]['term']]
        except (TypeError, KeyError):
            return None
        return random.choice(values)
    except requests.exceptions.RetryError as e:
        print(f"RetryError: {e}")
        return None

def get_total_results(params):
    params.append(('category', 'newspaper'))
    try:
        response = session.get(API_URL, params=params)
        print("get_total_results request URL:", response.url)
        data = response.json()
        if 'category' in data and len(data['category']) > 0:
            total = int(data['category'][0]['records']['total'])
        else:
            total = 0
        return total
    except requests.exceptions.RetryError as e:
        print(f"RetryError: {e}")
        return 0

def get_random_article(query, **kwargs):
    total = 0
    applied_facets = []
    facets = ['month', 'year', 'decade', 'word', 'illustrated', 'category', 'title']
    tries = 0

    # Build params as a list of tuples for repeated l-year
    params = [
        ('encoding', 'json'),
        ('n', '0'),
        ('key', API_KEY),
        ('category', 'newspaper')
    ]

    # Add year range from environment variables if BOTH are set
    if START_YEAR and END_YEAR:
        try:
            start = int(START_YEAR)
            end = int(END_YEAR)
            if start <= end:
                for year in range(start, end + 1):
                    params.append(('l-year', str(year)))
        except ValueError:
            pass

    # Add query
    if query:
        params.append(('q', f'fulltext:{query}'))
    else:
        random_word = random.choice(STOPWORDS)
        params.append(('q', f'fulltext:"{random_word}"'))

    for key, value in kwargs.items():
        params.append((f'l-{key}', value))
        applied_facets.append(key)

    facets[:] = [f for f in facets if f not in applied_facets]
    total = get_total_results(params.copy())

    print(f"N_total (total number of articles matching query): {total}")

    while total == 0 and tries <= 10:
        if not query:
            random_word = random.choice(STOPWORDS)
            params.append(('q', f'fulltext:"{random_word}"'))
        tries += 1

    while total > 100 and len(facets) > 0:
        facet = facets.pop()
        facet_value = get_random_facet_value(params.copy(), facet)
        if facet_value:
            params.append((f'l-{facet}', facet_value))
        total = get_total_results(params.copy())

    N_candidate = 0
    if total > 0:
        # Get a candidate set
        candidate_params = params.copy()
        candidate_params = [p for p in candidate_params if p[0] != 'n']  # Remove any existing 'n'
        candidate_params.append(('n', '100'))
        response = session.get(API_URL, params=candidate_params)
        print("get_random_article candidate request URL:", response.url)
        data = response.json()
        if 'category' in data and len(data['category']) > 0:
            articles = data['category'][0]['records']['article']
            N_candidate = len(articles)
            proportion = N_candidate / total if total > 0 else 0
            print(f"N_candidate (number of articles in final candidate set): {N_candidate}")
            print(f"Proportion: {proportion:.6f}")
            article = random.choice(articles)
            print(article)
            return article
        else:
            return None
    else:
        return None

@app.route('/random/')
def post_random():
    status = 'nothing to post'
    if is_authorized(request):
        keyword = random.choice(KEYWORDS.split(','))
        article = get_random_article(keyword, category='Article')
        if article:
            message = prepare_mastodon_post(article, keyword)
            print(message)
            mastodon_post(message)
            message = prepare_bluesky_post(article, keyword)
            bluesky_post(message, article)
            status = f'<p>I posted!<p> <blockquote>{message}</blockquote>'
        else:
            status = 'sorry, couldn\'t get data from Trove'
    else:
        status = 'sorry, not authorised to post'
    return status

if __name__ == "__main__":
    from os import environ
    app.run(host='0.0.0.0', port=int(environ['PORT']))
