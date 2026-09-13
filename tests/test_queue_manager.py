import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.queue_manager import QueueManager, QueueResult


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


class TestSaveImageToQueue(unittest.TestCase):
    """Tests for QueueManager.save_image_to_queue() result reporting."""

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.queue_data = {"queue": []}
        self.manager.queue_loaded = True
        self.manager.hydrus = MagicMock()
        self.manager.hydrus.hydrus_service_key = {"downloader_tags": "DL", "my_tags": "MY"}
        self.manager.hydrus.get_file_content.return_value = b"image-bytes"
        self.manager.telegram = MagicMock()
        self.manager.telegram.replace_html_entities.side_effect = lambda tag: tag
        self.manager.save_queue = MagicMock()
        self.manager.image_is_queued = MagicMock(return_value=False)

    @staticmethod
    def _metadata(tags):
        return {'metadata': [{'hash': 'abc123', 'ext': '.jpg', 'file_id': 1, 'tags': tags}]}

    @staticmethod
    def _downloader_tags(tag_list):
        return {"DL": {"storage_tags": {"0": tag_list}}}

    def test_missing_metadata_returns_failed(self):
        self.manager.hydrus.get_metadata.return_value = None
        self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))

    def test_missing_file_info_returns_failed(self):
        self.manager.hydrus.get_metadata.return_value = {'metadata': [{'hash': 'abc123'}]}
        self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))

    @patch('pathlib.Path.write_bytes')
    def test_empty_file_content_returns_failed(self, _write_bytes):
        self.manager.hydrus.get_metadata.return_value = self._metadata(self._downloader_tags([]))
        self.manager.hydrus.get_file_content.return_value = b""
        self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))

    @patch('pathlib.Path.write_bytes')
    def test_download_error_returns_failed(self, _write_bytes):
        self.manager.hydrus.get_metadata.return_value = self._metadata(self._downloader_tags([]))
        self.manager.hydrus.get_file_content.side_effect = OSError("boom")
        self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))

    @patch('pathlib.Path.write_bytes')
    def test_successful_save_returns_added(self, _write_bytes):
        self.manager.hydrus.get_metadata.return_value = self._metadata(
            self._downloader_tags(["creator:some artist", "title:a story", "character:someone"])
        )

        self.assertIs(QueueResult.ADDED, self.manager.save_image_to_queue(1))

        self.assertEqual(1, len(self.manager.queue_data['queue']))
        entry = self.manager.queue_data['queue'][0]
        self.assertEqual('abc123.jpg', entry['path'])
        self.assertIn('Some Artist', entry['creator'])
        self.assertIn('A Story', entry['title'])
        self.assertIn('Someone', entry['character'])

    @patch('pathlib.Path.write_bytes')
    def test_already_queued_returns_duplicate(self, _write_bytes):
        self.manager.image_is_queued.return_value = True
        self.manager.hydrus.get_metadata.return_value = self._metadata(self._downloader_tags([]))

        self.assertIs(QueueResult.DUPLICATE, self.manager.save_image_to_queue(1))

        self.assertEqual(0, len(self.manager.queue_data['queue']))

    @patch('pathlib.Path.write_bytes')
    def test_missing_downloader_tags_is_queued_without_metadata(self, _write_bytes):
        """
        A file whose downloader-tags service is absent is still postable.

        Treating this as a failure would strand the file: it would never be
        queued, and would be re-downloaded on every run.
        """
        self.manager.hydrus.get_metadata.return_value = self._metadata({})

        self.assertIs(QueueResult.ADDED, self.manager.save_image_to_queue(1))

        entry = self.manager.queue_data['queue'][0]
        self.assertEqual('abc123.jpg', entry['path'])
        self.assertNotIn('creator', entry)

    @patch('pathlib.Path.write_bytes')
    def test_missing_storage_tags_is_queued_without_metadata(self, _write_bytes):
        self.manager.hydrus.get_metadata.return_value = self._metadata({"DL": {}})

        self.assertIs(QueueResult.ADDED, self.manager.save_image_to_queue(1))
        self.assertNotIn('creator', self.manager.queue_data['queue'][0])

    @patch('pathlib.Path.write_bytes')
    def test_missing_zero_key_is_queued_without_metadata(self, _write_bytes):
        self.manager.hydrus.get_metadata.return_value = self._metadata({"DL": {"storage_tags": {"1": ["creator:x"]}}})

        self.assertIs(QueueResult.ADDED, self.manager.save_image_to_queue(1))
        self.assertNotIn('creator', self.manager.queue_data['queue'][0])


if __name__ == "__main__":
    unittest.main()
