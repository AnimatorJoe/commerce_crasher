import ast
import os
import urllib.parse
from datetime import datetime
from typing import Callable, Optional

from api.conversation import Conversation
from scraper.scrape_results_page import scrape, scrape_with_1688_image_search

sources = ["amazon", "1688"]

current_date_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
run_dir = f"runs_{current_date_time}"
os.makedirs(run_dir, exist_ok=True)

def summarize_keyword_conditions(keyword: str) -> Conversation:
    c = Conversation(instruction="please answer in a short sentence and provide a reason")
    
    analytics = generate_keyword_analytics(keyword)
    if analytics is None:
        print(f"analystics generation failed for keyword - {keyword}")
        return None
    
    stringified_analytics = ""
    for analytic in analytics:
        if analytic:
            ol = analytic['original_listing']
            estimated_margin = analytic['estimated_margin'] if analytic['estimated_margin'] else "supplier not found, margin unknown"
            stringified_analytics += f"{ol['name']}, {ol['price']}, {ol['rating']}, {ol['reviews']}, {ol['purchases']}, {estimated_margin}\n"
    
    c.message(
        message=(
            f"for the search term {keyword} on Amazon, the following products were found (name, price, rating, reviews, purchases, est. margin) with images listed in order of search results:\n"
            f"{stringified_analytics}\n"
            "please provide a summary on the challenges of this market, whether it is over saturated, low demand, etc. and why"
        ),
        images_urls=[analytic['original_listing']['image'] for analytic in analytics if analytic is not None])
    
    c.log_conversation(f"{run_dir}/summary_{keyword}_{current_date_time}.txt")
    
    return c   

def generate_keyword_analytics(keyword: str) -> Optional[list]:
    search_results = scrape(
        keyword,
        "amazon",
        max_results=5,
        result_output=f"{run_dir}/amazon_{current_date_time}_{keyword}.jsonl",
        corpus_output=f"{run_dir}/amazon_{current_date_time}_{keyword}.html"
    )
    
    analytics = []
    
    for listing in search_results:
        result = analyze_product_sourcing_with_image_search(listing)
        if result is None or len(result) == 0:
            analytics.append(None)
            continue
        
        listing_cost = float(listing['price'][1:])
        cost_of_matches = [pair['usd_cost'] for pair in result if pair['match']]
        
        estimated_cost = sum(cost_of_matches) / len(cost_of_matches) if len(cost_of_matches) > 0 else None
        estimated_margin = (listing_cost - estimated_cost) / listing_cost if estimated_cost else None
        listing_analytic = {
            "original_listing": listing,
            "comparisons": result,
            "estimated_cost": estimated_cost,
            "estimated_margin": estimated_margin,
        }
        analytics.append(listing_analytic)
        
    return analytics

def analyze_product_sourcing_with_keyword_search(listing: dict, generate_report: bool = True) -> Optional[list]:
    assert set(["name", "price", "image", "url"]).issubset(set(listing.keys())), "listing should have name and image keys"
    
    c = Conversation(instruction="answer only, no talking")
    result = c.message(
        message=("answer only, no talking\n"
                "There is a product on Amazon with the name\n"
                f"{listing['name']}\n"
                "The picture of it is attached.\n"
                "Give me the best Chinese search term you would use to find it on 1688"),
        images_urls=[listing['image']]
    )
    
    if result is None:
        print(f"search term generation failed for - {listing['name']}")
        return None
    
    used_terms = set()
    search_term = result
    
    results = []
    
    attempts = 5
    for attempt in range(attempts):
        st_encoded = urllib.parse.quote(search_term.encode('gb2312')) # 1688 uses gb2312 encoding for url parameters
        batch_size = 5
        listings = scrape(
            st_encoded,
            "1688",
            max_results=batch_size,
            result_output=f"{run_dir}/1688_{current_date_time}_{search_term}.jsonl",
            corpus_output=f"{run_dir}/1688_{current_date_time}_{search_term}.html"
        )
        
        if listings is None:
            print(f"scraping failed for search term - {search_term}")
            continue
        used_terms.add(search_term)
        
        if attempt == attempts - 1:
            break
        
        matches = 0
        for supplier_listing in listings:
            is_match = match_product_supplier_pair(listing, supplier_listing)
            if is_match:
                matches += 1
                
            pair = {
                "match": is_match,
                "usd_cost": toUSD(float(supplier_listing['price']), "1688"), # 1688 price is in RMB
                "supplier_listing": supplier_listing
            }
            results.append(pair)
        
        is_new = lambda term: term not in used_terms
        
        search_term = c.message_until_response_valid(
            valid=is_new,
            valid_criteria="answer only, no talking, don't repeat past answers, such as\n" + '\n'.join(used_terms),
            message=("Give me the best Chinese search term you would use to find a product on 1688 which matches the Amazon listing.\n"
                    "It should generate the highest number of results matching the Amazon listing.\n"
                    f"The previous search term generated {matches} matches out of {batch_size} results."),
            images_urls=[listing['image']]
        )   
        
        if search_term is None:
            print(f"search term generation on attempt {attempt} failed for - {listing['name']}; skipping current attempt")
            continue
            
    c.log_conversation(f"{run_dir}/term_generation_{listing['name']}_{current_date_time}.txt")
    return results

