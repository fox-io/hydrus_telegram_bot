import html
import json
import math
import os
import pathlib
import re
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, ReadTimeout, RequestException
from urllib3.util.retry import Retry

from modules.log_manager import LogManager

#: Directory holding the bundled ImageMagick policy.xml, relative to this file.
POLICY_DIR = pathlib.Path(__file__).resolve().parent.parent / "config" / "magick"


def use_bundled_imagemagick_policy(policy_dir=POLICY_DIR, env=None) -> bool:
    """
    Points ImageMagick at the policy.xml bundled with this repository.

    ImageMagick's coder and delegate restrictions can only come from a policy.xml,
    and it finds that file through MAGICK_CONFIGURE_PATH. Setting the variable here
    means the restrictions apply on every machine with nothing to install, which
    matters because the alternative is fragile: on Homebrew the real policy.xml
    lives inside the version-pinned Cellar, so `brew upgrade imagemagick` silently
    discards a hand-copied one.

    Pointing at a directory containing only policy.xml is safe. ImageMagick falls
    back to its installed configuration for everything else, so delegates still
    resolve normally.

    Args:
        policy_dir (Path): Directory containing policy.xml.
        env (MutableMapping): Environment to modify. Defaults to os.environ.

    Returns:
        bool: True if the variable was set, False if it was left alone.

    Note:
        An existing MAGICK_CONFIGURE_PATH is never overwritten, so an operator who
        has pointed ImageMagick somewhere deliberately keeps that choice.

        This must run before wand is imported: ImageMagick reads its configuration
        when the library first loads, so setting the variable afterwards has no
        effect. That is why the wand imports below sit after this call.
    """
    env = os.environ if env is None else env
    if not (policy_dir / "policy.xml").is_file():
        return False
    if "MAGICK_CONFIGURE_PATH" in env:
        return False
    env["MAGICK_CONFIGURE_PATH"] = str(policy_dir)
    return True


use_bundled_imagemagick_policy()

from wand.image import Image  # noqa: E402  (must follow the call above)
from wand.resource import limits  # noqa: E402


def imagemagick_limits(memory_mb: int, time_seconds: int, max_dimension: int) -> dict:
    """
    Computes the ImageMagick resource limits to apply.

    Kept separate from applying them so the arithmetic can be tested without a
    working ImageMagick install.

    Args:
        memory_mb (int): Megabytes of pixel cache before ImageMagick spills to disk.
        time_seconds (int): Wall-clock ceiling for any single operation.
        max_dimension (int): Largest width or height accepted from a source file.

    Returns:
        dict: Limit names mapped to their values, in the units ImageMagick expects
              (bytes for memory/map/disk/area, seconds for time, pixels for
              width/height).
    """
    memory_bytes = memory_mb * 1024 * 1024
    return {
        'memory': memory_bytes,
        # Memory-mapped and on-disk spill are allowed to exceed the in-memory cache,
        # but must still be bounded: disk is unlimited by default.
        'map': memory_bytes * 2,
        'disk': memory_bytes * 4,
        'area': memory_bytes,
        'time': time_seconds,
        'width': max_dimension,
        'height': max_dimension,
        # The bot decodes one image at a time; extra threads only add contention.
        'thread': 1,
    }


#: Path suffixes that mark a URL as pointing at the file itself rather than at a page
#: about it. Hydrus records both kinds in known_urls and only the pages are useful
#: as sauce links.
DIRECT_MEDIA_SUFFIXES = (
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.webm', '.mp4', '.avif', '.swf', '.bmp',
)


