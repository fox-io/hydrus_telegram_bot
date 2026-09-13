import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hydrus_api

from modules.hydrus_manager import HydrusManager
from modules.queue_manager import QueueResult


class TestGetNewHydrusFilesRetagging(unittest.TestCase):
    """
    Tests for HydrusManager.get_new_hydrus_files() retagging behaviour.

    A file must only lose its queue tag once it is confirmed to be in the queue.
    Retagging on failure marks the file as posted, so Hydrus never surfaces it
    again and it is silently lost.
    """

    @patch.object(HydrusManager, '__init__', lambda self, config, queue: None)
    def setUp(self):
        self.manager = HydrusManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.queue_tag = 'to_post'
        self.manager.config.posted_tag = 'posted:telegram'
        self.manager.queue = MagicMock()
        self.manager.hydrus_client = MagicMock()
        self.manager.hydrus_client.search_files.return_value = {'file_ids': [1]}
        self.manager.modify_tag = MagicMock()
        self.manager.check_hydrus_permissions = MagicMock(return_value=True)

    def test_failed_enqueue_does_not_retag(self):
        """A file that could not be queued keeps its tags so it can be retried."""
        self.manager.queue.save_image_to_queue.return_value = QueueResult.FAILED

        self.manager.get_new_hydrus_files()

        self.manager.modify_tag.assert_not_called()

    def test_added_file_is_retagged(self):
        """A successfully queued file loses the queue tag and gains the posted tag."""
        self.manager.queue.save_image_to_queue.return_value = QueueResult.ADDED

        self.manager.get_new_hydrus_files()

        self.assertEqual(3, self.manager.modify_tag.call_count)
        self.manager.modify_tag.assert_any_call(1, 'to_post', hydrus_api.TagAction.DELETE, 'downloader_tags')
        self.manager.modify_tag.assert_any_call(1, 'to_post', hydrus_api.TagAction.DELETE, 'my_tags')
        self.manager.modify_tag.assert_any_call(1, 'posted:telegram', hydrus_api.TagAction.ADD, 'my_tags')

    def test_duplicate_file_is_still_retagged(self):
        """
        An already-queued file must still be retagged.

        Skipping the retag here would make Hydrus return the same file on every
        run, re-downloading it forever.
        """
        self.manager.queue.save_image_to_queue.return_value = QueueResult.DUPLICATE

        self.manager.get_new_hydrus_files()

        self.assertEqual(3, self.manager.modify_tag.call_count)

    def test_failure_does_not_block_other_files(self):
        """One failing file does not stop the rest of the batch from being retagged."""
        self.manager.hydrus_client.search_files.return_value = {'file_ids': [1, 2]}
        self.manager.queue.save_image_to_queue.side_effect = [QueueResult.FAILED, QueueResult.ADDED]

        self.manager.get_new_hydrus_files()

        retagged_ids = {call.args[0] for call in self.manager.modify_tag.call_args_list}
        self.assertEqual({2}, retagged_ids)

    def test_no_files_found_does_not_retag(self):
        self.manager.hydrus_client.search_files.return_value = {'file_ids': []}

        self.manager.get_new_hydrus_files()

        self.manager.modify_tag.assert_not_called()
        self.manager.queue.save_image_to_queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
