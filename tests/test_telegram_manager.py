import unittest
from unittest.mock import MagicMock, patch
import urllib.parse
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock wand before importing telegram_manager
sys.modules['wand'] = MagicMock()
sys.modules['wand.image'] = MagicMock()

from modules.telegram_manager import TelegramManager


class TestGetMessageMarkup(unittest.TestCase):
    """Tests for TelegramManager.get_message_markup()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        """Set up a TelegramManager instance with mocked dependencies."""
        self.manager = TelegramManager(None)
        # Set up minimal required attributes
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_url_encodes_caption_with_special_characters(self):
        """Caption with special characters (&, <, >) is URL-encoded correctly."""
        image = {
            "title": "Test & Title <with> special chars",
            "creator": "Artist & Co.",
        }

        result = self.manager.get_message_markup(image)

        # Verify the caption is URL-encoded
        self.assertIn("&caption=", result)
        # Extract and decode the caption to verify content
        caption_encoded = result.split("&caption=")[1]
        caption_decoded = urllib.parse.unquote(caption_encoded)
        self.assertIn("Test & Title <with> special chars", caption_decoded)
        self.assertIn("Artist & Co.", caption_decoded)
        # Verify special characters are encoded in the URL
        self.assertIn("%26", caption_encoded)  # & encoded
        self.assertIn("%3C", caption_encoded)  # < encoded
        self.assertIn("%3E", caption_encoded)  # > encoded

    def test_url_encodes_simple_caption(self):
        """Simple caption without special characters is URL-encoded correctly."""
        image = {
            "title": "Simple Title",
            "creator": "SimpleArtist",
        }

        result = self.manager.get_message_markup(image)

        self.assertIn("&caption=", result)
        caption_encoded = result.split("&caption=")[1]
        caption_decoded = urllib.parse.unquote(caption_encoded)
        self.assertIn("Simple Title", caption_decoded)
        self.assertIn("SimpleArtist", caption_decoded)

    def test_handles_empty_caption(self):
        """Image with no title/creator/character results in 'No info.' caption."""
        image = {}

        result = self.manager.get_message_markup(image)

        self.assertIn("&caption=", result)
        caption_encoded = result.split("&caption=")[1]
        caption_decoded = urllib.parse.unquote(caption_encoded)
        self.assertEqual("No info.", caption_decoded)

    def test_truncates_long_caption_before_url_encoding(self):
        """Caption longer than 1024 characters is truncated before URL encoding."""
        # Create a long caption that exceeds 1024 characters
        long_title = "A" * 500
        long_creator = "B" * 500
        long_character = "C" * 500
        image = {
            "title": long_title,
            "creator": long_creator,
            "character": long_character,
        }

        result = self.manager.get_message_markup(image)

        # Extract and decode the caption
        caption_encoded = result.split("&caption=")[1]
        caption_decoded = urllib.parse.unquote(caption_encoded)
        # Verify it's truncated to 1024 characters or less
        self.assertLessEqual(len(caption_decoded), 1024)
        # Verify it ends with "..."
        self.assertTrue(caption_decoded.endswith("..."))


class TestConcatenateSauce(unittest.TestCase):
    """Tests for TelegramManager.concatenate_sauce()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_returns_comma_separated_urls(self):
        """Multiple matching URLs are joined with ', '."""
        urls = ["https://www.example.com/page1", "https://www.example.com/page2"]
        result = self.manager.concatenate_sauce(urls)
        self.assertEqual("https://www.example.com/page1, https://www.example.com/page2", result)

    def test_no_trailing_comma(self):
        """Result should not have a trailing comma."""
        urls = ["https://www.example.com/page1"]
        result = self.manager.concatenate_sauce(urls)
        self.assertFalse(result.endswith(","))
        self.assertEqual("https://www.example.com/page1", result)

    def test_filters_non_matching_urls(self):
        """URLs not starting with https://www. or https://e621.net/posts are excluded."""
        urls = [
            "https://www.furaffinity.net/view/123/",
            "https://static1.e621.net/data/image.jpg",  # direct link, no match
            "https://e621.net/posts/456",
            "http://example.com/page",  # http, not https
        ]
        result = self.manager.concatenate_sauce(urls)
        self.assertIn("furaffinity.net", result)
        self.assertIn("e621.net/posts/456", result)
        self.assertNotIn("static1.e621.net", result)
        self.assertNotIn("http://example.com", result)

    def test_empty_list_returns_empty_string(self):
        """Empty URL list returns empty string."""
        result = self.manager.concatenate_sauce([])
        self.assertEqual("", result)

    def test_all_filtered_returns_empty_string(self):
        """When all URLs are filtered out, returns empty string."""
        urls = ["https://static1.e621.net/data/image.jpg"]
        result = self.manager.concatenate_sauce(urls)
        self.assertEqual("", result)


