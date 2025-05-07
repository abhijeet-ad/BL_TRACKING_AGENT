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
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options


class TrackingAgent:
    def __init__(self):
        self.driver = None
        self.screenshot_counter = 0
        self.chrome_options = webdriver.ChromeOptions()
        self._configure_chrome_options()

    def _configure_chrome_options(self):
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        self.chrome_options.add_argument("--disable-infobars")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--log-level=3")
        self.chrome_options.add_argument("--silent")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--disable-gpu")

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        self.chrome_options.add_argument(f"user-agent={user_agent}")

        self.chrome_options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
        self.chrome_options.add_experimental_option('useAutomationExtension', False)

    def init_browser(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            "userAgent": self.chrome_options.arguments[-1].split('=', 1)[1]
        })
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            '''
        })

    def _take_screenshot(self):
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

    def track_bl(self, bl_number):
        try:
            yield "Initializing browser...", None
            self.init_browser()

            tracking_url = f"https://www.maersk.com/tracking/#tracking/{bl_number}"
            yield f"Navigating to {tracking_url}", None
            self.driver.get(tracking_url)

            yield "🍪 Handling cookies...", self._take_screenshot()
            self._accept_cookies()

            yield "Loading tracking data...", self._take_screenshot()
            try:
                WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-test='track-content'], .error-message"))
                )
            except TimeoutException:
                yield "Timed out waiting for page to load", self._take_screenshot()
                return

            if self._has_errors():
                yield "Error loading tracking information", self._take_screenshot()
                return

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
                time.sleep(2)
                return
            except Exception:
                continue

    def _has_errors(self):
        try:
            return bool(self.driver.find_elements(By.CSS_SELECTOR, ".error-message, .notification--error"))
        except:
            return False

    def process_tracking_info(self):
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
        try:
            return soup.select_one(selector).get_text(strip=True)
        except AttributeError:
            return None

    def _extract_container_info(self, soup):
        try:
            header = soup.select_one("[data-test^='container-header-']")
            return {
                'number': header.select_one(".mds-text--medium-bold").get_text(strip=True),
                'type': header.get_text().split('|')[-1].strip()
            }
        except AttributeError:
            return None

    def _extract_milestones(self, soup):
        milestones = []
        for item in soup.select("[data-test='transport-plan-list'] li"):
            try:
                milestones.append({
                    'location': self._clean_text(item.select_one("[data-test='location-name']")),
                    'status': self._clean_text(item.select_one("[data-test='milestone'] span")),
                    'date': self._clean_text(item.select_one("[data-test='milestone-date']")),
                    'vessel': self._extract_vessel_info(item)
                })
            except Exception:
                continue
        return milestones

    def _clean_text(self, element):
        return element.get_text(' ', strip=True).replace('\n', ' ') if element else None

    def _extract_vessel_info(self, item):
        try:
            text = item.select_one("[data-test='milestone']").get_text()
            if '(' in text:
                return text.split('(')[1].split(')')[0].strip()
        except:
            return None


def main():
    st.set_page_config(page_title="Maersk BL Tracker", layout="wide")
    st.title("Maersk BL Tracking Agent")

    if 'tracking_results' not in st.session_state:
        st.session_state.tracking_results = []
    if 'processed' not in st.session_state:
        st.session_state.processed = False

    with st.sidebar:
        st.header("Live Process")
        current_bl_placeholder = st.empty()
        screenshot_placeholder = st.empty()
        status_placeholder = st.empty()

    with st.form("bl_tracking_form"):
        query_params = st.query_params
        default_bl = query_params.get("bl_numbers", [""])[0]
        bl_numbers_input = st.text_input("Enter BL numbers (comma-separated):", value=default_bl)
        submitted = st.form_submit_button("Start Tracking")

    if submitted and bl_numbers_input:
        st.session_state.tracking_results = []
        st.session_state.processed = False
        bl_numbers = [bl.strip() for bl in bl_numbers_input.split(',') if bl.strip()]
        
        main_placeholder = st.empty()
        processed_count = 0

        with main_placeholder.container():
            progress_bar = st.progress(0)
            result_containers = []

            for idx, bl_number in enumerate(bl_numbers):
                agent = TrackingAgent()
                result_container = st.expander(f"Results for BL: {bl_number}", expanded=False)
                result_containers.append(result_container)
                with result_container:
                    process_text = st.empty()
                    extracted_data = None

                    for status, screenshot_path in agent.track_bl(bl_number):
                        if isinstance(status, dict):
                            extracted_data = status
                            break
                        with st.sidebar:
                            current_bl_placeholder.write(f"Current BL: {bl_number}")
                            status_placeholder.write(f"Status: {status}")
                            if screenshot_path:
                                screenshot_placeholder.image(screenshot_path, caption=f"Step {agent.screenshot_counter}")
                        process_text.write(f"**Process:** {status}")
                        time.sleep(0.5)

                    if extracted_data:
                        st.json(extracted_data)
                        st.session_state.tracking_results.append(extracted_data)
                    else:
                        st.error(f"Failed to track BL: {bl_number}")
                        st.session_state.tracking_results.append({"bl_number": bl_number, "error": "Tracking failed"})

                    processed_count += 1
                    progress = processed_count / len(bl_numbers)
                    progress_bar.progress(progress)

        st.success("🎉 All BLs processed!")
        st.session_state.processed = True


if __name__ == "__main__":
    main()
