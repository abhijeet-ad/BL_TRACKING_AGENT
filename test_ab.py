import time
import tempfile
import streamlit as st
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
import json
import pandas as pd
import os
class TrackingAgent:
    def __init__(self):
        self.driver = None
        self.screenshot_counter = 0
        self.chrome_options = webdriver.ChromeOptions()
        self._configure_chrome_options()

    def _configure_chrome_options(self):
        """Enhanced configuration for headless mode"""
        # Common options
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        self.chrome_options.add_argument("--disable-infobars")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--log-level=3")
        self.chrome_options.add_argument("--silent")
        self.chrome_options.add_argument("--window-size=1920,1080")
        
        # Headless-specific options
        self.chrome_options.add_argument("--headless=new")  # New headless mode
        self.chrome_options.add_argument("--disable-gpu")
        
        # Mimic real user
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        self.chrome_options.add_argument(f"user-agent={user_agent}")
        
        # Experimental options
        self.chrome_options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)

    def init_browser(self):
        """Initialize browser with enhanced stealth"""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        
        # Override webdriver property
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {"
            "get: () => undefined,"
            "configurable: true"
            "})"
        )
        
        # Additional stealth parameters
        self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": self.chrome_options.arguments[-1].split('=', 1)[1]
        })
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
            '''
        })
    def _take_screenshot(self):
        """Helper method to capture screenshots"""
        if not self.driver:
            return None
        try:
            self.screenshot_counter += 1
            temp_file = tempfile.NamedTemporaryFile(prefix="maersk_", suffix=".png", delete=False)
            self.driver.save_screenshot(temp_file.name)
            return temp_file.name
        except Exception as e:
            print(f"Error taking screenshot: {str(e)}")
            return None

    def init_browser(self):
        """Initialize the Chrome browser with configured options"""
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def track_bl(self, bl_number):
        try:
            yield "Initializing browser...", None
            self.init_browser()

            tracking_url = f"https://www.maersk.com/tracking/#tracking/{bl_number}"
            yield f"Navigating to {tracking_url}", None
            self.driver.get(tracking_url)

            # First handle cookies
            yield "🍪 Handling cookies...", self._take_screenshot()
            self._accept_cookies()

            # Wait for main content or error
            yield "Loading tracking data...", self._take_screenshot()
            try:
                WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-test='track-content'], .error-message"))
                )
            except TimeoutException:
                yield "Timed out waiting for page to load", self._take_screenshot()
                return

            # Check for errors
            if self._has_errors():
                yield "Error loading tracking information", self._take_screenshot()
                return

            # Final data extraction
            final_screenshot = self._take_screenshot()
            yield "Extracting shipment data...", final_screenshot
            
            extracted_data = self.process_tracking_info()
            yield "Tracking complete!", final_screenshot
            yield extracted_data, None

        except Exception as e:
            screenshot = self._take_screenshot() if self.driver else None
            yield f"Error occurred: {str(e)}", screenshot
        finally:
            if self.driver:
                self.driver.quit()

    def _accept_cookies(self):
        """Improved cookie handling with multiple fallback selectors"""
        selectors = [
            ("css", "#onetrust-accept-btn-handler"),
            ("css", "button[data-test='coi-allow-all-button']"),
            ("xpath", "//button[contains(., 'Accept')]"),
            ("xpath", "//button[contains(., 'Agree')]")
        ]

        for selector_type, selector in selectors:
            try:
                if selector_type == "css":
                    button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                else:
                    button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector)))
                button.click()
                time.sleep(2)  # Wait for cookie dialog to close
                return
            except Exception:
                continue

    def _has_errors(self):
        """Check for error messages on the page"""
        try:
            return bool(self.driver.find_elements(By.CSS_SELECTOR, ".error-message, .notification--error"))
        except:
            return False

    def process_tracking_info(self):
        """Robust data extraction using BeautifulSoup"""
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        
        return {
            'bl_number': self._extract_value(soup, "[data-test='transport-doc-value']"),
            'container': self._extract_container_info(soup),
            'route': {
                'from': self._extract_value(soup, "[data-test='track-from-value']"),
                'to': self._extract_value(soup, "[data-test='track-to-value']")
            },
            'milestones': self._extract_milestones(soup),
            'last_updated': self._extract_value(soup, "[data-test='last-updated'] span")
        }

    def _extract_value(self, soup, selector):
        """Generic value extractor with safety"""
        try:
            return soup.select_one(selector).get_text(strip=True)
        except AttributeError:
            return None

    def _extract_container_info(self, soup):
        """Extract container details"""
        try:
            header = soup.select_one("[data-test^='container-header-']")
            return {
                'number': header.select_one(".mds-text--medium-bold").get_text(strip=True),
                'type': header.get_text().split('|')[-1].strip()
            }
        except AttributeError:
            return None

    def _extract_milestones(self, soup):
        """Extract shipping milestones"""
        milestones = []
        for item in soup.select("[data-test='transport-plan-list'] li"):
            try:
                milestones.append({
                    'location': self._clean_text(item.select_one("[data-test='location-name']")),
                    'status': self._clean_text(item.select_one("[data-test='milestone'] span")),
                    'date': self._clean_text(item.select_one("[data-test='milestone-date']")),
                    'vessel': self._extract_vessel_info(item)
                })
            except Exception as e:
                continue
        return milestones

    def _clean_text(self, element):
        """Clean and format text content"""
        return element.get_text(' ', strip=True).replace('\n', ' ') if element else None

    def _extract_vessel_info(self, item):
        """Extract vessel information from milestone"""
        try:
            text = item.select_one("[data-test='milestone']").get_text()
            if '(' in text:
                return text.split('(')[1].split(')')[0].strip()
        except:
            return None

def main():
    st.set_page_config(page_title="Maersk BL Tracker", layout="wide")
    st.title("Maersk BL Tracking Agent")

    # Initialize session state
    if 'tracking_results' not in st.session_state:
        st.session_state.tracking_results = []
    if 'processed' not in st.session_state:
        st.session_state.processed = False

    with st.sidebar:
        st.header("Live Process")
        current_bl_placeholder = st.empty()
        screenshot_placeholder = st.empty()
        status_placeholder = st.empty()

    # Use a form to separate processing from downloads
    with st.form("bl_tracking_form"):
        query_params = st.query_params
        default_bl = query_params.get("bl_numbers", [""])[0]
        bl_numbers_input = st.text_input("Enter BL numbers (comma-separated):", value=default_bl)
        submitted = st.form_submit_button("Start Tracking")

    if submitted and bl_numbers_input:
        # Reset results when new submission occurs
        st.session_state.tracking_results = []
        st.session_state.processed = False
        bl_numbers = [bl.strip() for bl in bl_numbers_input.split(',') if bl.strip()]
        
        main_placeholder = st.empty()
        processed_count = 0

        with main_placeholder.container():
            progress_bar = st.progress(0)
            overall_status = st.empty()
            result_containers = []

            for idx, bl_number in enumerate(bl_numbers):
                current_bl = bl_number
                agent = TrackingAgent()
                result_container = st.expander(f"Results for BL: {current_bl}", expanded=False)
                result_containers.append(result_container)
                
                with result_container:
                    process_text = st.empty()
                    extracted_data = None
                    error_occurred = False

                    for status, screenshot_path in agent.track_bl(current_bl):
                        if isinstance(status, dict):
                            extracted_data = status
                            break
                        with st.sidebar:
                            current_bl_placeholder.write(f"Current BL: {current_bl}")
                            status_placeholder.write(f"Status: {status}")
                            if screenshot_path:
                                screenshot_placeholder.image(screenshot_path, caption=f"Step {agent.screenshot_counter}")
                        process_text.write(f"**Process:** {status}")
                        time.sleep(0.5)

                    if extracted_data:
                        st.json(extracted_data)
                        st.session_state.tracking_results.append(extracted_data)
                    else:
                        st.error(f"Failed to track BL: {current_bl}")
                        st.session_state.tracking_results.append({"bl_number": current_bl, "error": "Tracking failed"})
                        error_occurred = True

                    processed_count += 1
                    progress = processed_count / len(bl_numbers)
                    progress_bar.progress(progress)
                    overall_status.write(f"Processed {processed_count} of {len(bl_numbers)} BL numbers")

            st.session_state.processed = True

    # Download buttons (outside the form)
    if st.session_state.processed and st.session_state.tracking_results:
        st.subheader("Download Results")
        
        # Create two columns for side-by-side buttons
        col1, col2 = st.columns(2)
        
        with col1:
            # JSON Download
            json_data = json.dumps(st.session_state.tracking_results, indent=2)
            st.download_button(
                label="Download JSON",
                data=json_data,
                file_name="maersk_tracking_results.json",
                mime="application/json"
            )

        with col2:
            # CSV Download
            csv_data = []
            for result in st.session_state.tracking_results:
                if 'error' in result:
                    continue  # Skip failed entries
                bl_number = result.get('bl_number', 'N/A')
                container = result.get('container', {}).get('number', 'N/A')
                route_from = result.get('route', {}).get('from', 'N/A')
                route_to = result.get('route', {}).get('to', 'N/A')
                last_updated = result.get('last_updated', 'N/A')
                for milestone in result.get('milestones', []):
                    csv_data.append({
                        'BL Number': bl_number,
                        'Container Number': container,
                        'From': route_from,
                        'To': route_to,
                        'Last Updated': last_updated,
                        'Location': milestone.get('location', 'N/A'),
                        'Status': milestone.get('status', 'N/A'),
                        'Date': milestone.get('date', 'N/A'),
                        'Vessel': milestone.get('vessel', 'N/A')
                    })

            if csv_data:
                df = pd.DataFrame(csv_data)
                csv_string = df.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv_string,
                    file_name="maersk_tracking_results.csv",
                    mime="text/csv"
                )

    elif not bl_numbers_input:
        st.warning("🔍 Add BL numbers in the format: 123456789,987654321")

if __name__ == "__main__":
    main()
