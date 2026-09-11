# Standard library imports
import csv
import datetime
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

# Selenium imports for web scraping
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PIZZA_JSON_PATH = "pizza.json"
RESULTS_DIR = "results"
PAGE_WAIT_SECONDS = 10

# Number of Chrome instances that run at the same time. Each worker now
# reuses the SAME browser for every restaurant assigned to it, instead of
# opening and closing a brand new one per restaurant (see process_batch
# below). 8 is a conservative default for GitHub-hosted runners, which
# only have 2 CPU cores - running many full Chrome instances at once can
# starve the CPU and cause the timeouts/inconsistent scores mentioned in
# the README. Feel free to tune this if you're running elsewhere.
MAX_WORKERS = 8


#   Restaurant class to holds info about each pizza shop and retrieves busy data
class Restaurant:
    def __init__(self, name, url, scores=None):
        self.name = name    #    Name of the shop
        self.url = url    #    Shop URL on google maps
        self.scores = scores if scores is not None else []    #    This list stores business levels
        
    def _get_busy_levels(self, driver):    #    Scrapes the business levels using Selenium
        try:
            driver.get(self.url)
        except Exception as e:
            print(f"Error navigating to {self.url}: {e}")
            return None, None
        try: 
            WebDriverWait(driver, PAGE_WAIT_SECONDS).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[@role='img' and not(ancestor::div[@aria-hidden='true'])]"))
            )   #    Waits for the business level to load.

            images = driver.find_elements(By.XPATH, "//div[@role='img' and not(ancestor::div[@aria-hidden='true'])]")

            current_busy = None
            usual_busy = None
            # Parse the HTML 'aria-label' to scrape the busy percentages
            for image in images:    #
                busy_item = image.get_attribute("aria-label")
                #    Small safety check: some elements have no aria-label at
                #    all, which used to raise a TypeError on the "in" check below.
                if busy_item and "Currently" in busy_item:
                    current_busy = int(busy_item.split(" ")[1].replace("%", ""))
                    usual_busy = int(busy_item.split(" ")[4].replace("%", ""))
                    print(f"URL: {self.url}, current: {current_busy}, usual: {usual_busy}")
                    break

        except Exception as e:
            print(f"Error fetching data for {self.url}: {e}")
            current_busy, usual_busy = None, None

        return current_busy, usual_busy
    #    Updates the score of the business score of the restaurant
    def update(self, driver):
        current_busy, usual_busy = self._get_busy_levels(driver)

        if current_busy is None or usual_busy is None or usual_busy == 0:
            return None

        percent_of_usual_busy = round(current_busy / usual_busy, 2) * 100
        self.scores += [percent_of_usual_busy]

        return percent_of_usual_busy

def build_driver():
    """Builds a headless Chrome driver configured for CI environments."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    #    Forces a desktop-sized viewport. Headless Chrome otherwise defaults
    #    to a small window, which can change how the Google Maps page lays
    #    out and may be part of why the busy element isn't always found.
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(f"--user-data-dir=/tmp/selenium_{uuid.uuid4()}")
    return webdriver.Chrome(options=chrome_options)


def load_restaurants(path=PIZZA_JSON_PATH):
    """Reads pizza.json and returns a list of Restaurant objects."""
    with open(path, "r") as file:
        data = json.load(file)

    print(f'Total number of restaurants: {len(data)}')
    return [Restaurant(place["name"], place["url"]) for place in data]


def chunk_list(items, n):
    """Splits `items` into `n` roughly equal-sized lists (for the worker pool)."""
    n = max(1, min(n, len(items)) or 1)
    k, m = divmod(len(items), n)
    return [items[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


def process_batch(restaurants):
    """
    Processes a batch of restaurants using a single, reused Chrome driver.

    This replaces the old approach of launching (and quitting) a brand new
    Chrome instance for every restaurant. Opening a browser is the slowest
    part of each cycle, so doing it once per worker instead of once per
    restaurant is the main speed improvement in this script.
    """
    driver = build_driver()
    results = []
    try:
        for restaurant in restaurants:
            score = restaurant.update(driver)
            results.append((restaurant, score))
    finally:
        driver.quit()

    return results


def write_results(rows, results_dir=RESULTS_DIR):
    """Writes (restaurant, score) rows to a new timestamped CSV file."""
    os.makedirs(results_dir, exist_ok=True)

    date = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(results_dir, f'pizza_places_{date}.csv')

    with open(filepath, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['name', 'url', 'score'])
        writer.writeheader()
        for restaurant, score in rows:
            if score is not None:
                writer.writerow({'name': restaurant.name, 'url': restaurant.url, 'score': score})

    return filepath


#     Main script logic
def main():
    restaurants = load_restaurants()
    batches = chunk_list(restaurants, MAX_WORKERS)

    rows = []
    #    Run processing in threads: each thread owns one Chrome driver and
    #    works through its own batch of restaurants sequentially.
    with ThreadPoolExecutor(max_workers=len(batches)) as executor:
        for batch_results in executor.map(process_batch, batches):
            rows.extend(batch_results)

    filepath = write_results(rows)
    scored = sum(1 for _, score in rows if score is not None)
    print(f'Saved {scored}/{len(rows)} scored restaurants to {filepath}')


if __name__ == '__main__':
    main()
        
