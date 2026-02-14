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


if __name__ == "__main__":
    unittest.main()
