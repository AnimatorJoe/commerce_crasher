import atexit
import json
import random
import requests
import re
import os

from time import sleep
from typing import Optional, Callable, Any

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from selectorlib import Extractor

load_dotenv()

sources = ["amazon", "1688"]

e_amzn = Extractor.from_yaml_file(os.path.join(os.path.dirname(__file__), "layout/amazon_results.yml"))
e_1688 = Extractor.from_yaml_file(os.path.join(os.path.dirname(__file__), "layout/1688_results.yml"))
e_16882= Extractor.from_yaml_file(os.path.join(os.path.dirname(__file__), "layout/1688_results_image_search.yml"))

p = sync_playwright().start()
browser, context, page, proxy_on = None, None, None, None

def scrape( 
    keyword: str,
    source: str,
    max_results: int = 7,
    remove_partially_extracted: bool = False,
    remove_sponsored: bool = False,
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
    result = e.extract(corpus) # products field should always exist but set as None when extraction fails   

    if result is None or result['products'] is None:
        print("[tl scraper fn] extraction of products from web page failed, recieved the following result")
        print(result)
        return None
    
    assert type(result["products"]) == list, "products should be a list"
    result = result['products']
    if remove_partially_extracted:
        result = keep_non_null_only(result)
    result = result[:max_results] 
    
    if result_output:
        with open(result_output, 'w', encoding="utf-8") as outfile:
            for product in result:
                json.dump(product, outfile, ensure_ascii=False)
                outfile.write("\n")
    
    return result

def scrape_with_1688_image_search(
    image_urls: list,
    max_results: int = 20,
    remove_partially_extracted: bool = False,
    remove_sponsored: bool = False,
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
    
    result = e_16882.extract(corpus) # products field should always exist but set as None when extraction fails
    
    if result is None or result['products'] is None:
        print("[image scraper fn] extraction of products from web page failed, recieved the following result")
        print(result)
        return None
    
    assert type(result["products"]) == list, "products should be a list"
    result = result['products']
    if remove_partially_extracted:
        result = keep_non_null_only(result)
    result = result[:max_results] 
    
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
        return download_with_driver(url, proxy_url=True)
    return r.text
    
def get_1688_corpus(keyword: str) -> Optional[str]:
    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
    print("[get_1688_corpus] retrieving corpus with url %s"%url)
    
    # cannot use get request because 1688 page renders with javascript
    page = download_with_driver(url)
    
    if page is not None:    
        extract = e_1688.extract(page) # TODO: have a better way to check if extraction will fail
        if extract is not None and extract['products'] is not None:
            return page
        
    print("[get_1688_corpus] products cannot be extracted from 1688 web page, retrying page load with proxy")
    page = download_with_driver(url, proxy_url=True)
    
    return page

def get_1688_image_search_corpus(image_urls: list) -> Optional[str]:
    page = download_with_1688_image_search(image_urls)
    
    if page is not None:
        extract = e_16882.extract(page) # TODO: have a better way to check if extraction will fail
        if extract is not None and extract['products'] is not None:
            return page
        
    print(f"[get_1688_image_search_corpus] products cannot be extracted from 1688 image search page with proxy_on={proxy_on}")
    # if not proxy_on:
    #     print("[get_1688_image_search_corpus] proxy is off, retrying page load with proxy")
    #     page = call_until_not_exception_or_none(
    #         n=7,
    #         func=lambda: download_with_1688_image_search(image_urls, proxy=True),
    #         none_handler=lambda attempt: (
    #             print(f"[get_1688_image_search_corpus] page download returned None on attempt {attempt}, retrying with new proxy"),
    #             close_browser_instance(),
    #             initialize_browser(with_proxy=True)
    #         )
    #     )
    
    return page
    
def download_with_driver(url: str, proxy_url: bool = False, reset_cookies: bool = False) -> Optional[str]:
    global browser, context, page

    contents = None
    
    if browser is None:
        print("[driver] browser not initialized, initializing")
        initialize_browser()
    
    if proxy_url:
        if not os.getenv('SCRAPER_API_KEY'):
            print("[driver] no scraper api key found, please set the SCRAPER_API_KEY environment variable")
            return None
        url = f"http://api.scraperapi.com?api_key={os.getenv('SCRAPER_API_KEY')}&url={url}"

    try:
        if reset_cookies:
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

def download_with_1688_image_search(image_urls: list, proxy: Optional[bool] = None, reset_cookies: bool = False) -> Optional[str]:
    global browser, context, page, proxy_on
    
    if proxy is None:
        proxy = proxy_on
    
    if browser is None or proxy_on != proxy:
        print("[1688_image_search_driver] initializing browser")
        initialize_browser(with_proxy=proxy)

    outputs = []
    for i in range(len(image_urls)):
        response = requests.get(image_urls[i])
        output = f"image_{i}.jpg"
        with open(output, 'wb') as file:
            file.write(response.content)
        outputs.append(output)
        
    page_content = None
        
    try:
        if reset_cookies:
            print("[1688_image_search_driver] clearing page cookies")
            context.clear_cookies()
            
        if "s.1688.com/selloffer/offer_search.htm" not in page.url and "s.1688.com/youyuan/index.htm" not in page.url:
            print("[1688_image_search_driver] navigating to 1688's search page")
            page.goto("https://s.1688.com/selloffer/offer_search.htm?keywords=notepad")
            print("[1688_image_search_driver] 1688 search page loaded")
            sleep(3)
        
            print("[1688_image_search_driver] handling potential popup")
            try_closing_1688_popup()

        page.click("div.img-search-upload")
        print("[1688_image_search_driver] image upload initiated")
        sleep(2)

        page.set_input_files("input[type='file']", outputs)
        print("[1688_image_search_driver] input selected")
        sleep(3)
        
        page.wait_for_load_state("load")
        print("[1688_image_search_driver] image search page loaded")
        sleep(5)
        
        print("[1688_image_search_driver] downloading search results page")
        page_content = page.content()
        print("[1688_image_search_driver] download complete")

    except Exception as e:
        print(f"[1688_image_search_driver] An error occurred: {e}")
        return None 
    
    return page_content

def initialize_browser(with_proxy: bool = False):
    global browser, context, page, proxy_on

    userAgentStrings = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.2227.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.3497.92 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    ]

    proxy_address = None
    if with_proxy:
        proxy_address = call_until_not_exception_or_none(3, get_free_proxy_2)
    proxy_on = proxy_address is not None

    if with_proxy and not proxy_on:
        print("[initialize_browser] could not retrieve proxy, proceeding without proxy")
    
    browser = (
        p.chromium.launch(headless=False, proxy={
            "server": proxy_address,
        })
        if proxy_on
        else p.chromium.launch(headless=False)
    )
    
    context = browser.new_context(
        user_agent=random.choice(userAgentStrings), 
        ignore_https_errors=True
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        const get_param = (module, param) => {
            return Object.values(module._nodeModulesPolyfillHeaders)[0][param];
        }
        Object.defineProperty(window, 'RTCPeerConnection', {
            value: get_param(window.RTCPeerConnection, 'mozRTCPeerConnection')
        });
        Object.defineProperty(window, 'RTCSessionDescription', {
            value: get_param(window.RTCSessionDescription, 'mozRTCSessionDescription')
        });
    """)
    context.set_default_timeout(300000)
   
    page = context.new_page()
    
    sleep(3)
   
    print(f"[initialize_browser] browser, context, and page initialized with proxy_on={proxy_on}")

def get_free_proxy() -> Optional[str]:
    if not hasattr(get_free_proxy, "proxies"):
        get_free_proxy.proxies = []
    
    if not get_free_proxy.proxies:
        url = "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&country=us&proxy_format=protocolipport&format=text&timeout=2000"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            get_free_proxy.proxies = [proxy.strip() for proxy in response.text.split('\n') if proxy.strip()]
        
        except requests.RequestException as e:
            print(f"[get_free_proxy] An error occurred when downwloading proxy list: {e}")
            return None
    
    if get_free_proxy.proxies:
        proxy = random.choice(get_free_proxy.proxies)
        print(f"[get_free_proxy] selected proxy {proxy}")
        return proxy
    else:
        return None 
    
def get_free_proxy_2() -> Optional[str]:
    if not hasattr(get_free_proxy_2, "proxies"):
        url = "https://free-proxy-list.net/anonymous-proxy.html"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table')
        rows = table.tbody.find_all('tr')

        get_free_proxy_2.proxies = []
        for row in rows:
            cells = row.find_all('td')
            ip = cells[0].text
            port = cells[1].text
            get_free_proxy_2.proxies.append(f"{ip}:{port}")
   
    proxy = random.choice(get_free_proxy_2.proxies)
    print(f"[get_free_proxy_2] selected proxy {proxy}")
    return proxy 

def keep_non_null_only(json_list: list) -> list:
    return [obj for obj in json_list if all(value is not None for value in obj.values())]

def extract_url_from_css(css_attr: str) -> Optional[str]:
    pattern = r'url\("([^"]+)"\)'
    m = re.search(pattern, css_attr)

    if m:
        url = m.group(1)
        return url
    else:
        return None

def try_closing_1688_popup():
    # sometimes, 1688 will display a popup to block webscrapers (this can be closed by pressing the button with class 'baxia-dialog-close')
    # since the exact conditions for the popup is unpredictable, this function is called whenever it is likely to appear
    try:
        page.click(".baxia-dialog-close", timeout=6000)
        print("[close_1688_popup] popup closed")
    except Exception as e:
        print(f"[close_1688_popup] popup close action failed (possibly not present): {e}") 

def call_until_no_exception(
    n: int,
    func: Callable[[], Any],
    handler: Optional[Callable[[Exception, int], None]] = None
) -> Any:
    for attempt in range(n):
        try:
            return func()
        except Exception as e:
            if handler:
                handler(e, attempt + 1)
            else:
                print(f"[{func.__name__}] attempt {attempt + 1} failed: {e}")
    return None

def call_until_not_exception_or_none(
    n: int,
    func: Callable[[], Any],
    error_handler: Optional[Callable[[Exception, int], None]] = None,
    none_handler: Optional[Callable[[int], None]] = None
) -> Optional[Any]:
    for attempt in range(n):
        try:
            result = func()
            if result is not None:
                return result
            else:
                if none_handler:
                    none_handler(attempt + 1)
                else: 
                    print(f"[{func.__name__}] returned None on attempt {attempt + 1}")
        except Exception as e:
            if error_handler:
                error_handler(e, attempt + 1)
            else:
                print(f"[{func.__name__}] failed on attempt {attempt + 1}: {e}")
    return None

def close_browser_instance():
    global browser, context, page, proxy_on
    if browser is not None:
        print("[close_browser_instance] closing browser")
        browser.close()
    browser, context, page, proxy_on = None, None, None, None

def exit_handler():
    print("application exiting")
    close_browser_instance()
    p.stop()

atexit.register(exit_handler)