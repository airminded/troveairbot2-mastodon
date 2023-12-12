from flask import Flask, render_template, request
import requests
import os
import json
import random
import arrow
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from atproto import Client, models

session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
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
API_URL = 'http://api.trove.nla.gov.au/v2/result'
BLUESKY_EMAIL = os.environ.get('BLUESKY_EMAIL')
BLUESKY_PASSWORD = os.environ.get('BLUESKY_PASSWORD')


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
    newspaper_title = item['title']['value']
    date = arrow.get(item['date'], 'YYYY-MM-DD').format('D MMM YYYY')
    embed_external = models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(
            title=article_title,
            description=newspaper_title,
            uri=article_url,
        )
    )
    post_with_link_card = bluesky_client.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=bluesky_client.me.did,
            collection=models.ids.AppBskyFeedPost,
            record=models.AppBskyFeedPost.Main(
                created_at=bluesky_client.get_current_time_iso(),
                text=message,
                embed=embed_external
            ),
        )
    )


def truncate_text(text, length):
    if len(text) > length:
        text = '{}...'.format(text[:length])
    return text


def prepare_post(item, key):
    greeting = 'This historical Australian newspaper article contains the keyword ' + key + ':'
    details = None
    date = arrow.get(item['date'], 'YYYY-MM-DD').format('D MMM YYYY')
    title = truncate_text(item['heading'], 200)
    url = f'http://nla.gov.au/nla.news-article{item["id"]}'
    message = f"{greeting} {date}, '{title}': {url}"
    return message


def is_authorized(request):
    if request.args.get('key') == APP_KEY:
        return True
    else:
        return False


@app.route('/')
def home():
    return 'hello, I\'m ready to post'


def get_random_facet_value(params, facet):
    '''
    Get values for the supplied facet and choose one at random.
    '''
    these_params = params.copy()
    these_params['facet'] = facet
    response = session.get(API_URL, params=these_params)
    data = response.json()
    try:
        values = [t['search'] for t in data['response']['zone'][0]['facets']['facet']['term']]
    except TypeError:
        return None
    return random.choice(values)


def get_total_results(params):
    response = session.get(API_URL, params=params)
    data = response.json()
    total = int(data['response']['zone'][0]['records']['total'])
    return total


def get_random_article(query, **kwargs):
    '''
    Get a random article.
    The kwargs can be any of the available facets, such as 'state', 'title', 'illtype', 'year'.
    '''
    print(query)
    total = 0
    applied_facets = []
    facets = ['month', 'year', 'decade', 'word', 'illustrated', 'category', 'title']
    tries = 0
    params = {
        'zone': 'newspaper',
        'encoding': 'json',
        'n': '0',
        'key': API_KEY
    }
    if query:
        params['q'] = query
    else:
        random_word = random.choice(STOPWORDS)
        params['q'] = f'"{random_word}"'

    for key, value in kwargs.items():
        params[f'l-{key}'] = value
        applied_facets.append(key)

    facets[:] = [f for f in facets if f not in applied_facets]
    total = get_total_results(params)

    while total == 0 and tries <= 10:
        if not query:
            random_word = random.choice(STOPWORDS)
            params['q'] = f'"{random_word}"'
        tries += 1

    while total > 100 and len(facets) > 0:
        facet = facets.pop()
        params[f'l-{facet}'] = get_random_facet_value(params, facet)
        total = get_total_results(params)

    if total > 0:
        params['n'] = '100'
        response = session.get(API_URL, params=params)
        data = response.json()
        article = random.choice(data['response']['zone'][0]['records']['article'])
        print(article)
        return article


@app.route('/random/')
def post_random():
    status = 'nothing to post'
    if is_authorized(request):
        keyword = random.choice(KEYWORDS.split(','))
        print(keyword)
        article = get_random_article(keyword, category='Article')
        if article:
            message = prepare_post(article, keyword)
            print(message)
            #mastodon_post(message)
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
