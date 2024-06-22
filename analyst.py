import ast
import os
import re
import urllib.parse
from datetime import datetime
from typing import Callable, Optional

from api.conversation import Conversation
from scraper.scrape_results_page import scrape, scrape_with_1688_image_search
from recorder import writeRuntimeState 

sources = ["amazon", "1688"]

current_date_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
run_dir = f"runs/run_{current_date_time}"

def search_term_exploration(initial_term: str, recursions: int=2, branching_factor: int=3): 
    global run_dir
    run_dir = f"runs/run_{initial_term}_{datetime.now().strftime('%Y-%m-%d_%H-%M')}" 
    os.makedirs(run_dir, exist_ok=True)
    
    terms_so_far = set()
    state = []    
    queue = [{
        "term": initial_term,
        "parent": None,
        "depth": 0
    }]
    c = Conversation(instruction=(
        "I will provide webscraped search results on Amazon for select keywords. "
        "Some scraped strings could be invalid, if so, ignore them. "
        "Good profit margin is anything >50 percent; High volume is anything with more than 100 reviews or 1k purchases (purchases might not be scraped correctly, if so, ignore them). High price is anything >100 bucks; Good review is anything above 3.75 stars."
    ))
        
    while len(queue) > 0:
        element = queue.pop(0)
        term = element["term"]
        parent = element["parent"]
        depth = element["depth"]
        
        
        analytics = generate_keyword_analytics(term)
        if analytics is None:
            print(f"analystics generation failed for keyword - {term}")
            continue
        
        names, prices, ratings, reviews, purchases, margins, images = [], [], [], [], [], [], []
        for analytic in analytics:
            ol = analytic['original_listing']
            names.append(ol['name'])
            prices.append(ol['price'])
            ratings.append(ol['rating'])
            reviews.append(ol['reviews'])
            purchases.append(ol['purchases'])
            margins.append(analytic['estimated_margin'] if analytic['estimated_margin'] else "supplier not found, margin unknown")
            images.append(ol['image'])
        
        analyst_feedback = c.message(
            message=(
                f"for the search term {term}, the following product info is found on Amazon\n"
                f"names     - {names}\n"
                f"prices    - {prices}\n"
                f"ratings   - {ratings}\n"
                f"reviews   - {reviews}\n"
                f"purchases - {purchases}\n"
                f"margins   - {margins}\n"
                "images are attached\n"
                "write a summary of how this keyword compares to previous ones if there were any\n"
                "please give a bullet point summary each on profit margins, price range, number of reviews/purchases, ratings, and how different the listed products are\n"
                "write the summary at the end on if this term is saturated or niche\n"
            ),
            images_urls=images
        )
        c.log_conversation(f"{run_dir}/term_generation_{initial_term}_{current_date_time}.yml")
       
        
        analysis = {
            "analytics": analytics,
            "analyst_feedback": analyst_feedback
        }
        
        if analysis is None:
            print(f"analysis failed for keyword - {term}")
            return None
        analysis["original_term"] = parent
        analysis["term"] = term
        
        state.append(analysis)
        writeRuntimeState([analysis], f"{run_dir}/term_search.yml")

        if depth >= recursions:
            continue


        valid = lambda x: is_valid_list_of(str, branching_factor)(x) and all(term not in terms_so_far for term in ast.literal_eval(x))
        new_terms = c.message_until_response_valid(
            valid=valid,
            valid_criteria=f"answer should be a python list of {branching_factor} strings not including any elemet of {terms_so_far}, no talking, no markdown",
            message=("what are some unique items from the search results I shared\n"
                    "based on this, come up with more niche keywords which could have high profit margin and low competition\n"
                    "the keywords should be short and something a user would likely type in")
        )
        c.log_conversation(f"{run_dir}/term_generation_{initial_term}_{current_date_time}.yml")
        new_terms = ast.literal_eval(new_terms)
        terms_so_far.update(new_terms)
        
        for new_term in new_terms:
            queue.append({
                "term": new_term,
                "parent": term,
                "depth": depth + 1
            })

