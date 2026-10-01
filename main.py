import os
import sys
import json
import time
import signal
import shutil
import sqlite3
import logging
import argparse
import tempfile
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Set, Tuple

# Windows consoles default to a legacy codepage (e.g. cp1252) that cannot encode
# the Persian strings used throughout this script. Force UTF-8 so --help, logs and
# console output do not raise UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('karlancer_monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def cleanup_previous_sessions():
    """Kill any remaining Chrome/chromedriver processes and clean temp directories"""
    try:
        # exec with an argument array (no shell), so no shell metacharacter can
        # be interpreted. Silently skipped on platforms without pkill.
        for pattern in ("chrome", "chromedriver"):
            try:
                subprocess.run(["pkill", "-f", pattern], check=False)
            except FileNotFoundError:
                logger.debug("pkill not available on this platform; skipping")
                break

        temp_dir = tempfile.gettempdir()
        for item in os.listdir(temp_dir):
            # Only touch directories this bot itself creates (chrome_<pid>_<ts>)
            if item.startswith("chrome_") and os.path.isdir(os.path.join(temp_dir, item)):
                try:
                    shutil.rmtree(os.path.join(temp_dir, item), ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Error cleaning {item}: {str(e)}")

        logger.info("Previous sessions cleaned up successfully")
    except Exception as e:
        logger.warning(f"Cleanup error: {str(e)}")

class KarlancerAuth:
    """Handles authentication with karlancer.com"""
    
    def __init__(self, debug: bool = False):
        self.driver: Optional[webdriver.Chrome] = None
        self.debug = debug
        self.base_url = "https://www.karlancer.com"
        self.init_db()

    def init_db(self) -> None:
        """Initialize database for token storage"""
        try:
            with sqlite3.connect('karlancer.db') as conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS tokens
                             (id INTEGER PRIMARY KEY, 
                              auth_token TEXT,
                              user_data TEXT,
                              expires_at TEXT)''')
            logger.debug("Database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            raise

    def save_tokens(self, tokens: Dict[str, Any]) -> None:
        """Save tokens to database"""
        try:
            expires_at = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect('karlancer.db') as conn:
                c = conn.cursor()
                c.execute("DELETE FROM tokens")
                c.execute("INSERT INTO tokens VALUES (1, ?, ?, ?)",
                         (tokens['auth-token'],
                          tokens.get('user.data', ''),
                          expires_at))
            logger.info("Tokens saved to database successfully")
        except Exception as e:
            logger.error(f"Failed to save tokens: {str(e)}")
            raise

    def get_tokens(self) -> Optional[Dict[str, Any]]:
        """Retrieve tokens from database"""
        try:
            with sqlite3.connect('karlancer.db') as conn:
                c = conn.cursor()
                c.execute("SELECT auth_token, user_data, expires_at FROM tokens WHERE id=1")
                row = c.fetchone()
            
            if not row:
                logger.debug("No tokens found in database")
                return None
                
            logger.debug("Tokens retrieved from database")
            return {
                'auth-token': row[0],
                'user.data': row[1],
                'expires_at': row[2]
            }
        except Exception as e:
            logger.error(f"Failed to retrieve tokens: {str(e)}")
            return None

    def init_driver(self) -> webdriver.Chrome:
        """Initialize the WebDriver with unique user data directory"""
        if self.driver is not None:
            return self.driver
            
        options = Options()
        
        # Essential settings for VPS
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # NOTE: no --remote-debugging-port. It was set to 9222 but nothing ever
        # connected to it, and a fixed port lets any local process drive the
        # authenticated browser session. Leave it off unless needed.

        # Create unique temp directory
        user_data_dir = os.path.join(tempfile.gettempdir(), f"chrome_{os.getpid()}_{int(time.time())}")
        os.makedirs(user_data_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir}")

        # Detection evasion: the site this bot targets blocks obvious automation,
        # so the following hide WebDriver's fingerprints. This is deliberate and
        # documented in the README -- not an oversight. See the README
        # "Detection evasion" section for the tradeoff.
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        if not self.debug:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--blink-settings=imagesEnabled=false")

        try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = webdriver.Chrome(
                        service=Service(
                            ChromeDriverManager().install(),
                            service_args=['--verbose'],
                            log_path='chromedriver.log'
                        ),
                        options=options
                    )
                    
                    self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                    })
                    
                    logger.info("WebDriver initialized successfully")
                    return self.driver
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(2)
                    continue
                    
        except Exception as e:
            shutil.rmtree(user_data_dir, ignore_errors=True)
            logger.error(f"Failed to initialize WebDriver: {str(e)}")
            raise

    def close_driver(self) -> None:
        """Close the WebDriver and clean up"""
        if self.driver is not None:
            try:
                user_data_dir = None
                try:
                    with open('chromedriver.log', 'r') as f:
                        for line in f:
                            if 'user-data-dir' in line:
                                user_data_dir = line.split('user-data-dir=')[1].strip()
                                break
                except Exception as e:
                    logger.warning(f"Error reading chromedriver.log: {str(e)}")
                
                self.driver.quit()
                
                if user_data_dir and os.path.exists(user_data_dir):
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                    logger.info(f"Cleaned up user data directory: {user_data_dir}")
                    
            except Exception as e:
                logger.error(f"Error closing driver: {str(e)}")
            finally:
                self.driver = None

    def manual_login(self) -> Dict[str, Any]:
        """Manual login and token extraction"""
        try:
            self.init_driver()
            self.driver.get(f"{self.base_url}/login")
            input("After manual login, press Enter...")

            WebDriverWait(self.driver, 30).until(
                lambda d: "dashboard" in d.current_url.lower()
            )

            tokens: Dict[str, Any] = {
                'auth-token': self.driver.execute_script("return localStorage.getItem('auth-token')"),
                'user.data': self.driver.execute_script("return localStorage.getItem('user.data')"),
            }

            if not tokens['auth-token']:
                raise ValueError("auth-token not found in localStorage after login")

            logger.info("Manual login successful")
            return tokens
        except Exception as e:
            logger.error(f"Manual login failed: {str(e)}")
            raise

    def set_localstorage(self) -> bool:
        """Set tokens from database to localStorage"""
        try:
            tokens = self.get_tokens()
            if not tokens or datetime.now() > datetime.strptime(tokens['expires_at'], "%Y-%m-%d %H:%M:%S"):
                logger.warning("Tokens expired or not found")
                return False

            self.init_driver()
            self.driver.get(f"{self.base_url}")

            script = f"""
                localStorage.setItem('auth-token', {json.dumps(tokens['auth-token'])});
                localStorage.setItem('user.data', {json.dumps(tokens['user.data'])});
            """
            self.driver.execute_script(script)
            time.sleep(2)
            self.driver.refresh()
            logger.info("Tokens set in localStorage successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to set localStorage tokens: {str(e)}")
            return False

    def auth(self) -> bool:
        """Main authentication method"""
        try:
            if self.get_tokens():
                logger.info("Tokens loaded from database")
                if self.set_localstorage():
                    logger.info("Authentication successful using stored tokens")
                    return True

            logger.info("Manual login required")
            tokens = self.manual_login()
            self.save_tokens(tokens)
            logger.info("Authentication completed successfully")
            return True
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            return False

    def reconnect(self) -> bool:
        """Reconnect the browser session"""
        try:
            self.close_driver()
            if not self.auth():
                return False
            logger.info("Reconnected successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to reconnect: {str(e)}")
            return False

class KarlancerProjectMonitor:
    """Monitors new projects on karlancer.com"""
    
    def __init__(self, auth: KarlancerAuth, search_term: str = "", refresh_interval: int = 20):
        self.auth = auth
        self.search_term = search_term
        self.refresh_interval = refresh_interval
        self.base_url = "https://www.karlancer.com"
        self.previous_projects: Set[Tuple[str, str]] = set()
        self.descriptions_file = "descriptions.txt"
        logger.info(f"Project monitor initialized with search term: '{search_term}'")

    def load_descriptions(self) -> list:
        """Load proposal descriptions from text file"""
        try:
            with open(self.descriptions_file, 'r', encoding='utf-8-sig') as f:
                full_text = f.read().strip()
                if not full_text:
                    raise ValueError("Description file is empty")
                logger.debug("Descriptions loaded successfully")
                return [full_text]
        except Exception as e:
            logger.error(f"Could not load descriptions: {str(e)}")
            raise

    def parse_persian_time(self, time_str: str) -> timedelta:
        """Parse Persian time string into timedelta"""
        try:
            time_str = time_str.strip()
            
            if "ثانیه" in time_str:  # seconds
                seconds = int(''.join(filter(str.isdigit, time_str)))
                return timedelta(seconds=seconds)
            elif "دقیقه" in time_str:  # minutes
                minutes = int(''.join(filter(str.isdigit, time_str)))
                return timedelta(minutes=minutes)
            elif "ساعت" in time_str:  # hours
                hours = int(''.join(filter(str.isdigit, time_str)))
                return timedelta(hours=hours)
            elif "روز" in time_str:  # days
                days = int(''.join(filter(str.isdigit, time_str)))
                return timedelta(days=days)
            else:
                return timedelta.max
        except Exception as e:
            logger.warning(f"Could not parse Persian time '{time_str}': {str(e)}")
            return timedelta.max

    def _wait_for_page_load(self, driver: webdriver.Chrome, timeout=30):
        """Wait for page to fully load"""
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            time.sleep(1)
            logger.debug("Page loaded successfully")
        except Exception as e:
            logger.warning(f"Page load wait failed: {str(e)}")

    def start_monitoring(self) -> None:
        """Start the monitoring process"""
        logger.info("Starting monitoring process")
        if not self._ensure_authenticated():
            raise Exception("Failed to authenticate")

        driver = self.auth.driver
        if not driver:
            raise Exception("WebDriver not initialized")

        try:
            while True:
                try:
                    driver.get(f"{self.base_url}/search/")
                    self._wait_for_page_load(driver)

                    self._apply_search_filter(driver)
                    self._wait_for_page_load(driver)

                    current_projects = self._get_recent_projects(driver)
                    self._process_new_projects(current_projects)

                    logger.info(f"Waiting {self.refresh_interval} seconds before next check")
                    time.sleep(self.refresh_interval)

                except KeyboardInterrupt:
                    logger.info("Monitoring stopped by user")
                    break
                except Exception as e:
                    logger.error(f"Error occurred during monitoring: {str(e)}")
                    if not self._handle_error():
                        break
        finally:
            logger.info("Monitoring process ended")

    def _ensure_authenticated(self) -> bool:
        """Ensure we're authenticated"""
        if not self.auth.auth():
            logger.error("Authentication failed")
            return False
        logger.info("Authentication verified")
        return True

    def _apply_search_filter(self, driver: webdriver.Chrome) -> None:
        """Apply the search term filter"""
        try:
            self._wait_for_page_load(driver)
            
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, '//input[@type="text"]'))
            )
            
            try:
                search_input = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, 
                        '//input[contains(@placeholder, "جستجو") or contains(@placeholder, "search")]'))
                )
                search_input.clear()
                search_input.send_keys(self.search_term)
                search_input.send_keys(Keys.RETURN)
            except:
                inputs = driver.find_elements(By.XPATH, '//input[@type="text"]')
                for input_field in inputs:
                    try:
                        if input_field.is_displayed() and input_field.is_enabled():
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_field)
                            input_field.clear()
                            input_field.send_keys(self.search_term)
                            input_field.send_keys(Keys.RETURN)
                            break
                    except:
                        continue
            
            try:
                # The search term is passed as a script argument rather than
                # interpolated into the source, so a term containing quotes or
                # newlines cannot inject arbitrary JavaScript into the page.
                driver.execute_script("""
                    const term = arguments[0];
                    let inputs = document.querySelectorAll('input[type="text"]');
                    for (let input of inputs) {
                        if (input.placeholder && (input.placeholder.includes('جستجو') || input.placeholder.includes('search'))) {
                            input.value = term;
                            input.dispatchEvent(new Event('input'));
                            let form = input.closest('form');
                            if (form) {
                                form.submit();
                            } else {
                                let event = new KeyboardEvent('keydown', {'key': 'Enter'});
                                input.dispatchEvent(event);
                            }
                            break;
                        }
                    }
                """, self.search_term)
            except Exception as js_error:
                logger.warning(f"JavaScript fallback failed: {str(js_error)}")
            
            logger.info(f"Applied search filter: '{self.search_term}'")
            time.sleep(3)
            
            try:
                current_url = driver.current_url
                if "search" in current_url or "جستجو" in current_url:
                    logger.debug("Search filter successfully applied")
                else:
                    logger.warning("Search may not have been applied - checking results anyway")
            except:
                pass
                
        except Exception as e:
            logger.error(f"Failed to apply search filter: {str(e)}")
            driver.save_screenshot("search_error.png")
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            raise

    def _get_recent_projects(self, driver: webdriver.Chrome) -> Set[Tuple[str, str, str, str, str]]:
        """Get filtered projects that match our search term"""
        try:
            page_text = driver.page_source
            if self.search_term and self.search_term not in page_text:
                logger.warning(f"Search term '{self.search_term}' not found in results")
            
            projects = WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.XPATH, 
                    '//div[contains(@class, "bg-white") and contains(@class, "br-9") and contains(@class, "p-30-20")]'))
            )

            current_projects = set()
            max_age = timedelta(minutes=7)
            
            for project in projects:
                try:
                    try:
                        project.find_element(By.XPATH, './/div[contains(@id, "setBidBtn")]')
                    except:
                        continue

                    title_element = project.find_element(By.XPATH, './/a[contains(@class, "max-w-100p-120")]')
                    title = title_element.text.strip()
                    link = title_element.get_attribute("href")
                    if not link.startswith('http'):
                        link = self.base_url + link

                    time_element = project.find_element(By.XPATH, './/span[contains(@class, "fs-13") and contains(@class, "text-nowrap")]')
                    time_str = time_element.text.strip()
                    age = self.parse_persian_time(time_str)

                    budget = "Not specified"
                    time_suggested = "Not specified"

                    try:
                        budget_label = project.find_element(By.XPATH, './/span[contains(text(), "بودجه")]')
                        budget_value = budget_label.find_element(By.XPATH, 
                            './following-sibling::div[contains(@class, "fs-16") and contains(@class, "b-900")]')
                        budget = budget_value.text.strip()

                        time_label = project.find_element(By.XPATH, './/span[contains(text(), "زمان پیشنهادی")]')
                        time_value = time_label.find_element(By.XPATH,
                            './following-sibling::div[contains(@class, "fs-16") and contains(@class, "b-900")]')
                        time_suggested = time_value.text.strip()
                    except:
                        try:
                            details = project.find_elements(By.XPATH, 
                                './/div[contains(@class, "fs-16") and contains(@class, "b-900") and contains(@class, "mr-2")]')
                            if len(details) >= 2:
                                budget = details[0].text.strip()
                                time_suggested = details[1].text.strip()
                        except:
                            pass

                    if age <= max_age:
                        current_projects.add((title, link, str(age), budget, time_suggested))
                        logger.info(f"Found project: {title[:50]}... | Age: {age} | Budget: {budget} | Time: {time_suggested}")

                except Exception as e:
                    logger.warning(f"Skipping project due to error: {str(e)[:100]}...")
                    continue

            return current_projects

        except Exception as e:
            logger.error(f"Failed to fetch projects: {str(e)}")
            raise

    def _process_new_projects(self, current_projects: Set[Tuple[str, str, str, str, str]]) -> None:
        """Process and display new projects"""
        try:
            descriptions = self.load_descriptions()
            current_projects_set = {(title, link) for title, link, age, budget, time_suggested in current_projects}
            new_projects = current_projects_set - self.previous_projects

            if new_projects:
                logger.info(f"Found {len(new_projects)} new projects")
                for title, link, age, budget, time_suggested in current_projects:
                    if (title, link) in new_projects:
                        logger.info(f"Processing new project: {title}")
                        logger.info(f"Details - Age: {age}, Budget: {budget}, Time: {time_suggested}")

                        self.auth.driver.get(link)
                        self._wait_for_page_load(self.auth.driver)
                        
                        try:
                            detailed_budget = "Not specified"
                            min_budget = max_budget = 0
                            try:
                                budget_container = WebDriverWait(self.auth.driver, 10).until(
                                    EC.presence_of_element_located((By.XPATH, '//div[contains(@class, "d-flex") and contains(@class, "align-items-center") and contains(., "بودجه")]'))
                                )
                                detailed_budget = budget_container.text.strip()
                                logger.info(f"Detailed Budget Info: {detailed_budget}")
                                
                                numbers = [int(''.join(filter(str.isdigit, part))) 
                                        for part in detailed_budget.split() 
                                        if any(c.isdigit() for c in part)]
                                if len(numbers) >= 2:
                                    min_budget = numbers[0]
                                    max_budget = numbers[1]
                                elif numbers:
                                    min_budget = max_budget = numbers[0]
                            except Exception as e:
                                logger.warning(f"Could not extract detailed budget info: {str(e)}")
                                numbers = [int(''.join(filter(str.isdigit, part))) 
                                        for part in budget.split() 
                                        if any(c.isdigit() for c in part)]
                                if numbers:
                                    min_budget = max_budget = numbers[0]

                            bid_button = WebDriverWait(self.auth.driver, 15).until(
                                EC.element_to_be_clickable((By.XPATH, '//div[contains(@class, "blue-box") and contains(@id, "setBidBtn")]'))
                            )
                            bid_button.click()
                            logger.info("Clicked on project bid button")
                            time.sleep(2)
                            
                            try:
                                dont_show_button = WebDriverWait(self.auth.driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, '//button[contains(., "دیگر این پیام را به من نشان نده")]'))
                                )
                                dont_show_button.click()
                                logger.info("Clicked on 'don't show again' button")
                                time.sleep(1)
                            except:
                                pass
                            
                            try:
                                portfolio_warning = WebDriverWait(self.auth.driver, 5).until(
                                    EC.presence_of_element_located((By.XPATH, '//div[contains(., "شما نمونه‌کار مرتبط با این پروژه ندارید")]'))
                                )
                                dont_show_again = WebDriverWait(self.auth.driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, '//span[contains(., "دیگر نشانم نده")]'))
                                )
                                dont_show_again.click()
                                logger.info("Clicked on portfolio warning 'don't show again'")
                                
                                continue_button = WebDriverWait(self.auth.driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, '//button[contains(., "ادامه و ثبت پیشنهاد")]'))
                                )
                                continue_button.click()
                                logger.info("Clicked on continue button")
                                time.sleep(2)
                            except:
                                pass
                            
                            try:
                                if time_suggested != "Not specified":
                                    try:
                                        original_days = int(''.join(filter(str.isdigit, time_suggested)))
                                        suggested_days = max(1, original_days // 2)
                                        time_input = WebDriverWait(self.auth.driver, 10).until(
                                            EC.presence_of_element_located((By.XPATH, '//input[contains(@placeholder, "تعداد روز") or contains(@placeholder, "مدت انجام")]'))
                                        )
                                        time_input.clear()
                                        time_input.send_keys(str(suggested_days))
                                        logger.info(f"Set time: {suggested_days} days (original: {original_days} days)")
                                    except Exception as e:
                                        logger.warning(f"Could not set time: {str(e)}")
                                
                                if min_budget > 0 and max_budget > 0:
                                    suggested_price = (min_budget + max_budget) // 2
                                    price_input = WebDriverWait(self.auth.driver, 10).until(
                                        EC.presence_of_element_located((By.XPATH, '//input[contains(@placeholder, "قیمت") or contains(@placeholder, "مبلغ")]'))
                                    )
                                    price_input.clear()
                                    price_input.send_keys(str(suggested_price))
                                    logger.info(f"Set price: {suggested_price:,} (range: {min_budget:,}-{max_budget:,})")
                                else:
                                    logger.warning("Could not determine budget range for pricing")
                                
                                description_area = WebDriverWait(self.auth.driver, 10).until(
                                    EC.presence_of_element_located((By.XPATH, '//textarea[contains(@placeholder, "توضیح‌دهید")]'))
                                )
                                description_area.clear()
                                description_area.send_keys(descriptions[0])
                                logger.info("Added proposal description")
                                
                                submit_button = WebDriverWait(self.auth.driver, 10).until(
                                    EC.element_to_be_clickable((By.XPATH, '//button[@id="submitBid"]'))
                                )
                                submit_button.click()
                                logger.info("Proposal submitted successfully")
                                time.sleep(3)
                                
                                try:
                                    upgrade_modal = WebDriverWait(self.auth.driver, 5).until(
                                        EC.presence_of_element_located((By.XPATH, '//div[contains(@class, "overflow-hidden") and contains(., "می‌دونستی فقط با ۲۰هزار تومان")]'))
                                    )
                                    no_upgrade_button = WebDriverWait(upgrade_modal, 5).until(
                                        EC.element_to_be_clickable((By.XPATH, './/div[contains(@class, "bg-primary-color") and contains(., "ثبت پیشنهاد بدون ارتقا")]')))
                                    no_upgrade_button.click()
                                    logger.info("Clicked on 'submit without upgrade' button")
                                    time.sleep(2)
                                except:
                                    logger.debug("No upgrade offer modal appeared")

                                try:
                                    success_message = WebDriverWait(self.auth.driver, 5).until(
                                        EC.presence_of_element_located((By.XPATH, '//div[contains(., "پیشنهاد شما با موفقیت ثبت شد")]'))
                                    )
                                    logger.info("Proposal confirmation received")
                                except:
                                    logger.warning("Could not verify proposal submission")
                                
                            except Exception as e:
                                logger.error(f"Failed to submit proposal: {str(e)}")
                                self.auth.driver.save_screenshot("proposal_error.png")
                                
                        except Exception as e:
                            logger.error(f"Failed to process project: {str(e)}")
                            self.auth.driver.save_screenshot("project_error.png")

            else:
                logger.debug("No new projects found")

            self.previous_projects = current_projects_set
        except Exception as e:
            logger.error(f"Error processing new projects: {str(e)}")
            raise

    def _handle_error(self) -> bool:
        """Handle errors and attempt recovery"""
        logger.warning("Attempting to recover from error")
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            self.auth.driver.save_screenshot(f"error_{timestamp}.png")
            self.auth.driver.refresh()
            time.sleep(5)
            return True
        except:
            if not self.auth.reconnect():
                logger.error("Failed to recover connection")
                return False
            return True

def handle_interrupt(signum, frame):
    logger.info("Received interrupt signal, shutting down...")
    sys.exit(0)

def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="karbot - auto-bidding bot for karlancer.com")
    parser.add_argument("-s", "--search-term", default="طراحی سایت",
                        help="Keyword to filter projects by (default: %(default)s)")
    parser.add_argument("-i", "--interval", type=int, default=300,
                        help="Seconds between checks (default: %(default)s)")
    parser.add_argument("--headless", action="store_true",
                        help="Run Chrome without a visible window (for VPS/servers)")
    return parser.parse_args()

if __name__ == "__main__":
    # Parse before any side effects so --help / bad flags exit cleanly
    # instead of running cleanup and closing a driver that never started.
    args = parse_args()
    auth: Optional[KarlancerAuth] = None
    try:
        cleanup_previous_sessions()

        auth = KarlancerAuth(debug=not args.headless)
        monitor = KarlancerProjectMonitor(auth,
                                          search_term=args.search_term,
                                          refresh_interval=args.interval)

        signal.signal(signal.SIGINT, handle_interrupt)
        signal.signal(signal.SIGTERM, handle_interrupt)

        monitor.start_monitoring()

    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
    finally:
        if auth is not None:
            auth.close_driver()
        cleanup_previous_sessions()