class TelegramManager:
    """
    TelegramManager handles communication with the Telegram bot.

    Attributes:
        logger (Logger): The logger for the TelegramManager.
        config (ConfigManager): The configuration settings for the bot.
        token (str): The Telegram bot access token.

    Methods:
        build_telegram_api_url(method, payload, is_file): Constructs a Telegram API url for bot communication.
        concatenate_sauce(known_urls): Return source URLs, minus direct file links.
        escape_html(text): Escape text for Telegram's HTML parse mode.
        build_caption_buttons(caption): Assembles buttons to display under the Telegram post.
        reduce_image_size(path): Telegram has limits on image file size and dimensions. We resize large things here.
        get_message_markup(image): Build the message markup for the Telegram post.
        api_request(api_call, payload): Send messages or images to Telegram bot.
        send_message(message): Sends a message to all admin users.
        send_image(api_call, image, path): Attempt to send the image to our Telegram bot.
    """
    subreddit_regex = "/(r/[a-z0-9][_a-z0-9]{2,20})/"

    def __init__(self, config):
        """
        Initializes the TelegramManager object.

        Args:
            config (ConfigManager): The configuration settings for the bot.

        Raises:
            ValueError: No Telegram access token was configured.
        """
        self.logger = LogManager.setup_logger('TEL')
        self.config = config.config_data
        if not self.config.telegram_access_token:
            # Returning here would leave self.token undefined, so every later call
            # raised AttributeError far from the actual cause. _redact_token is the
            # worst of them: it is used in the handler for other failures, so the
            # missing token masked whatever error was being reported.
            self.logger.error('No Telegram token was provided.')
            raise ValueError('telegram_access_token is required')
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
        self.apply_imagemagick_limits()
        self.logger.debug('Telegram Module initialized.')

    def apply_imagemagick_limits(self):
        """
        Constrains what ImageMagick is allowed to spend decoding a queued file.

        Queued media is downloaded from the internet, so ImageMagick is parsing
        attacker-influenced input. Its stock limits are close to unbounded: on a
        typical host `time` and `disk` are both the 64-bit maximum, and width and
        height allow roughly 3.6e16 pixels per side. That makes a decompression bomb
        cheap, since a small file can declare enormous dimensions and have the
        decoder exhaust memory, fill the disk, or simply never finish.

        Note:
            These limits do not address the other ImageMagick risk, which is
            delegate and coder abuse. That is controlled by policy.xml; see
            config/magick/policy.xml, which the bot loads automatically.

            Failures here are logged rather than raised. An older ImageMagick that
            rejects one of these keys should not stop the bot from starting.
        """
        values = imagemagick_limits(
            self.config.imagemagick_memory_limit_mb,
            self.config.imagemagick_time_limit_seconds,
            self.config.imagemagick_max_source_dimension,
        )
        applied = []
        for key, value in values.items():
            try:
                limits[key] = value
            except Exception as e:
                self.logger.warning(f"Could not set ImageMagick '{key}' limit: {e}")
            else:
                applied.append(key)
        self.logger.debug(
            f"Applied ImageMagick limits ({', '.join(applied)}): "
            f"{self.config.imagemagick_memory_limit_mb} MB memory, "
            f"{self.config.imagemagick_time_limit_seconds}s per operation, "
            f"max {self.config.imagemagick_max_source_dimension}px per side."
        )

    def _redact_token(self, text):
        """Redacts the bot token from a string to prevent it from appearing in logs."""
        return str(text).replace(self.token, "[REDACTED]")

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
    def is_source_page(self, url) -> bool:
        """
        Reports whether a URL points at a page about the file rather than the file.

        Args:
            url (str): A URL from Hydrus known_urls.

        Returns:
            bool: True if the URL is worth offering as a sauce link.

        Note:
            This used to be approximated by requiring the URL to start with
            "https://www." or with the e621 posts path, which tested the wrong
            property in both directions. It dropped real source pages that happen
            not to use a www subdomain, such as furaffinity.net, x.com and
            inkbunny.net, and it kept direct file links that do, such as
            https://www.somecdn.com/files/image.jpg.

            Judging by the path suffix matches the actual intent: skip links to the
            media itself, keep everything else.
        """
        if not isinstance(url, str):
            return False
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return False
        return not parsed.path.lower().endswith(DIRECT_MEDIA_SUFFIXES)

    def concatenate_sauce(self, known_urls: list):
        """
        Joins source URLs.

        Args:
            known_urls (list): A list of URLs to combine.

        Returns:
            str: A comma-separated list of source URLs.

        Note:
            Duplicates are collapsed. Hydrus frequently records the same page under
            more than one form, differing only by scheme, a www prefix or a trailing
            slash, which would otherwise produce several buttons pointing at the
            same page. The first form seen is the one kept.
        """
        urls = []
        seen = set()
        for url in known_urls or []:
            if not self.is_source_page(url):
                continue
            key = self._sauce_key(url)
            if key in seen:
                continue
            seen.add(key)
            urls.append(url)
        return ", ".join(urls)

    @staticmethod
    def _sauce_key(url: str):
        """
        Builds a comparison key that ignores cosmetic differences between URLs.

        Args:
            url (str): The URL to key.

        Returns:
            tuple: Host without any www prefix, path without a trailing slash, and
                   the query. The scheme is ignored so http and https forms of one
                   page collapse together.
        """
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith('www.'):
            host = host[4:]
        return (host, parsed.path.rstrip('/').lower(), parsed.query)

    def escape_html(self, text):
        """
        Escapes text for Telegram's HTML parse mode.

        Args:
            text (str): Text destined for a caption.

        Returns:
            str: The text with &, < and > replaced by their HTML entities.

        Note:
            This replaces replace_html_entities(), which substituted lookalike
            characters rather than escaping: & became +, and < and > became the
            Unicode characters PRECEDES and SUCCEEDS. Captions rendered without
            error, but the data was silently altered, so an artist tagged
            "Tom & Jerry" posted as "Tom + Jerry".

            Quotes are left alone. This text is placed between tags, never inside
            an attribute, so a literal quote is both safe and more readable. URLs
            that do go into attributes are percent-encoded instead.
        """
        if text is None:
            return text
        return html.escape(str(text), quote=False)

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
                line = line.strip()
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
                        # Alternate between the two columns.
                        url_column = 1 - url_column
            return keyboard
        else:
            return None

    def reduce_image_size(self, path):
        """
        Reduces image filesize and dimensions as needed for Telegram compatability.

        Args:
            path (str): The path to the image file.

        Returns:
            bool: True if the image is valid or successfully resized, False otherwise.

        Raises:
            Exception: Could not open the image.
        """
        try:
            with Image(filename=path) as img:
                # Wand can return None for unknown formats; guard before lower()
                img_format = img.format.lower() if img.format else None
                if img_format not in ["jpeg", "jpg", "png", "gif"]:
                    self.logger.warning(f"Skipping resize: Unsupported format {img.format}")
                    return True  # Can't resize, but may still be sendable as-is

                # Reject images with zero dimensions
                if img.width == 0 or img.height == 0:
                    self.logger.warning(f"Image has zero dimension ({img.width}x{img.height}): {path}")
                    return False

                # Check aspect ratio
                ratio = img.width / img.height
                if ratio > 20 or ratio < 0.05:
                    self.logger.warning(f"Image aspect ratio {ratio:.2f} exceeds Telegram limit of 20:1.")
                    return False

                # Pass 1: Resize if dimensions exceed Telegram limits
                if img.width > self.config.max_image_dimension or img.height > self.config.max_image_dimension:
                    scale = self.config.max_image_dimension / max(img.width, img.height)
                    img.resize(round(img.width * scale), round(img.height * scale))
                    img.save(filename=path)

                # Pass 2: Scale down further if file size exceeds Telegram limits. Uses os.path.getsize() to
                # check file size even if the pass 1 resized it.
                if os.path.getsize(path) > self.config.max_file_size:
                    size_ratio = os.path.getsize(path) / self.config.max_file_size
                    img.resize(round(img.width / math.sqrt(size_ratio)), round(img.height / math.sqrt(size_ratio)))
                    img.save(filename=path)

            return True
        except Exception as e:
            self.logger.error(f"Could not open the image: {e}")
            return False

    def get_message_markup(self, image) -> dict:
        """
        Builds the Telegram form fields describing a post.

        Args:
            image (dict): The image data to post.

        Returns:
            dict: Form fields to send with the upload. Values are plain strings;
                  requests handles encoding them.

        Note:
            These used to be returned as a pre-encoded query string fragment that
            the caller concatenated into a URL. Returning values means nothing has
            to be quoted by hand, and a field added later cannot be forgotten.
        """
        fields = {}

        # Sauce Buttons
        sauce = self.build_caption_buttons(image['sauce']) if "sauce" in image else None
        if sauce:
            fields['reply_markup'] = json.dumps(sauce)

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
        fields['caption'] = caption

        return fields

    def api_request(self, api_call, payload):
        """
        Send messages or images to Telegram bot.

        Args:
            api_call (str): The API call to make.
            payload (dict): The payload to send to the API.

        Raises:
            requests.exceptions.RequestException: Could not communicate with Telegram.
        """
        if api_call == 'sendMessage':
            try:
                url = self.build_telegram_api_url(api_call, '')
                response = requests.get(url, params=payload, timeout=10)
                response_json = response.json()
                if not response_json.get("ok", False):
                    self.logger.error(f"Failed to send message: {response_json}")
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Could not communicate with Telegram: {self._redact_token(e)}")

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
            self.api_request('sendMessage', payload)

    def send_image(self, api_call, fields, image, path):
        """
        Sends an image to a Telegram bot with retry logic.

        Args:
            api_call (str): The API method to call, such as sendPhoto.
            fields (dict): Form fields to accompany the upload, such as chat_id,
                           caption and parse_mode.
            image (dict): Open file handles to upload, keyed by Telegram field name.
            path (str): The path to the image file, used for logging.

        Returns:
            bool: True if the image was sent successfully, False otherwise.

        Note:
            Fields are posted as multipart form data rather than appended to the
            URL. Telegram accepts either, and passing them as data leaves the
            encoding to requests instead of to hand-written quoting.
        """
        url = self.build_telegram_api_url(api_call, '')
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
                sent_file = requests.post(url, data=fields, files=image, timeout=timeout)

                if sent_file.status_code != 200:
                    self.logger.error(f"{path} failed to send. Telegram API returned {sent_file.status_code} - {sent_file.text}")
                    if 400 <= sent_file.status_code < 500:
                        self.send_message(f"❌ Image failed to send (Client Error): `{path}`\nStatus: {sent_file.status_code}")
                        return False

                    if attempt == max_retries - 1:
                        self.send_message(f"❌ Image failed to send after {max_retries} attempts: `{path}`\nStatus: {sent_file.status_code}")
                        return False
                    continue

                content_type = sent_file.headers.get('Content-Type', '')
                response_json = sent_file.json() if 'application/json' in content_type else {}

                if response_json.get("ok"):
                    self.logger.debug("Image sent successfully.")
                    return True
                else:
                    self.logger.error(f"{path} failed to send. Response: {response_json}")
                    if attempt == max_retries - 1:
                        self.send_message(f"❌ Image failed to send after {max_retries} attempts: `{path}`\nResponse: {response_json.get('description', 'Unknown error')}")
                        return False

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Could not communicate with the Telegram bot (attempt {attempt + 1}/{max_retries}): {self._redact_token(e)}")
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
                    f"Telegram polling connection error after {elapsed:.2f}s (#{consecutive_errors}): {self._redact_token(e)}. "
                    f"Backing off {delay}s."
                )
                time.sleep(delay)
            except RequestException as e:
                consecutive_errors += 1
                elapsed = time.monotonic() - start_time
                delay = min(5 * consecutive_errors, 60)
                self.logger.error(
                    f"Telegram polling request error after {elapsed:.2f}s (#{consecutive_errors}): {self._redact_token(e)}. "
                    f"Backing off {delay}s."
                )
                time.sleep(delay)
            except Exception as e:
                consecutive_errors += 1
                elapsed = time.monotonic() - start_time
                delay = min(5 * consecutive_errors, 60)
                self.logger.error(
                    f"Unexpected error in Telegram polling after {elapsed:.2f}s (#{consecutive_errors}): {self._redact_token(e)}. "
                    f"Backing off {delay}s."
                )
                time.sleep(delay)