def generate_keyword_analytics(keyword: str) -> Optional[list]:
    search_results = scrape(
        keyword=keyword,
        source="amazon",
        max_results=5,
        remove_partially_extracted=True,
        result_output=f"{run_dir}/amazon_{current_date_time}_{clean_file_path(keyword)}.jsonl",
    )
    if search_results is None:
        print(f"failed to get amazon search results for {keyword}")
        return None
    
    analytics = []
    
    for listing in search_results:
        try:
            result = analyze_product_sourcing_with_image_search(listing)
            if result is None or len(result) == 0:
                raise ValueError("No valid result")
            
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
        except ValueError as e:
            print(f"Error processing listing: {e}")
            listing_analytic = {
                "original_listing": listing,
                "comparisons": [],
                "estimated_cost": None,
                "estimated_margin": None,
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
            keyword=st_encoded,
            source="1688",
            max_results=batch_size,
            remove_partially_extracted=True,
            result_output=f"{run_dir}/1688_{current_date_time}_{clean_file_path(search_term)}.jsonl",
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
            
    c.log_conversation(f"{run_dir}/term_generation_{clean_file_path(listing['name'])}_{current_date_time}.yml")
    return results

def analyze_product_sourcing_with_image_search(listing: dict, generate_report: bool = True) -> Optional[list]:
    assert set(["name", "price", "image", "url"]).issubset(set(listing.keys())), "listing should have name and image keys"
    
    c = Conversation()
    
    listing_name = listing['name']
    suggested_listings = scrape_with_1688_image_search(
        image_urls=[listing["image"]],
        max_results=13,
        remove_partially_extracted=True,
        result_output=f"{run_dir}/1688_{current_date_time}_image_sr_{clean_file_path(listing_name)}.jsonl",
    )
    
    if suggested_listings is None:
        print(f"image search failed for Amazon listing - {listing['name']}")
        return None
     
    requirements_string = f"answer should be a python list of {len(suggested_listings)} booleans, no talking, no markdown"
    evaluation = is_valid_list_of(bool, len(suggested_listings))
    question_string = (
        "the Amazon product\n"
        f"{listing['name']}\n"
        "has an Amazon thumbnail attached as the first image below\n\n"
        "products from 1688 have names and thumbnails listed after in the same order\n"
        "return a list of booleans, for if each of the 1688 product can be sold as the Amazon one\n\n"
    )
    for suggested_listing in suggested_listings:
        question_string += f"{suggested_listing['name']}\n\n"
    
    result = c.message_until_response_valid(
        valid=evaluation,
        valid_criteria=requirements_string,
        message=question_string,
        images_urls=[listing['image']] + [listing['image'] for listing in suggested_listings]
    )
    
    if result is None:
        print(f"matching failed for Amazon listing - {listing['name']}")
        return None
    
    matches = ast.literal_eval(result)
    
    pairs = []
    for is_match, supplier_listing in zip(matches, suggested_listings):
        try:
            usd_cost = toUSD(float(supplier_listing['price']), "1688")
            pairs.append({
                "match": is_match,
                "usd_cost": usd_cost,
                "supplier_listing": supplier_listing
            })
        except ValueError as e:
            print(f"Error processing listing: {e}")
            continue
    
    c.message("give a short reason for each answer")
    
    c.log_conversation(f"{run_dir}/image_search_{clean_file_path(listing['name'])}_{current_date_time}.yml")
    
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
    c.log_conversation(f"{run_dir}/matching_against_{clean_file_path(listing['name'])}.yml")
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

def clean_file_path(file_path):
    allowed_chars = re.compile(r'[^a-zA-Z0-9_.\\-]')
    cleaned_path = allowed_chars.sub('_', file_path)
    return cleaned_path
