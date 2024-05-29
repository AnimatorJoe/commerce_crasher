import requests 
import json 
from time import sleep
from playwright.sync_api import sync_playwright
from selectorlib import Extractor
from typing import Optional

# Create an Extractor by reading from the YAML file
e_amzn = Extractor.from_yaml_file('./layout/amazon_results.yml')
e_1688 = Extractor.from_yaml_file('./layout/1688_results.yml')

def scrape(keyword: str, source: str, result_output: Optional[str] = None, corpus_output: Optional[str] = None) -> dict:
    if source not in ["amazon", "1688"]:
        print("invalid source, select either 'amazon' or '1688'")
        return
        
    corpus = get_amazon_corpus(keyword) if source == "amazon" else get_1688_corpus(keyword)
    e = e_amzn if source == "amazon" else e_1688
    result = e.extract(corpus)
    
    if result_output:
        with open(result_output, 'w', encoding="utf-8") as outfile:
            for product in result['products']:
                json.dump(product, outfile, ensure_ascii=False)
                outfile.write("\n")
    
    if corpus_output:
        with open(corpus_output, 'w') as outfile:
            outfile.write(corpus)
    
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
    print("Downloading %s"%url)   
    r = requests.get(url, headers=headers)
    
    # Simple check to check if page was blocked (Usually 503)
    if r.status_code > 500:
        if "To discuss automated access to Amazon data please contact" in r.text:
            print("Page %s was blocked by Amazon. Please try using better proxies if failure persists."%url)
        else:
            print("Page %s must have been blocked by Amazon as the status code was %d"%(url,r.status_code))
        
        print("attempting to bypass with webdriver")
        return scrape_with_driver(url)
    return r.text
    
def get_1688_corpus(keyword: str) -> Optional[str]:
    # Download the page using requests
    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
    print("Downloading %s"%url)
    
    # cannot use get request because 1688 page renders with javascript
    return scrape_with_driver(url)

def scrape_with_driver(url: str) -> Optional[str]:
    contents = None

    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch()
        print("Browser launched")
        # Open new page
        page = browser.new_page()
        # Go to the specified URL
        page.goto(url)
        # Wait for 2 seconds
        print("Waiting for page render")
        sleep(2)
        # Get page HTML content
        contents = page.content()
        # Close page
        page.close()
        browser.close()
        
    return contents
    
