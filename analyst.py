import ast
from typing import Callable, Optional

from api.conversation import Conversation
from scraper.scrape_results_page import scrape

sources = ["amazon", "1688"]


def summarize_keyword_conditions(keyword: str) -> Optional[Conversation]:
    c = Conversation(instruction="please answer in a short sentence and provide a reason")
    
    analytics = analyze_keyword(keyword)
    if analytics is None:
        print(f"analystics generation failed for keyword - {keyword}")
        return None
    
    stringified_analytics = ""
    for analytic in analytics:
        if analytics:
            ol = analytic['original_listing']
            stringified_analytics += f"{ol['name']}, {ol['price']}, {ol['ratings']}, {ol['reviews']}, {ol['purchases']}, {analytic['estimated_margin']}\n"
    
    c.message(
        f"""for the search term {keyword} on Amazon, the following products were found listed in (name, price, ratings, reviews, purchases, est. margin) with images listed in order or products\n:
        {stringified_analytics}
        please provide a summary on the challenges of this market, whether it is over saturated, low demand, etc. and why""",
        [listing['image'] for listing in analytics if listing is not None])

def analyze_keyword(keyword: str) -> Optional[list]:
    search_results = scrape(keyword, "amazon")
    
    analytics = []
    
    for listing in search_results:
        result = analyze_listing(listing)
        if result is None:
            analytics.append(None)
            continue
        
        average_cost = sum([pair['usd_cost'] for pair in result if pair['match']]) / len(result)
        listing_analytic = {
            "original_listing": listing,
            "estimated_cost": average_cost,
            "estimated_margin": listing['price'] - average_cost / listing['price'],
        }
        analytics.append(listing_analytic)
        
    return analytics

def analyze_listing(listing: str) -> Optional[list]:
    assert set(["name", "price", "image", "url"]).issubset(set(listing.keys())), "listing should have name and image keys"
    
    c = Conversation(instruction="please only answer each question with a python list of strings, no markdown")
    result = c.message_until_response_valid(
        is_valid_list_of(str, 5),
        "the answer should be a length 5 python list of strings, no markdown",
        "There is a product on Amazon with the name\n" +
        f"{listing['name']}\n" +
        "The pricture of it is attached.\n" +
        "Give me 5 chinese search terms you would use to find it on 1688",
        [listing['image']])
    
    if result is None:
        print(f"search term generation failed for - {listing['name']}")
        return None
    search_terms = ast.literal_eval(result)
    
    results = []
    
    for st in search_terms:
        listings = scrape(st, "1688")
        if listings is None:
            print(f"scraping failed for search term - {st}")
            continue
        
        for supplier_listing in listings:
            pair = {
                "match": match_pair(listing, supplier_listing),
                "usd_cost": toUSD(float(supplier_listing['price']), "1688"), # 1688 price is in RMB
                "supplier_listing": supplier_listing
            }
            results.append(pair)
            
    return results

def match_pair(listing: dict, against_listing: dict) -> Optional[bool]:
    assert set(["name", "image"]).issubset(set(listing.keys())), "listing should have name and image keys"
    assert set(["name", "image"]).issubset(set(against_listing.keys())), "against_listing should have name and image keys"
    
    c = Conversation(instruction="please answer with only yes or no")
    
    result = c.message_until_response_valid(
        lambda x: x.lower() in ["yes", "no"],
        "the answer should be just 'yes' or 'no' in lower case",
        f"the first product is {listing['name']}, the second is {against_listing['name']}. Their images are listed in order. Can I sell the second one as the first one?",
        [listing['image'], against_listing['image']])
    
    if result is None:
        return None
    
    return "yes" in result.lower()

def languageOf(source: str) -> str:
    assert source in sources, f"source should be one of {sources}"
    return "english" if source == "amazon" else "chinese"

def toUSD(amount:float, source: str) -> float:
    assert source in sources, f"source should be one of {sources}"
    return amount if source == "amazon" else round(amount * 0.15, 2)
    
def is_valid_list_of(type : type, length: int) -> Callable[[str], bool]:
    def is_valid_list(string: str) -> bool:
        try:
            result = ast.literal_eval(string)
            if isinstance(result, list) and all(isinstance(item, type) for item in result):
                return len(result) == length
            else:
                return False
        except (ValueError, SyntaxError):
            return False
    return is_valid_list