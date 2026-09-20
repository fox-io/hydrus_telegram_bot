import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

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



class TestRecordSendFailure(unittest.TestCase):
    """
    Tests for QueueManager.record_send_failure().

    A file that can never be sent must eventually leave the queue, otherwise it is
    redrawn at random forever and unsendable files accumulate until they crowd out
    the good ones.
    """

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.max_send_failures = 3
        self.manager.config.failed_tag = 'failed:telegram'
        self.manager.hydrus = MagicMock()
        self.manager.hydrus.mark_file_failed.return_value = True
        self.manager.telegram = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.delete_from_queue = MagicMock()
        self.entry = {'path': 'abc123.jpg', 'file_id': 7}
        self.manager.queue_data = {"queue": [self.entry]}
        self.manager.queue_loaded = True

    def test_first_failure_keeps_file_and_counts(self):
        self.manager.record_send_failure('queue/abc123.jpg', 0, self.entry)

        self.assertEqual(1, self.entry['failures'])
        self.manager.delete_from_queue.assert_not_called()
        self.manager.hydrus.mark_file_failed.assert_not_called()
        self.manager.save_queue.assert_called_once()

    def test_failures_accumulate_across_runs(self):
        for expected in (1, 2):
            self.manager.record_send_failure('queue/abc123.jpg', 0, self.entry)
            self.assertEqual(expected, self.entry['failures'])
            self.manager.delete_from_queue.assert_not_called()

    def test_final_failure_evicts_and_tags_hydrus(self):
        self.entry['failures'] = 2

        self.manager.record_send_failure('queue/abc123.jpg', 0, self.entry)

        self.assertEqual(3, self.entry['failures'])
        self.manager.delete_from_queue.assert_called_once_with('queue/abc123.jpg', 0)
        self.manager.hydrus.mark_file_failed.assert_called_once_with(file_id=7, file_hash='abc123')
        self.manager.telegram.send_message.assert_called_once()
        self.assertIn('failed:telegram', self.manager.telegram.send_message.call_args.args[0])

    def test_legacy_entry_without_file_id_falls_back_to_hash(self):
        """Entries queued before file_id was stored are resolved by hash."""
        entry = {'path': 'deadbeef.png', 'failures': 2}

        self.manager.record_send_failure('queue/deadbeef.png', 0, entry)

        self.manager.hydrus.mark_file_failed.assert_called_once_with(file_id=None, file_hash='deadbeef')
        self.manager.delete_from_queue.assert_called_once()

    def test_eviction_proceeds_when_hydrus_tagging_fails(self):
        """A Hydrus outage must not keep an unsendable file in the queue forever."""
        self.manager.hydrus.mark_file_failed.return_value = False
        self.entry['failures'] = 2

        self.manager.record_send_failure('queue/abc123.jpg', 0, self.entry)

        self.manager.delete_from_queue.assert_called_once()
        self.assertIn('Could not tag it in Hydrus', self.manager.telegram.send_message.call_args.args[0])

    def test_respects_configured_limit(self):
        self.manager.config.max_send_failures = 1

        self.manager.record_send_failure('queue/abc123.jpg', 0, self.entry)

        self.manager.delete_from_queue.assert_called_once()