def analyze_product_sourcing_with_image_search(listing: dict, generate_report: bool = True) -> Optional[list]:
    assert set(["name", "price", "image", "url"]).issubset(set(listing.keys())), "listing should have name and image keys"
    
    c = Conversation()
    
    listing_name = listing['name']
    suggested_listings = scrape_with_1688_image_search(
        image_urls=[listing["image"]],
        max_results=13,
        result_output=f"{run_dir}/1688_{current_date_time}_image_sr_{listing_name}.jsonl",
        corpus_output=f"{run_dir}/1688_{current_date_time}_image_sr_{listing_name}.html"
    )
    
    if suggested_listings is None:
        print(f"image search failed for Amazon listing - {listing['name']}")
        return None
    
    requirements_string = f"answer should be a python list of {len(suggested_listings)} booleans, no talking, no markdown"
    evaluation = is_valid_list_of(bool, len(suggested_listings))
    question_string = (
        "the Amazon product\n"
        f"{listing['name']}\n"
        "has a thumbnail listed on Amazon attached as the first image below\n\n"
        "in addition, I will include several products from 1688\n"
        "their names are listed below and their corresponding thumbnails are attached in the same order\n"
        "please answer with a list of booleans, where each boolean corresponds to whether the 1688 product can be sold as the Amazon product\n\n"
    )
    
    for suggested_listing in suggested_listings:
        question_string += f"{suggested_listing['name']}\n\n"
    
    result = c.message_until_response_valid(
        valid=evaluation,
        valid_criteria=requirements_string,
        message=question_string,
        images_urls=[listing['image']] + [listing['image'] for listing in suggested_listings]
    )
    
    matches = ast.literal_eval(result)
    
    pairs = [
        {
            "match": is_match,
            "usd_cost": toUSD(float(supplier_listing['price']), "1688"), # 1688 price is in RMB
            "supplier_listing": supplier_listing
        }
        for is_match, supplier_listing in zip(matches, suggested_listings)
    ]
    
    c.message("give a short reason for each answer")
    
    c.log_conversation(f"{run_dir}/image_search_{listing['name']}_{current_date_time}.txt")
    
    return pairs

def match_product_supplier_pair(listing: dict, against_listing: dict) -> Optional[bool]:
    assert set(["name", "image"]).issubset(set(listing.keys())), "listing should have name and image keys"
    assert set(["name", "image"]).issubset(set(against_listing.keys())), "against_listing should have name and image keys"
    
    c = Conversation()
    
    if against_listing["image"] is None: # TODO: support 1688 listings with videos instead of images
        return None
    
    result = c.message_until_response_valid(
        valid=lambda x: x.lower() in ["yes", "no"],
        valid_criteria="the answer should be just 'yes' or 'no' in lower case",
        message=("the first product is\n"
                f"{listing['name']}\n"
                "the second is\n"
                f"{against_listing['name']}\n"
                "their images are listed in order. Can I sell the second one as the first one?"),
        images_urls=[listing['image'], against_listing['image']]
    )
    
    if result is None:
        return None
    
    c.message("why?")
    c.log_conversation(f"{run_dir}/matching_against_{listing['name']}.txt")    
    return "yes" in result.lower()

def languageOf(source: str) -> str:
    assert source in sources, f"source should be one of {sources}"
    return "english" if source == "amazon" else "chinese"

def toUSD(amount:float, source: str) -> float:
    assert source in sources, f"source should be one of {sources}"
    return amount if source == "amazon" else round(amount * 0.15, 2)
    
def is_valid_list_of(expected_type : type, length: int) -> Callable[[str], bool]:
    def is_valid_list(string: str) -> bool:
        try:
            result = ast.literal_eval(string)
            if isinstance(result, list) and all(isinstance(item, expected_type) for item in result):
                return len(result) == length
            else:
                return False
        except (ValueError, SyntaxError):
            return False
    return is_valid_list
