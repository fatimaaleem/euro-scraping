import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
import time
import logging
import pandas as pd
import re

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Use a headless browser
options = webdriver.ChromeOptions()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev_shm_usage')

driver = None  # Initialize driver to None

try:
    driver = webdriver.Chrome(options=options)

    base_url = "https://www.euronews.com/"
    all_article_links = set()
    max_pages_to_scrape = 5  # Set a limit to prevent infinite loops
    request_delay = 5 # Delay between page requests
    page_load_timeout = 45 # Timeout for page load

    logging.info("Starting link collection with pagination using broader search and more refined filtering.")

    for page_num in range(max_pages_to_scrape):
        # Adjust URL based on pagination structure - based on previous findings, simple page parameter works for initial pages
        url = f"{base_url}?page={page_num}" if page_num > 0 else base_url
        logging.info(f"Attempting to scrape links from {url}")

        try:
            driver.get(url)
            # Wait for any element in the body to be present
            WebDriverWait(driver, page_load_timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )

            soup = BeautifulSoup(driver.page_source, 'html.parser')

            # Identify and collect article links on the current page using a broader approach
            # Look for common article container classes or tags
            article_containers = soup.find_all(['article', 'div', 'section'], class_=lambda x: x and ('article' in x or 'media' in x or 'headline' in x or 'c-article-tile' in x))

            if not article_containers and page_num > 0:
                logging.info(f"No article containers found on page {url}. Assuming end of pagination.")
                break
            elif not article_containers and page_num == 0:
                 logging.error("No article containers found on the first page. Check website structure.")
                 break


            page_links_found = 0
            for container in article_containers:
                for link_element in container.find_all('a', href=True):
                    href = link_element.get('href')
                    if href and href.startswith('/') and len(href) > 1:
                         full_url = requests.compat.urljoin(base_url, href)
                         # More specific filtering to target URLs that likely represent articles
                         # Articles often contain the year and a descriptive slug.
                         # Exclude known non-article patterns and require a pattern that looks like an article link.
                         excluded_patterns = ['/tag/', '/my-europe/', '/video/', '/culture/', '/green/', '/programs/', '/live', '/widgets', '/business/markets'] # Added more exclusions
                         # Example of an article pattern: /YYYY/MM/DD/slug
                         article_pattern = r'/\d{4}/\d{2}/\d{2}/' # Looking for /YYYY/MM/DD/ in the URL

                         if not any(pattern in full_url for pattern in excluded_patterns) and re.search(article_pattern, full_url):
                              all_article_links.add(full_url)
                              page_links_found += 1

            logging.info(f"Scraped {page_links_found} potential article links from {url}. Total unique links: {len(all_article_links)}")

            if page_links_found == 0 and page_num > 0:
                 logging.info("No new article links found on subsequent page using broader search. Assuming end of pagination.")
                 break


            # Introduce a delay between page requests
            time.sleep(request_delay)

            # Pagination logic remains based on page number and finding no new links

        except TimeoutException:
            logging.error(f"Timed out waiting for page to load at {url}. Skipping this page.")
            continue
        except NoSuchElementException:
            logging.warning(f"Could not find expected elements on {url}. Page structure might have changed or no articles. Skipping this page.")
            continue
        except WebDriverException as e:
             logging.critical(f"Selenium WebDriver critical error while processing {url}: {e}. Stopping.")
             break
        except Exception as e:
            logging.error(f"An unexpected error occurred while scraping links from {url}: {e}. Skipping this page.")
            continue


    logging.info(f"Finished collecting links. Found a total of {len(all_article_links)} unique article links.")

    # Now, scrape the content of each link
    article_data = []
    links_to_process = list(all_article_links)  # Convert set to list
    article_request_delay = 1 # Delay between article requests
    article_request_timeout = 20 # Timeout for article requests
    # num_articles_to_process = 15 # Increase the limit for processing articles - commented out to process all links

    logging.info(f"Starting article content scraping for {len(links_to_process)} links.")

    for i, link in enumerate(links_to_process): # Iterate through all links
        logging.info(f"Processing article link {i+1}/{len(links_to_process)}: {link}")
        try:
            article_response = requests.get(link, timeout=article_request_timeout)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.content, 'html.parser')

            # Extract Title (assuming h1 is still the main title)
            title_tag = article_soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else 'N/A'
            if title == 'N/A':
                logging.warning(f"Title not found for article: {link}")

            # Extract Author - Further refine author extraction based on manual inspection
            author = 'N/A'
            # Check existing selectors first
            author_tag = article_soup.find(class_='c-article-byline__name')
            if author_tag:
                 author = author_tag.get_text(strip=True)
            else:
                meta_author = article_soup.find('meta', {'name': 'author'})
                if meta_author and 'content' in meta_author.attrs:
                    author = meta_author['content']
                else:
                    # Based on manual inspection, authors might be in a specific span within a byline div
                    byline_div = article_soup.find('div', class_='c-article-byline')
                    if byline_div:
                        author_span = byline_div.find('span', class_='c-article-byline__name') # This is the same as the first selector, but good to be explicit within the structure
                        if author_span:
                            author = author_span.get_text(strip=True)
                        else:
                             # Look for other potential author elements within the byline div
                             other_author_element = byline_div.find('a', class_='u-hover-underline') # Example based on inspection
                             if other_author_element:
                                  author = other_author_element.get_text(strip=True)
                    # Add other potential author selectors here if identified from manual inspection

            if author == 'N/A':
                 logging.info(f"Author not found using specified selectors for article: {link}")


            # Extract Publication Date (assuming time tag with datetime attribute) - Added alternative selectors
            publication_date = 'N/A'
            date_tag = article_soup.find('time') # Existing selector
            if date_tag and 'datetime' in date_tag.attrs:
                publication_date = date_tag['datetime']
            else:
                # Try finding date in meta tags
                meta_pub_date = article_soup.find('meta', {'property': 'article:published_time'}) or \
                                article_soup.find('meta', {'name': 'pubdate'})
                if meta_pub_date and 'content' in meta_pub_date.attrs:
                    publication_date = meta_pub_date['content']
                else:
                    # Look for date in other potential elements (e.g., spans with date classes)
                    date_span = article_soup.find('span', class_='c-article-byline__date') # Example based on inspection
                    if date_span:
                        publication_date = date_span.get_text(strip=True)

            if publication_date == 'N/A':
                logging.warning(f"Publication date not found for article: {link}")


            # Extract Content - Refine content extraction logic with more selectors
            content = 'N/A'
            # Attempt the specific selector first
            content_paragraphs = article_soup.select('div.c-article-content > p')
            if content_paragraphs:
                 content = "\n".join([p.get_text(strip=True) for p in content_paragraphs])
            else:
                # Try a broader approach: find a main article body container
                article_body = article_soup.find('div', class_='c-article__body') # Example of a potential container class
                if article_body:
                    content_paragraphs = article_body.find_all('p')
                    if content_paragraphs:
                        content = "\n".join([p.get_text(strip=True) for p in content_paragraphs])
                else:
                    # Look for content within a more general article container if specific body class not found
                    general_article_container = article_soup.find('article')
                    if general_article_container:
                        content_paragraphs = general_article_container.find_all('p')
                        if content_paragraphs:
                            content = "\n".join([p.get_text(strip=True) for p in content_paragraphs])


            if content == 'N/A':
                logging.warning(f"Content not found using specified selectors for article: {link}")


            article_data.append({
                'url': link,
                'title': title,
                'author': author,
                'publication_date': publication_date,
                'content': content
            })

            logging.info(f"Successfully processed article: {link}")

            # Introduce a delay between article requests
            time.sleep(article_request_delay)


        except requests.exceptions.Timeout:
            logging.error(f"Request timed out for article {link}. Skipping.")
            continue
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching article {link}: {e}. Skipping.")
            continue
        except AttributeError as e:
            logging.error(f"Attribute error while processing article {link}: {e}. Missing element or unexpected structure. Skipping.")
            continue
        except TypeError as e:
            logging.error(f"Type error while processing article {link}: {e}. Data format issue. Skipping.")
            continue
        except Exception as e:
            logging.error(f"An unexpected error occurred while scraping links from {link}: {e}. Skipping.")
            continue


    # Store the scraped data in a pandas DataFrame
    df_articles = pd.DataFrame(article_data)
    if not df_articles.empty:
        logging.info(f"Successfully created DataFrame with {len(df_articles)} articles.")
        print(df_articles.head())
    else:
        logging.warning("No article data was successfully scraped to create a DataFrame.")


except Exception as e:
    logging.critical(f"A critical error occurred during the scraping process: {e}")

finally:
    if driver:
        driver.quit()
        logging.info("Selenium WebDriver closed.")