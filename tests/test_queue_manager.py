import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.queue_manager import QueueManager


class TestProperTitle(unittest.TestCase):
    """Tests for QueueManager._proper_title()"""

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()

    def test_basic_title_case(self):
        self.assertEqual("Hello World", self.manager._proper_title("hello world"))

    def test_apostrophe_not_capitalized(self):
        """Letters after apostrophes should stay lowercase (e.g. don't -> Don't, not Don'T)."""
        self.assertEqual("Don't", self.manager._proper_title("don't"))

    def test_multiple_apostrophe_words(self):
        self.assertEqual("It's A Won't Situation", self.manager._proper_title("it's a won't situation"))

    def test_empty_string(self):
        self.assertEqual("", self.manager._proper_title(""))

    def test_none_returns_none(self):
        self.assertIsNone(self.manager._proper_title(None))

    def test_single_word(self):
        self.assertEqual("Hello", self.manager._proper_title("hello"))

    def test_already_title_case(self):
        self.assertEqual("Already Title", self.manager._proper_title("Already Title"))

    def test_all_caps(self):
        self.assertEqual("All Caps", self.manager._proper_title("ALL CAPS"))

    def test_artist_name_with_underscore_style(self):
        """Tag-style names are capitalized per word."""
        self.assertEqual("Some Artist", self.manager._proper_title("some artist"))

    def test_preserves_apostrophe_at_start(self):
        """Apostrophe at the start of a word."""
        result = self.manager._proper_title("'twas the night")
        self.assertIn("The", result)
        self.assertIn("Night", result)


if __name__ == "__main__":
    unittest.main()
