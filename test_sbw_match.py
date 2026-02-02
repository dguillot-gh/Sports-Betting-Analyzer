import asyncio
import httpx
from bs4 import BeautifulSoup

async def test_match():
    url = "https://sportsbookwire.usatoday.com/category/nba/"
    home = "Boston Celtics"
    away = "Milwaukee Bucks"
    
    print(f"Fetching {url}...")
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        response = await client.get(url)
        html = response.text
    
    soup = BeautifulSoup(html, 'html.parser')
    
    home_short = home.split()[-1].lower()
    away_short = away.split()[-1].lower()
    
    print(f"Short names: {home_short}, {away_short}")
    
    found = False
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.text.lower()
        
        if "odds-picks-and-predictions" in href or "odds-picks-and-predictions" in text:
            if (home_short in href or home_short in text) and (away_short in href or away_short in text):
                if "story/sports/nba" in href:
                    print(f"MATCH FOUND!")
                    print(f"Href: {href}")
                    print(f"Text: {a.text}")
                    found = True
                    break
    if not found:
        print("MATCH NOT FOUND")

if __name__ == "__main__":
    asyncio.run(test_match())
