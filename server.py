from flask import Flask, render_template, request, Response, jsonify
import requests
#import tweepy
import os
import json
import random
import arrow
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

## Mastodon API config
token = "42OYj5JGGkKwQQhTPIGdxziueMHE9fyfJ8Sbqc-joIM"
instance = "botsin.space"

s = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[ 502, 503, 504 ])
s.mount('https://', HTTPAdapter(max_retries=retries))
s.mount('http://', HTTPAdapter(max_retries=retries))

with open('stopwords.json', 'r') as json_file:
    STOPWORDS = json.load(json_file)

app = Flask(__name__)

APP_KEY = os.environ.get('APP_KEY')
TOKEN = os.environ.get('TOKEN')
INSTANCE = os.environ.get('INSTANCE')
API_KEY = os.environ.get('TROVE_API_KEY')
#airminded - KEYWORDS replaces TITLES (although functionally equivalent)
KEYWORDS = os.environ.get('KEYWORDS')
API_URL = 'http://api.trove.nla.gov.au/v2/result'

###convert to mastodon
def tweet(message):
    url = "https://" + INSTANCE + "/api/v1/statuses"
    headers =   {
            'Accept': 'application/json', 
            'Content-type': 'application/json', 
            'Authorization': 'Bearer ' + TOKEN
            }
    data =      {  'status': message  }
    response = requests.request(method = "POST", url = url, data = json.dumps(data), headers = headers)


def truncate(message, length):
  if len(message) > length:
    message = '{}...'.format(message[:length])
  return message


def prepare_message(item, key):
    #airminded - customise tweet introduction (could use keyword here)
###    key = 'air raid'
    greeting = 'This Australian newspaper article features the keyword ' + key + ' : '
    details = None
    date = arrow.get(item['date'], 'YYYY-MM-DD').format('D MMM YYYY')
    title = truncate(item['heading'], 200)
    url = f'http://nla.gov.au/nla.news-article{item["id"]}'
    message = f"{greeting} {date}, '{title}': {url}"
    return message

### this needs to be the token but is checking the key is correct or merely that it exists?
### comment out?
def authorised(request):
    if request.args.get('key') == APP_KEY:    
        return True
    else:
    	return False


@app.route('/')
def home():
    return 'hello, I\'m ready to tweet'

def get_random_facet_value(params, facet):
    '''
    Get values for the supplied facet and choose one at random.
    '''
    these_params = params.copy()
    these_params['facet'] = facet
    response = s.get(API_URL, params=these_params)
    data = response.json()
    try:
        values = [t['search'] for t in data['response']['zone'][0]['facets']['facet']['term']]
    except TypeError:
        return None
    return random.choice(values)


def get_total_results(params):
    response = s.get(API_URL, params=params)
    data = response.json()
    total = int(data['response']['zone'][0]['records']['total'])
    return total

#airminded - want to pass the keyword query
#def get_random_article(query=None, **kwargs):
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
        # Note that keeping n at 0 until we've filtered the result set speeds things up considerably
        'n': '0',
        # Uncomment these if you need more than the basic data
        #'reclevel': 'full',
        #'include': 'articleText',
        'key': API_KEY
    }
    if query:
        params['q'] = query
    # If there's no query supplied then use a random stopword to mix up the results
    else:
        random_word = random.choice(STOPWORDS)
        params['q'] = f'"{random_word}"'
    # Apply any supplied factes
    for key, value in kwargs.items():
        params[f'l-{key}'] = value
        applied_facets.append(key)
    # Remove any facets that have already been applied from the list of available facets
    facets[:] = [f for f in facets if f not in applied_facets]
    total = get_total_results(params)
    # If our randomly selected stopword has produced no results
    # keep trying with new queries until we get some (give up after 10 tries)
    while total == 0 and tries <= 10:
        if not query:
            random_word = random.choice(STOPWORDS)
            params['q'] = f'"{random_word}"'
        tries += 1
    # Apply facets one at a time until we have less than 100 results, or we run out of facets
    while total > 100 and len(facets) > 0:
        # Get the next facet
        facet = facets.pop()
        # Set the facet to a randomly selected value
        params[f'l-{facet}'] = get_random_facet_value(params, facet)
        total = get_total_results(params)
        #print(total)
        #print(response.url)
    # If we've ended up with some results, then select one (of the first 100) at random
    if total > 0:
        params['n'] = '100'
        response = s.get(API_URL, params=params)
        data = response.json()
        article = random.choice(data['response']['zone'][0]['records']['article'])
        return article


@app.route('/random/')
def tweet_random():
    status = 'nothing to tweet'
    if authorised(request):
        #airminded - choose random keyword from KEYWORDS instead of newspaper_id from TITLES
        keyword = random.choice(KEYWORDS.split(','))
        print(keyword)
        #airminded - send keyword instead of newspaper_id
        article = get_random_article(keyword, category='Article')
        if article:
            message = prepare_message(article, keyword)
            print(message)
            tweet(message)
            status = f'<p>I tweeted!<p> <blockquote>{message}</blockquote>'
        else:
            status = 'sorry, couldn\'t get data from Trove'
    else:
        status = 'sorry, not authorised to tweet'
    return status

  # listen for requests :)
if __name__ == "__main__":
    from os import environ
    app.run(host='0.0.0.0', port=int(environ['PORT']))
