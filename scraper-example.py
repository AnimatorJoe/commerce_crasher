from scraper.scrape_results_page import scrape

scrape("laptop", "1688", result_output="1688_laptops.jsonl")
scrape("laptop", "amazon", result_output="amazon_laptops.jsonl")