class TestReplaceHtmlEntities(unittest.TestCase):
    """Tests for TelegramManager.replace_html_entities()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_replaces_ampersand(self):
        self.assertEqual("foo + bar", self.manager.replace_html_entities("foo & bar"))

    def test_replaces_angle_brackets(self):
        result = self.manager.replace_html_entities("<tag>")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
        self.assertIn("\u227a", result)  # ≺
        self.assertIn("\u227b", result)  # ≻

    def test_no_entities_unchanged(self):
        self.assertEqual("plain text", self.manager.replace_html_entities("plain text"))

    def test_multiple_entities(self):
        result = self.manager.replace_html_entities("a & b < c > d")
        self.assertEqual("a + b \u227a c \u227b d", result)


class TestBuildTelegramApiUrl(unittest.TestCase):
    """Tests for TelegramManager.build_telegram_api_url()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.token = "123:ABC"

    def test_basic_api_url(self):
        url = self.manager.build_telegram_api_url("sendMessage", "?chat_id=123")
        self.assertEqual("https://api.telegram.org/bot123:ABC/sendMessage?chat_id=123", url)

    def test_strips_extra_question_mark(self):
        """Payload with leading ? should not produce double ??."""
        url = self.manager.build_telegram_api_url("sendMessage", "?chat_id=123")
        self.assertNotIn("??", url)

    def test_file_url(self):
        url = self.manager.build_telegram_api_url("", "?file_path=photos/file.jpg", is_file=True)
        self.assertIn("file/bot123:ABC", url)
        self.assertNotIn("/sendMessage", url)

    def test_no_payload(self):
        url = self.manager.build_telegram_api_url("getMe", "")
        self.assertEqual("https://api.telegram.org/bot123:ABC/getMe", url)


class TestRedactToken(unittest.TestCase):
    """Tests for TelegramManager._redact_token()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.token = "123:SECRET_TOKEN"

    def test_redacts_token(self):
        text = "Error at https://api.telegram.org/bot123:SECRET_TOKEN/sendMessage"
        result = self.manager._redact_token(text)
        self.assertNotIn("123:SECRET_TOKEN", result)
        self.assertIn("[REDACTED]", result)

    def test_no_token_unchanged(self):
        text = "No token here"
        result = self.manager._redact_token(text)
        self.assertEqual("No token here", result)


class TestBuildCaptionButtons(unittest.TestCase):
    """Tests for TelegramManager.build_caption_buttons()"""

    @patch.object(TelegramManager, '__init__', lambda self, config: None)
    def setUp(self):
        self.manager = TelegramManager(None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()

    def test_none_caption_returns_none(self):
        result = self.manager.build_caption_buttons(None)
        self.assertIsNone(result)

    def test_e621_url_gets_label(self):
        caption = "https://e621.net/posts/123"
        result = self.manager.build_caption_buttons(caption)
        self.assertIsNotNone(result)
        buttons = result['inline_keyboard']
        self.assertEqual(1, len(buttons))
        self.assertEqual('e621', buttons[0][0]['text'])

    def test_reddit_url_with_subreddit(self):
        caption = "https://www.reddit.com/r/aww/comments/abc123"
        result = self.manager.build_caption_buttons(caption)
        buttons = result['inline_keyboard']
        self.assertIn('Reddit', buttons[0][0]['text'])
        self.assertIn('r/aww', buttons[0][0]['text'])

    def test_multiple_urls_in_two_columns(self):
        """Two URLs should be in the same row (two-column layout)."""
        caption = "https://e621.net/posts/1, https://e621.net/posts/2"
        result = self.manager.build_caption_buttons(caption)
        buttons = result['inline_keyboard']
        # Two URLs should be in the same row
        self.assertEqual(1, len(buttons))
        self.assertEqual(2, len(buttons[0]))

    def test_no_http_links_returns_empty_keyboard(self):
        caption = "just some text without urls"
        result = self.manager.build_caption_buttons(caption)
        self.assertEqual({'inline_keyboard': []}, result)


if __name__ == "__main__":
    unittest.main()