class TestProcessQueueFailureHandling(unittest.TestCase):
    """Tests that unsendable files are routed into the failure counter."""

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.telegram_channel = -100
        self.manager.config.max_post_attempts = 10
        self.manager.telegram = MagicMock()
        self.manager.hydrus = MagicMock()
        self.manager.load_queue = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.delete_from_queue = MagicMock()
        self.manager.record_send_failure = MagicMock()
        self.manager.queue_loaded = True

    def _queue(self, path):
        self.manager.queue_data = {"queue": [{'path': path, 'file_id': 7}]}

    def test_ffmpeg_failure_is_recorded_not_raised(self):
        """A conversion failure must not escape into the scheduler's retry loop."""
        self._queue('clip.webm')
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'ffmpeg')):
            self.manager.process_queue()

        self.manager.record_send_failure.assert_called_once()
        self.manager.delete_from_queue.assert_not_called()

    def test_missing_media_file_is_recorded_not_raised(self):
        self._queue('gone.jpg')
        self.manager.telegram.reduce_image_size.return_value = True
        with patch('builtins.open', side_effect=FileNotFoundError('gone.jpg')):
            self.manager.process_queue()

        self.manager.record_send_failure.assert_called_once()
        self.manager.delete_from_queue.assert_not_called()

    def test_send_failure_is_recorded(self):
        self._queue('photo.jpg')
        self.manager.telegram.reduce_image_size.return_value = True
        self.manager.telegram.send_image.return_value = False
        with patch('builtins.open', MagicMock()):
            self.manager.process_queue()

        self.manager.record_send_failure.assert_called_once()
        self.manager.delete_from_queue.assert_not_called()

    def test_successful_send_deletes_and_does_not_count_failure(self):
        self._queue('photo.jpg')
        self.manager.telegram.reduce_image_size.return_value = True
        self.manager.telegram.send_image.return_value = True
        with patch('builtins.open', MagicMock()):
            self.manager.process_queue()

        self.manager.delete_from_queue.assert_called_once_with('queue/photo.jpg', 0)
        self.manager.record_send_failure.assert_not_called()

    def test_invalid_dimensions_still_removed_immediately(self):
        """The existing self-healing path is unchanged: no failure counting needed."""
        self._queue('wide.jpg')
        self.manager.telegram.reduce_image_size.return_value = False

        self.manager.process_queue()

        self.manager.delete_from_queue.assert_called_once_with('queue/wide.jpg', 0)
        self.manager.record_send_failure.assert_not_called()


class TestProcessQueueKeepsTrying(unittest.TestCase):
    """
    Tests that a scheduled run posts something rather than being consumed by a
    file that cannot be sent.
    """

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.max_post_attempts = 10
        self.manager.telegram = MagicMock()
        self.manager.hydrus = MagicMock()
        self.manager.load_queue = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.record_send_failure = MagicMock()
        self.manager.queue_loaded = True

    def _queue(self, *paths):
        self.manager.queue_data = {"queue": [{'path': p, 'file_id': i} for i, p in enumerate(paths)]}

    def test_moves_on_to_another_file_after_a_failure(self):
        """A failed file must not consume the run."""
        self._queue('a.jpg', 'b.jpg', 'c.jpg')
        attempted = []

        def attempt(entry, index):
            attempted.append(entry['path'])
            return len(attempted) == 3  # first two fail, third posts

        self.manager._attempt_post = MagicMock(side_effect=attempt)

        self.manager.process_queue()

        self.assertEqual(3, len(attempted))
        self.assertEqual(3, len(set(attempted)), "should not retry the same file twice in one run")

    def test_stops_as_soon_as_something_posts(self):
        self._queue('a.jpg', 'b.jpg', 'c.jpg')
        self.manager._attempt_post = MagicMock(return_value=True)

        self.manager.process_queue()

        self.manager._attempt_post.assert_called_once()
        self.manager.telegram.send_message.assert_not_called()

    def test_never_retries_the_same_file_within_one_run(self):
        self._queue('a.jpg', 'b.jpg')
        self.manager._attempt_post = MagicMock(return_value=False)

        self.manager.process_queue()

        tried = [call.args[0]['path'] for call in self.manager._attempt_post.call_args_list]
        self.assertEqual(2, len(tried))
        self.assertEqual({'a.jpg', 'b.jpg'}, set(tried))

    def test_gives_up_and_notifies_when_whole_queue_fails(self):
        self._queue('a.jpg', 'b.jpg')
        self.manager._attempt_post = MagicMock(return_value=False)

        self.manager.process_queue()

        self.assertIn('Nothing could be posted', self.manager.telegram.send_message.call_args.args[0])

    def test_respects_max_post_attempts(self):
        """A mostly-unsendable queue must not be walked end to end in one run."""
        self._queue(*[f'{i}.jpg' for i in range(50)])
        self.manager.config.max_post_attempts = 4
        self.manager._attempt_post = MagicMock(return_value=False)

        self.manager.process_queue()

        self.assertEqual(4, self.manager._attempt_post.call_count)

    def test_handles_queue_shrinking_mid_run(self):
        """Evicting a file shifts indices; the run must still pick valid entries."""
        self._queue('a.jpg', 'b.jpg', 'c.jpg')
        seen = []

        def attempt(entry, index):
            seen.append((entry['path'], index))
            # Simulate record_send_failure evicting this entry.
            self.manager.queue_data['queue'].pop(index)
            return False

        self.manager._attempt_post = MagicMock(side_effect=attempt)

        self.manager.process_queue()

        self.assertEqual(3, len(seen))
        self.assertEqual({'a.jpg', 'b.jpg', 'c.jpg'}, {p for p, _ in seen})
        # Every index handed to _attempt_post must have addressed that same entry.
        self.assertEqual([], [p for p, i in seen if i < 0])

    def test_empty_queue_still_short_circuits(self):
        self.manager.queue_data = {"queue": []}
        self.manager._attempt_post = MagicMock()

        self.manager.process_queue()

        self.manager._attempt_post.assert_not_called()
        self.assertIn('Queue is empty', self.manager.telegram.send_message.call_args.args[0])


