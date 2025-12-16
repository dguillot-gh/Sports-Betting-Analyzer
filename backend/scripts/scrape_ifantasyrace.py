"""
NASCAR Data Scraper for ifantasyrace.com
Scrapes Total Speed Rankings and Loop Data for NASCAR Cup Series.

Usage:
    python scripts/scrape_ifantasyrace.py --data-type speed-rankings
    python scripts/scrape_ifantasyrace.py --data-type loop-data
    python scripts/scrape_ifantasyrace.py --all
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
from pathlib import Path
from datetime import datetime
import argparse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Respectful scraping settings
REQUEST_DELAY = 2  # seconds between requests
USER_AGENT = 'Mozilla/5.0 (compatible; SportsAnalyzer/1.0; +educational-project)'

BASE_URL = 'https://ifantasyrace.com'

# Track index pages
SPEED_RANKINGS_INDEX = f'{BASE_URL}/total-speed-rankings/'
LOOP_DATA_INDEX = f'{BASE_URL}/fantasy-nascar-box-score-archive/'
DRIVER_RATINGS_INDEX = f'{BASE_URL}/nascar-driver-rating-index/'


class IFantasyRaceScraper:
    """Scraper for ifantasyrace.com NASCAR data."""
    
    def __init__(self, output_dir: str = None):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        
        if output_dir is None:
            output_dir = Path(__file__).parent.parent / 'data' / 'nascar' / 'scraped'
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_page(self, url: str) -> BeautifulSoup:
        """Fetch a page with rate limiting."""
        logger.info(f"Fetching: {url}")
        time.sleep(REQUEST_DELAY)
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    def get_race_links(self, index_url: str) -> list:
        """Get all race-specific page links from an index page."""
        soup = self._get_page(index_url)
        if not soup:
            return []
        
        links = []
        # Find all links that look like race-specific pages
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Match patterns like /2024/05/29/charlotte-2024-nascar-total-speed-rankings/
            if re.search(r'/\d{4}/\d{2}/\d{2}/.*-(total-speed-rankings|loop-data|box-score)/', href):
                if href not in links:
                    links.append(href if href.startswith('http') else BASE_URL + href)
        
        logger.info(f"Found {len(links)} race links")
        return links
    
    def scrape_speed_rankings_page(self, url: str) -> pd.DataFrame:
        """Scrape a single Total Speed Rankings page."""
        soup = self._get_page(url)
        if not soup:
            return pd.DataFrame()
        
        # Extract race info from URL
        match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/(.*)-total-speed/', url)
        if match:
            year, month, day, track_slug = match.groups()
            race_date = f"{year}-{month}-{day}"
            track = track_slug.replace('-', ' ').title()
        else:
            race_date = 'unknown'
            track = 'unknown'
        
        # Look for tables with speed data
        tables = soup.find_all('table')
        
        all_data = []
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
            
            # Get headers
            headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
            
            # Get data rows
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(cells) >= 2:  # At least driver name and some data
                    data = dict(zip(headers, cells))
                    data['race_date'] = race_date
                    data['track'] = track
                    data['source_url'] = url
                    all_data.append(data)
        
        if all_data:
            logger.info(f"Scraped {len(all_data)} driver records from {track} {race_date}")
            return pd.DataFrame(all_data)
        
        return pd.DataFrame()
    
    def scrape_loop_data_page(self, url: str) -> pd.DataFrame:
        """Scrape a single Loop Data Box Score page."""
        soup = self._get_page(url)
        if not soup:
            return pd.DataFrame()
        
        # Extract race info from URL
        match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/(.*?)/', url)
        if match:
            year, month, day, track_slug = match.groups()
            race_date = f"{year}-{month}-{day}"
            track = track_slug.replace('-', ' ').title()
        else:
            race_date = 'unknown'
            track = 'unknown'
        
        # Look for tables with loop data
        tables = soup.find_all('table')
        
        all_data = []
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
            
            # Get headers
            headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
            
            # Get data rows
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(cells) >= 3:
                    data = dict(zip(headers, cells))
                    data['race_date'] = race_date
                    data['track'] = track
                    data['source_url'] = url
                    all_data.append(data)
        
        if all_data:
            logger.info(f"Scraped {len(all_data)} records from {track} {race_date}")
            return pd.DataFrame(all_data)
        
        return pd.DataFrame()
    
    def scrape_all_speed_rankings(self, max_pages: int = None) -> pd.DataFrame:
        """Scrape all Total Speed Rankings pages."""
        links = self.get_race_links(SPEED_RANKINGS_INDEX)
        
        if max_pages:
            links = links[:max_pages]
        
        all_data = []
        for i, link in enumerate(links):
            logger.info(f"Processing {i+1}/{len(links)}: {link}")
            df = self.scrape_speed_rankings_page(link)
            if not df.empty:
                all_data.append(df)
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            output_file = self.output_dir / 'speed_rankings.csv'
            combined.to_csv(output_file, index=False)
            logger.info(f"Saved {len(combined)} total records to {output_file}")
            return combined
        
        return pd.DataFrame()
    
    def scrape_all_loop_data(self, max_pages: int = None) -> pd.DataFrame:
        """Scrape all Loop Data Box Score pages."""
        links = self.get_race_links(LOOP_DATA_INDEX)
        
        if max_pages:
            links = links[:max_pages]
        
        all_data = []
        for i, link in enumerate(links):
            logger.info(f"Processing {i+1}/{len(links)}: {link}")
            df = self.scrape_loop_data_page(link)
            if not df.empty:
                all_data.append(df)
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            output_file = self.output_dir / 'loop_data.csv'
            combined.to_csv(output_file, index=False)
            logger.info(f"Saved {len(combined)} total records to {output_file}")
            return combined
        
        return pd.DataFrame()
    
    def run_full_collection(self, max_pages_per_type: int = None):
        """Run a full data collection for all data types."""
        logger.info("=" * 60)
        logger.info("Starting full data collection from ifantasyrace.com")
        logger.info("=" * 60)
        
        results = {}
        
        # Speed Rankings
        logger.info("\n--- Collecting Speed Rankings ---")
        speed_df = self.scrape_all_speed_rankings(max_pages=max_pages_per_type)
        results['speed_rankings'] = len(speed_df)
        
        # Loop Data
        logger.info("\n--- Collecting Loop Data ---")
        loop_df = self.scrape_all_loop_data(max_pages=max_pages_per_type)
        results['loop_data'] = len(loop_df)
        
        logger.info("\n" + "=" * 60)
        logger.info("Collection complete!")
        logger.info(f"Speed Rankings: {results['speed_rankings']} records")
        logger.info(f"Loop Data: {results['loop_data']} records")
        logger.info(f"Output directory: {self.output_dir}")
        logger.info("=" * 60)
        
        return results


def main():
    parser = argparse.ArgumentParser(description='Scrape NASCAR data from ifantasyrace.com')
    parser.add_argument('--data-type', choices=['speed-rankings', 'loop-data', 'all'], 
                       default='all', help='Type of data to scrape')
    parser.add_argument('--max-pages', type=int, default=None,
                       help='Maximum pages to scrape per data type (for testing)')
    parser.add_argument('--output-dir', type=str, default=None,
                       help='Output directory for scraped data')
    
    args = parser.parse_args()
    
    scraper = IFantasyRaceScraper(output_dir=args.output_dir)
    
    if args.data_type == 'speed-rankings':
        scraper.scrape_all_speed_rankings(max_pages=args.max_pages)
    elif args.data_type == 'loop-data':
        scraper.scrape_all_loop_data(max_pages=args.max_pages)
    else:
        scraper.run_full_collection(max_pages_per_type=args.max_pages)


if __name__ == '__main__':
    main()
