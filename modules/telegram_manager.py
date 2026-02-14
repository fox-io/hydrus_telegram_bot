import re
from urllib.parse import urlparse
import urllib.parse
from wand.image import Image
import os
import requests
import math
from requests.adapters import HTTPAdapter
from requests.exceptions import ReadTimeout, ConnectionError, RequestException
from urllib3.util.retry import Retry
from modules.log_manager import LogManager
from modules.file_manager import FileManager
import json
import time

class TelegramManager:
    """
    TelegramManager handles communication with the Telegram bot.

    Attributes:
        logger (Logger): The logger for the TelegramManager.
        config (ConfigManager): The configuration settings for the bot.
        files (FileManager): The file manager for the bot.
        token (str): The Telegram bot access token.

    Methods:
        build_telegram_api_url(method, payload, is_file): Constructs a Telegram API url for bot communication.
        concatenate_sauce(known_urls): Return source URLs.
        replace_html_entities(tag): Replace HTML entities in tags.
        build_caption_buttons(caption): Assembles buttons to display under the Telegram post.
        reduce_image_size(path): Telegram has limits on image file size and dimensions. We resize large things here.
        get_message_markup(image): Build the message markup for the Telegram post.
        api_request(api_call, payload, image, path): Send messages or images to Telegram bot.
        send_message(message): Sends a message to all admin users.
        send_image(api_call, image, path): Attempt to send the image to our Telegram bot.
    """
    subreddit_regex = "/(r/[a-z0-9][_a-z0-9]{2,20})/"

    def __init__(self, config):
        """
        Initializes the TelegramManager object.

        Args:
            config (ConfigManager): The configuration settings for the bot.
        """
        self.logger = LogManager.setup_logger('TEL')
        self.config = config.config_data
        self.files = FileManager()
        if not self.config.telegram_access_token:
            self.logger.error('No Telegram token was provided.')
            return
        self.token = self.config.telegram_access_token
        self.polling_session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.polling_session.mount("https://", adapter)
        self.polling_session.mount("http://", adapter)
        self.logger.debug('Telegram Module initialized.')

    def build_telegram_api_url(self, method: str, payload: str, is_file: bool = False):
        """
        Constructs a Telegram API url for bot communication.

        Args:
            method (str): The method to call in the Telegram API.
            payload (str): The payload to send to the Telegram API.
            is_file (bool): True if the payload is a file.

        Returns:
            str: The Telegram API url
        """
        url = f"https://api.telegram.org/{'file/' if is_file else ''}bot{self.token}"
        if not is_file and method:
            url += f"/{method}"
        if payload:
            url += f"?{payload.lstrip('?')}" # Make sure payload starts with a ?.
        return url


    # noinspection PyMethodMayBeStatic
    def concatenate_sauce(self, known_urls: list):
        """
        Joins source URLs.

        Args:
            known_urls (list): A list of URLs to combine.

        Returns:
            str: A comma-separated list of source URLs.
        """
        # Return source URLs.
        sauce = ''
        for url in known_urls:
            # Skip direct links.
            if url.startswith("https://www.") or url.startswith("https://e621.net/posts"):
                sauce = sauce + url + ','
        return sauce

    def replace_html_entities(self, tag: str):
        """
        Replace problematic HTML entities in tags.

        Args:
            tag (str): The tag to clean.

        Returns:
            str: The cleaned tag.
        """
        tag = tag.replace("&", "+")
        tag = tag.replace("<", "≺")
        tag = tag.replace(">", "≻")
        return tag

    def build_caption_buttons(self, caption: str):
        """
        Assembles buttons to display under the Telegram post.

        Args:
            caption (str): The caption to parse.

        Returns:
            dict: The keyboard for the Telegram post.
        """
        if caption is not None:
            keyboard = {'inline_keyboard': []}
            url_column = 0
            url_row = -1
            for line in caption.split(','):
                if 'http' in line:
                    link = urlparse(line)
                    skip_link = False

                    # Pretty print known site names.
                    if 'furaffinity' in link.netloc:
                        website = 'Furaffinity'

                        if 'user' in link.path:
                            skip_link = True

                        # Check if the link is dead on Furaffinity.
                        fa_url = link.geturl()
                        try:
                            response = requests.get(fa_url, timeout=10)
                            if "The submission you are trying to find is not in our database." in response.text:
                                skip_link = True
                        except requests.exceptions.RequestException as e:
                            self.logger.error(f"An error occurred when checking the Furaffinity link: {e}")
                    elif 'e621' in link.netloc:
                        website = 'e621'
                    elif 'reddit' in link.netloc:
                        subreddit_match = re.search(self.subreddit_regex, link.geturl(), re.IGNORECASE)
                        website = 'Reddit (' + subreddit_match.group(1) + ')' if subreddit_match else 'Reddit'
                    else:
                        website = link.netloc

                    # Only add the button if the link is not dead.
                    if not skip_link:
                        if url_column == 0:
                            keyboard['inline_keyboard'].append([])
                            url_row += 1
                        url = link.geturl()
                        keyboard['inline_keyboard'][url_row].append({
                            'text': website,
                            'url': url
                        })
                        url_column = url_column == 0 and 1 or 0
            return keyboard
        else:
            return None

    def reduce_image_size(self, path):
        """
        Reduces image filesize and dimensions as needed for Telegram compatability.

        Args:
            path (str): The path to the image file.

        Returns:
            None

        Raises:
            Exception: Could not open the image.
        """
        try:
            img = Image(filename=path)

            # Wand can return None for unknown formats; guard before lower()
            img_format = img.format.lower() if img.format else None
            if img_format not in ["jpeg", "jpg", "png", "gif"]:
                self.logger.warning(f"Skipping resize: Unsupported format {img.format}")
                return

            if img.width > self.config.max_image_dimension or img.height > self.config.max_image_dimension:
                img.transform(resize='1024x768')
                img.save(filename=path)

            if os.path.getsize(path) > self.config.max_file_size:
                size_ratio = os.path.getsize(path) / self.config.max_file_size
                img.resize(round(img.width / math.sqrt(size_ratio)), round(img.height / math.sqrt(size_ratio)))
                img.save(filename=path)
        except Exception as e:
            self.logger.error(f"Could not open the image: {e}")

    def get_message_markup(self, image):
        """
        Build the message markup for the Telegram post.

        Args:
            image (dict): The image data to post.

        Returns:
            str: The message markup for the Telegram post.
        """
        message_markup = ''

        # Sauce Buttons
        sauce = self.build_caption_buttons(image['sauce']) if "sauce" in image else None
        if sauce:
            # URL-encode the JSON to prevent "can't parse reply keyboard markup" errors
            message_markup = message_markup + '&reply_markup=' + urllib.parse.quote(json.dumps(sauce))
        # Caption Text
        caption_parts = []
        #     Title
        if "title" in image and image["title"]:
            caption_parts.append('Title(s):\n' + str(image['title']))
        #     Creator
        if "creator" in image and image["creator"]:
            caption_parts.append('Uploader:\n' + str(image['creator']))
        #     Character
        if "character" in image and image["character"]:
            caption_parts.append('Character(s):\n' + str(image['character']))
        caption = "\n\n".join(caption_parts) if caption_parts else "No info."
        # Do not let captions be longer than 1024 characters (max Telegram bot limit).
        if len(caption) > 1024:
            caption = caption[:1021].rsplit('\n', 1)[0] + "..."
        message_markup += f"&caption={caption}"

        return message_markup

    def api_request(self, api_call, payload, image, path):
        """
        Send messages or images to Telegram bot.

        Args:
            api_call (str): The API call to make.
            payload (dict): The payload to send to the API.
            image (dict): The image data to send.
            path (str): The path to the image file.

        Raises:
            requests.exceptions.RequestException: Could not communicate with Telegram.
        """
        if api_call == 'sendMessage':
            try:
                url = self.build_telegram_api_url(api_call, "?" + urllib.parse.urlencode(payload))
                response = requests.get(url, timeout=10)
                response_json = response.json()
                if not response_json.get("ok", False):
                    self.logger.error(f"Failed to send message: {response_json}")
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Could not communicate with Telegram: {e}")

    def send_message(self, message):
        """
        Sends a message to all admin users.

        Args:
            message (str): The message to send.
        """
        if not message:
            return

        for admin in self.config.admins:
            payload = {'chat_id': str(admin), 'text': message, 'parse_mode': 'Markdown'}
            self.api_request('sendMessage', payload, None, None)

    def send_image(self, api_call, image, path):
        """
        Sends an image to a Telegram bot with retry logic.

        Args:
            api_call (str): The API call to make.
            image (dict): The image data to send.
            path (str): The path to the image file.

        Returns:
            bool: True if the image was sent successfully, False otherwise.
        """
        max_retries = 3
        timeouts = [10, 20, 30]
        
        for attempt in range(max_retries):
            sent_file = None
            timeout = timeouts[attempt]
            
            try:
                # Reset file handles to beginning before each attempt to avoid "file must be non-empty" errors
                for file_obj in image.values():
                    if hasattr(file_obj, 'seek'):
                        file_obj.seek(0)
                
                self.logger.debug(f"Attempting to send {path} (attempt {attempt + 1}/{max_retries}, timeout={timeout}s)")
                sent_file = requests.get(api_call, files=image, timeout=timeout)
                
                if sent_file.status_code != 200:
                    self.logger.error(f"{path} failed to send. Telegram API returned {sent_file.status_code} - {sent_file.text}")
                    if attempt == max_retries - 1:
                        self.send_message(f"❌ Image failed to send after {max_retries} attempts: `{path}`\nStatus: {sent_file.status_code}")
                        return False
                    continue
                
                response_json = sent_file.json() if sent_file.headers.get('Content-Type') == 'application/json' else {}

                if response_json.get("ok"):
                    self.logger.debug("Image sent successfully.")
                    return True
                else:
                    self.logger.error(f"{path} failed to send. Response: {response_json}")
                    if attempt == max_retries - 1:
                        self.send_message(f"❌ Image failed to send after {max_retries} attempts: `{path}`\nResponse: {response_json.get('description', 'Unknown error')}")
                        return False
                        
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Could not communicate with the Telegram bot (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    self.send_message(f"❌ Network error sending image after {max_retries} attempts: `{path}`\nError: {type(e).__name__}")
                    return False
                # Wait before retrying (exponential backoff)
                time.sleep(2 ** attempt)
        
        return False

    def process_incoming_message(self, message: dict):
        """
        Processes incoming messages from Telegram admin users.

        Args:
            message (dict): The incoming message data from Telegram.
        """
        # Check if the message is from an admin
        user_id = message.get('from', {}).get('id')
        text = message.get('text', '').strip().lower()
        if user_id in self.config.admins:
            if text == 'test':
                self.logger.debug('test')

    def poll_telegram_updates(self, is_shutting_down_func):
        """
        Polls Telegram for new updates and processes incoming messages from admins.
        
        Args:
            is_shutting_down_func (callable): Function that returns whether the bot is shutting down.
        """
        offset = None
        consecutive_timeouts = 0
        consecutive_errors = 0
        self.logger.info("Starting Telegram polling loop for admin messages.")
        while not is_shutting_down_func():
            start_time = time.monotonic()
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {'timeout': 30, 'offset': offset}
                response = self.polling_session.get(url, params=params, timeout=(5, 35))
                elapsed = time.monotonic() - start_time
                if response.status_code == 200:
                    data = response.json()
                    updates = data.get('result', [])
                    if updates:
                        self.logger.debug(f"Polling succeeded in {elapsed:.2f}s with {len(updates)} update(s). Offset now {offset}.")
                    else:
                        # Long polls often return empty when no messages exist. Keep it quiet but traceable.
                        self.logger.debug(f"Polling completed in {elapsed:.2f}s with no updates. Offset {offset}.")
                    for update in data.get('result', []):
                        offset = update['update_id'] + 1
                        message = update.get('message')
                        if message:
                            self.process_incoming_message(message)
                    consecutive_timeouts = 0
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    delay = min(5 * consecutive_errors, 60)
                    self.logger.warning(
                        f"Failed to fetch updates (status={response.status_code}) after {elapsed:.2f}s. "
                        f"Body preview: {response.text[:200]!r}. Backing off {delay}s."
                    )
                    time.sleep(delay)
            except ReadTimeout:
                consecutive_timeouts += 1
                elapsed = time.monotonic() - start_time
                log_method = self.logger.info if consecutive_timeouts % 3 == 0 else self.logger.debug
                log_method(f"Telegram long poll timed out after {elapsed:.2f}s (#{consecutive_timeouts}).")
            except ConnectionError as e:
                consecutive_errors += 1
                elapsed = time.monotonic() - start_time
                delay = min(5 * consecutive_errors, 60)
                self.logger.warning(
                    f"Telegram polling connection error after {elapsed:.2f}s (#{consecutive_errors}): {e}. "
                    f"Backing off {delay}s."
                )
                time.sleep(delay)
            except RequestException as e:
                consecutive_errors += 1
                elapsed = time.monotonic() - start_time
                delay = min(5 * consecutive_errors, 60)
                self.logger.error(
                    f"Telegram polling request error after {elapsed:.2f}s (#{consecutive_errors}): {e}. "
                    f"Backing off {delay}s."
                )
                time.sleep(delay)
            except Exception as e:
                consecutive_errors += 1
                elapsed = time.monotonic() - start_time
                delay = min(5 * consecutive_errors, 60)
                self.logger.error(
                    f"Unexpected error in Telegram polling after {elapsed:.2f}s (#{consecutive_errors}): {e}. "
                    f"Backing off {delay}s."
                )
                time.sleep(delay)
