# Commerce Crasher

A tool for recursively finding product ideas on amazon.com by referencing prices on 1688 and doing analysis on competitive landscape.

## Set up

1. Create `.env` file in the root directory with the following:

```
OPENAI_API_KEY=[openai api key]
ANTHROPIC_API_KEY=[anthropic api key]
SCRAPER_API_KEY=[scraperapi api key]
```

2. Create venv and install dependencies

```
python3.9 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
