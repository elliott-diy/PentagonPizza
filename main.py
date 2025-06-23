# Standard library imports
import datetime
import os
import time
import json
import csv
from concurrent.futures import ThreadPoolExecutor

# Selenium imports for web scraping
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

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
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[@role='img' and not(ancestor::div[@aria-hidden='true'])]"))
            )   #    Waits for the business level to load.

            images = driver.find_elements(By.XPATH, "//div[@role='img' and not(ancestor::div[@aria-hidden='true'])]")

            current_busy = None
            usual_busy = None
            # Parse the HTML 'aria-label' to scrape the busy percentages
            for image in images:    #
                busy_item = image.get_attribute("aria-label")
                if "Currently" in busy_item:
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

#     Function to process a single restaurant in a thread
def process_restaurant(restaurant):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)

    try:
        score = restaurant.update(driver)
    finally:
        driver.quit()

    return restaurant, score

#     Main script logic
def main():
    places = []
    scores = []
    
    with open("pizza.json", "r") as file:    #    Updates the pizza.json file
        data = json.load(file)
        print(f'Total number of restaurants: {len(data)}')
        for place in data:
            name = place["name"]
            url = place["url"]
            restaurant = Restaurant(name, url)
            places.append(restaurant)
    #     Output directory and filename setup
    date = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  

    if not os.path.exists("results"):
        os.makedirs("results")
    #    Write results to CSV
    with open(f'results/pizza_places_{date}.csv', 'w', newline='') as csvfile:  
        fieldnames = ['name', 'url', 'score']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        #    Run processing in threads
        with ThreadPoolExecutor(max_workers=25) as executor:
            future_to_restaurant = {executor.submit(process_restaurant, restaurant): restaurant for restaurant in places}
            for future in future_to_restaurant:
                restaurant, score = future.result()
                if score is not None:
                    scores.append(score)
                    writer.writerow({'name': restaurant.name, 'url': restaurant.url, 'score': score})



if __name__ == '__main__':
    main()
