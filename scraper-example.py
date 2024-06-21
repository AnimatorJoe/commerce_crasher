from scraper.scrape_results_page import scrape, scrape_with_1688_image_search

# scrape("laptop", "1688", result_output="1688_laptops.jsonl")
scrape("ektorp sofa cover", "amazon", result_output="amazon_sofa_covers.jsonl")

# scrape_with_1688_image_search(
#     image_urls=["https://m.media-amazon.com/images/I/71MYcD-6FOL._AC_UL320_.jpg"],
#     result_output="1688_lamps.jsonl",
# )