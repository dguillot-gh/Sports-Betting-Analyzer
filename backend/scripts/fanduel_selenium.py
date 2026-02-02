import json
import time
import sys

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Error: undetected_chromedriver or selenium not installed.")
    print("pip install undetected-chromedriver selenium")
    sys.exit(1)

URL = "https://sportsbook.fanduel.com/motorsport?tab=cook-out-clash"

def scrape_fanduel():
    print(f"Starting browser to scrape {URL}...")
    options = uc.ChromeOptions()
    options.headless = False  # Headless often triggers detection
    
    driver = uc.Chrome(options=options)
    
    try:
        driver.get(URL)
        print("Page loaded. Waiting for odds...")
        
        # Wait for meaningful content (e.g., driver names or odds)
        # Adjust selector based on actual FanDuel class names if known, or generic
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Betting')] | //span[contains(text(), '+')]"))
        )
        time.sleep(5) # Extra buffer for dynamic load
        
        # Extract text
        body_text = driver.find_element(By.TAG_NAME, "body").text
        print(f"Extracted {len(body_text)} characters.")
        
        # Simple parsing for demonstration
        import re
        # Find lines with odds like +500
        lines = body_text.split('\n')
        odds_data = []
        for i, line in enumerate(lines):
            if re.match(r'^\+\d+$', line.strip()) or re.match(r'^\-\d+$', line.strip()):
                # Likely an odd. Driver might be previous line.
                if i > 0:
                     driver_name = lines[i-1]
                     odds = line.strip()
                     odds_data.append({"driver": driver_name, "odds": odds})
        
        print(json.dumps(odds_data, indent=2))
        
        # Save to file
        with open("fanduel_odds.json", "w") as f:
            json.dump(odds_data, f, indent=2)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    scrape_fanduel()