class TestProcessQueueEndToEnd(unittest.TestCase):
    """
    Exercises process_queue with the real _attempt_post, record_send_failure and
    delete_from_queue, so index shifting during eviction is actually covered.
    """

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.telegram_channel = -100
        self.manager.config.max_post_attempts = 10
        self.manager.config.max_send_failures = 3
        self.manager.config.failed_tag = 'failed:telegram'
        self.manager.telegram = MagicMock()
        self.manager.telegram.reduce_image_size.return_value = True
        self.manager.hydrus = MagicMock()
        self.manager.hydrus.mark_file_failed.return_value = True
        self.manager.load_queue = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.queue_loaded = True

    def test_all_files_at_cap_are_each_evicted_and_tagged(self):
        """Index shifting during eviction must not skip or double-evict entries."""
        self.manager.queue_data = {"queue": [
            {'path': 'a.jpg', 'file_id': 1, 'failures': 2},
            {'path': 'b.jpg', 'file_id': 2, 'failures': 2},
            {'path': 'c.jpg', 'file_id': 3, 'failures': 2},
        ]}
        self.manager.telegram.send_image.return_value = False

        with patch('builtins.open', MagicMock()), patch('os.remove'):
            self.manager.process_queue()

        self.assertEqual([], self.manager.queue_data['queue'], "queue should be fully drained")
        tagged = {c.kwargs['file_id'] for c in self.manager.hydrus.mark_file_failed.call_args_list}
        self.assertEqual({1, 2, 3}, tagged, "every evicted file must be tagged exactly once")
        self.assertEqual(3, self.manager.hydrus.mark_file_failed.call_count)

    def test_posts_the_one_good_file_among_bad_ones(self):
        """
        The run must post rather than being consumed by a bad file.

        random.choice is pinned to the first candidate so the bad file is drawn
        first, which is the case worth testing: fail, move on, post.
        """
        self.manager.queue_data = {"queue": [
            {'path': 'bad.jpg', 'file_id': 1},
            {'path': 'good.jpg', 'file_id': 2},
        ]}
        self.manager.telegram.send_image.side_effect = lambda req, files, path: path == 'queue/good.jpg'

        with patch('builtins.open', MagicMock()), patch('os.remove'), \
             patch('random.choice', lambda seq: seq[0]):
            self.manager.process_queue()

        remaining = {e['path'] for e in self.manager.queue_data['queue']}
        self.assertEqual({'bad.jpg'}, remaining, "the good file should have posted and been removed")
        # The bad file is kept with one failure recorded, not evicted.
        self.assertEqual(1, self.manager.queue_data['queue'][0]['failures'])
        self.manager.hydrus.mark_file_failed.assert_not_called()
        # A successful post must not trigger the "nothing posted" alert.
        for call in self.manager.telegram.send_message.call_args_list:
            self.assertNotIn('Nothing could be posted', call.args[0])

if __name__ == "__main__":
    unittest.main()
