import atexit
import json
import requests
import re
import os

from time import sleep
from typing import Optional

from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from selectorlib import Extractor

load_dotenv()

sources = ["amazon", "1688"]

e_amzn = Extractor.from_yaml_file(os.path.join(os.path.dirname(__file__), "layout/amazon_results.yml"))
e_1688 = Extractor.from_yaml_file(os.path.join(os.path.dirname(__file__), "layout/1688_results.yml"))
e_16882= Extractor.from_yaml_file(os.path.join(os.path.dirname(__file__), "layout/1688_results_image_search.yml"))

p = sync_playwright().start()
browser, context, page = None, None, None

def scrape( 
    keyword: str,
    source: str,
    max_results: int = 7,
    result_output: Optional[str] = None,
    corpus_output: Optional[str] = None
) -> Optional[list]:
    
    assert source in sources, f"source should be one of {sources}"
        
    corpus = get_amazon_corpus(keyword) if source == "amazon" else get_1688_corpus(keyword)
    
    if corpus is None:
        print(f"[tl scraper fn] failed to retrieve corpus from web page for {keyword} on {source}")
        return None
    
    if corpus_output:
        with open(corpus_output, 'w') as outfile:
            outfile.write(corpus)
    
    e = e_amzn if source == "amazon" else e_1688
    result = e.extract(corpus)
    
    if result is None or result['products'] is None:
        print("[tl scraper fn] extraction of products from web page failed, recieved the following result")
        print(result)
        return None
    
    result = result['products'][:max_results]
    
    if result_output:
        with open(result_output, 'w', encoding="utf-8") as outfile:
            for product in result:
                json.dump(product, outfile, ensure_ascii=False)
                outfile.write("\n")
    
    return result

def scrape_with_1688_image_search(
    image_urls: list,
    max_results: int = 20,
    result_output: Optional[str] = None,
    corpus_output: Optional[str] = None
) -> Optional[list]:
    corpus = get_1688_image_search_corpus(image_urls)
    
    if corpus is None:
        print(f"[image scraper fn] failed to retrieve corpus from web page for images {image_urls}")
        return None
    
    if corpus_output:
        with open(corpus_output, 'w') as outfile:
            outfile.write(corpus)
    
    result = e_16882.extract(corpus)
    
    if result is None or result['products'] is None:
        print("[image scraper fn] extraction of products from web page failed, recieved the following result")
        print(result)
        return None
    
    result = result['products'][:max_results]
    
    for product in result:
        attribute = product['image']
        if attribute:
            # in 1688 image search, each listing image is stored as a css attribute, extract it here
            image_url = extract_url_from_css(attribute) 
        product['image'] = image_url
    
    if result_output:
        with open(result_output, 'w', encoding="utf-8") as outfile:
            for product in result:
                json.dump(product, outfile, ensure_ascii=False)
                outfile.write("\n")
    
    return result
    
def get_amazon_corpus(keyword: str) -> Optional[str]:
    headers = {
        'dnt': '1',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-user': '?1',
        'sec-fetch-dest': 'document',
        'referer': 'https://www.amazon.com/',
        'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
    }    
    url = f"https://www.amazon.com/s?k={keyword}"
    print("[get_amazon_corpus] retrieving corpus with url %s"%url)
    print("[get_amazon_corpus] retrieving page with get request")   
    r = requests.get(url, headers=headers)
    
    # Simple check to check if page was blocked (Usually 503)
    if r.status_code > 500:
        if "To discuss automated access to Amazon data please contact" in r.text:
            print("[get_amazon_corpus] rPage %s was blocked by Amazon."%url)
        else:
            print("[get_amazon_corpus] rPage %s must have been blocked by Amazon as the status code was %d"%(url,r.status_code))
        
        print("[get_amazon_corpus] re-attempting to bypass with webdriver + proxy")
        return scrape_with_driver(url, proxy=True)
    return r.text
    
def get_1688_corpus(keyword: str) -> Optional[str]:
    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
    print("[get_1688_corpus] retrieving corpus with url %s"%url)
    
    # cannot use get request because 1688 page renders with javascript
    page = scrape_with_driver(url)
    
    if page is not None:    
        extract = e_1688.extract(page) # TODO: have a better way to check if extraction will fail
        if extract['products'] is not None:
            return page
        
    print("[get_1688_corpus] products cannot be extracted from 1688 web page, retrying page load with proxy")
    page = scrape_with_driver(url, proxy=True)
    
    return page

def get_1688_image_search_corpus(image_urls: list) -> Optional[str]:
    global browser, context, page
        
    if browser is None:
        print("[scrape_1688_with_image_search] browser not initialized, initializing")
        initialize_browser()

    outputs = []
    for i in range(len(image_urls)):
        response = requests.get(image_urls[i])
        output = f"image_{i}.jpg"
        with open(output, 'wb') as file:
            file.write(response.content)
        outputs.append(output)
        
    page_content = None
        
    try:
        print("[get_1688_image_search_corpus] navigating to 1688's search page")
        page.goto("https://s.1688.com/selloffer/offer_search.htm?keywords=keyboard")
        print("[get_1688_image_search_corpus] 1688 search page loaded")
        sleep(2)

        page.click("div.img-search-upload")
        print("[get_1688_image_search_corpus] image upload initiated")
        sleep(2)

        page.set_input_files("input[type='file']", outputs)
        print("[get_1688_image_search_corpus] input selected")
        sleep(8)

        print("[get_1688_image_search_corpus] downloading search results page")
        page_content = page.content()
        print("[get_1688_image_search_corpus] download complete")

    except Exception as e:
        print(f"An error occurred: {e}")
        return None
    
    return page_content

def scrape_with_driver(url: str, proxy: bool = False) -> Optional[str]:
    global browser, context, page

    contents = None
    
    if browser is None:
        print("[driver] browser not initialized, initializing")
        initialize_browser()
    
    if proxy:
        if not os.getenv('SCRAPER_API_KEY'):
            print("[driver] no scraper api key found, please set the SCRAPER_API_KEY environment variable")
            return None
        url = f"http://api.scraperapi.com?api_key={os.getenv('SCRAPER_API_KEY')}&url={url}"

    try:
        print("[driver] clearing page cookies")
        context.clear_cookies()
        print("[driver] waiting for page render")
        page.goto(url)
        sleep(2)
        print("[driver] downloading %s"%url)
        contents = page.content()
    except Exception as e:
        print("[driver] error occured while scraping page")
        print(e)
        
    return contents

def extract_url_from_css(css_attr: str) -> Optional[str]:
    pattern = r'url\("([^"]+)"\)'
    m = re.search(pattern, css_attr)

    if m:
        url = m.group(1)
        return url
    else:
        return None
   
def initialize_browser():
    global browser, context, page
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    print("[initialize_browser] browser, context, and page initialized")
    
def exit_handler():
    print("application exiting")
    if browser is not None:
        print("closing browser")
        browser.close()
    p.stop()

atexit.register(exit_handler)