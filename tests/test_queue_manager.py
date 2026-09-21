import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.queue_manager import (
    QueueManager,
    QueueResult,
    resolve_queue_path,
    safe_queue_filename,
)


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
        self.manager.telegram.escape_html.side_effect = lambda text: text
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
        self.manager.telegram.send_image.side_effect = lambda method, fields, files, path: path == 'queue/good.jpg'

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


class TestRunFfmpeg(unittest.TestCase):
    """
    Tests for QueueManager._run_ffmpeg().

    Queued media is downloaded from the internet, so ffmpeg is parsing
    attacker-influenced input and must not be able to run unbounded.
    """

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.ffmpeg_timeout_seconds = 300

    def test_passes_timeout_and_disables_stdin(self):
        with patch('subprocess.run') as run:
            self.manager._run_ffmpeg(["-i", "in.webm", "out.mp4"])

        args, kwargs = run.call_args
        self.assertEqual(300, kwargs['timeout'], "ffmpeg must be bounded by the configured timeout")
        self.assertIn('-nostdin', args[0], "ffmpeg must not be able to consume the bot's stdin")
        self.assertEqual('ffmpeg', args[0][0])
        self.assertTrue(kwargs['check'])

    def test_uses_configured_timeout(self):
        self.manager.config.ffmpeg_timeout_seconds = 7
        with patch('subprocess.run') as run:
            self.manager._run_ffmpeg(["-i", "in.webm", "out.mp4"])
        self.assertEqual(7, run.call_args.kwargs['timeout'])

    def test_timeout_propagates_to_caller(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 300)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.manager._run_ffmpeg(["-i", "in.webm", "out.mp4"])
        self.assertTrue(self.manager.logger.error.called)

    def test_failure_logs_ffmpeg_stderr_tail(self):
        err = subprocess.CalledProcessError(1, 'ffmpeg')
        err.stderr = b"ffmpeg banner line\nInvalid data found when processing input\n"
        with patch('subprocess.run', side_effect=err):
            with self.assertRaises(subprocess.CalledProcessError):
                self.manager._run_ffmpeg(["-i", "bad.webm", "out.mp4"])
        logged = self.manager.logger.error.call_args.args[0]
        self.assertIn("Invalid data found", logged)

    def test_failure_without_stderr_does_not_crash(self):
        err = subprocess.CalledProcessError(1, 'ffmpeg')
        err.stderr = None
        with patch('subprocess.run', side_effect=err):
            with self.assertRaises(subprocess.CalledProcessError):
                self.manager._run_ffmpeg(["-i", "bad.webm", "out.mp4"])


class TestFfmpegTimeoutIsRecorded(unittest.TestCase):
    """A timed-out conversion must be counted as a send failure, not escape the run."""

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.telegram_channel = -100
        self.manager.config.max_post_attempts = 10
        self.manager.config.ffmpeg_timeout_seconds = 300
        self.manager.telegram = MagicMock()
        self.manager.hydrus = MagicMock()
        self.manager.load_queue = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.delete_from_queue = MagicMock()
        self.manager.record_send_failure = MagicMock()
        self.manager.queue_data = {"queue": [{'path': 'hang.webm', 'file_id': 1}]}
        self.manager.queue_loaded = True

    def test_timeout_is_recorded_not_raised(self):
        """
        TimeoutExpired is not an OSError and is not a CalledProcessError, so a handler
        catching only those would let it escape into the scheduler's retry loop.
        """
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 300)):
            self.manager.process_queue()

        self.manager.record_send_failure.assert_called_once()
        self.manager.delete_from_queue.assert_not_called()


class TestSafeQueueFilename(unittest.TestCase):
    """
    Tests for safe_queue_filename().

    The hash and extension arrive verbatim from the Hydrus API and are
    concatenated straight into a filesystem path, so they are a trust boundary.
    """

    def test_accepts_a_normal_file(self):
        self.assertEqual("abc123.jpg", safe_queue_filename("abc123", ".jpg"))

    def test_accepts_the_formats_the_bot_handles(self):
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".webm", ".mp4"):
            with self.subTest(ext=ext):
                self.assertEqual(f"abc123{ext}", safe_queue_filename("abc123", ext))

    def test_rejects_traversal_in_the_extension(self):
        for ext in ("../../../../etc/cron.d/evil", ".jpg/../../../evil", "..", "./x"):
            with self.subTest(ext=ext):
                self.assertIsNone(safe_queue_filename("abc123", ext))

    def test_rejects_separators_in_the_extension(self):
        for ext in (".jp/g", ".jp\\g", ".jp g"):
            with self.subTest(ext=ext):
                self.assertIsNone(safe_queue_filename("abc123", ext))

    def test_rejects_extension_without_a_leading_dot(self):
        self.assertIsNone(safe_queue_filename("abc123", "jpg"))

    def test_rejects_empty_extension(self):
        self.assertIsNone(safe_queue_filename("abc123", ""))

    def test_rejects_non_hex_hash(self):
        for h in ("../../etc/passwd", "not-hex-zzz", "abc/123", "abc 123"):
            with self.subTest(hash=h):
                self.assertIsNone(safe_queue_filename(h, ".jpg"))

    def test_rejects_non_string_input(self):
        self.assertIsNone(safe_queue_filename(None, ".jpg"))
        self.assertIsNone(safe_queue_filename("abc123", None))
        self.assertIsNone(safe_queue_filename(12345, ".jpg"))

    def test_rejects_absurdly_long_extension(self):
        self.assertIsNone(safe_queue_filename("abc123", "." + "a" * 200))


class TestResolveQueuePath(unittest.TestCase):
    """Tests for resolve_queue_path(): nothing may resolve outside the queue."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.queue = pathlib.Path(self.tmp) / "queue"
        self.queue.mkdir()

    def test_accepts_a_bare_filename(self):
        self.assertIsNotNone(resolve_queue_path("abc.jpg", self.queue))

    def test_rejects_parent_traversal(self):
        self.assertIsNone(resolve_queue_path("../evil.jpg", self.queue))
        self.assertIsNone(resolve_queue_path("sub/../../evil", self.queue))

    def test_rejects_absolute_paths(self):
        self.assertIsNone(resolve_queue_path("/etc/passwd", self.queue))

    def test_rejects_empty(self):
        self.assertIsNone(resolve_queue_path("", self.queue))

    @unittest.skipIf(os.name == 'nt', "symlink creation needs privilege on Windows")
    def test_rejects_symlink_escaping_the_queue(self):
        """A name-only check cannot see this; resolution can."""
        outside = pathlib.Path(self.tmp) / "outside.jpg"
        outside.write_text("x")
        (self.queue / "link.jpg").symlink_to(outside)
        self.assertIsNone(resolve_queue_path("link.jpg", self.queue))


class TestUnsafeEntriesAreNotActedOn(unittest.TestCase):
    """A queue entry naming a path outside the queue must never reach the filesystem."""

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.config.telegram_channel = -100
        self.manager.telegram = MagicMock()
        self.manager.hydrus = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.record_send_failure = MagicMock()
        self.manager.delete_from_queue = MagicMock()
        self.manager.queue_data = {"queue": [{'path': '../../etc/passwd', 'file_id': 1}]}
        self.manager.queue_loaded = True

    def test_entry_is_discarded_without_touching_disk(self):
        with patch('os.remove') as remove, patch('builtins.open') as opened:
            result = self.manager._attempt_post(self.manager.queue_data['queue'][0], 0)

        self.assertFalse(result)
        remove.assert_not_called()
        opened.assert_not_called()
        self.manager.delete_from_queue.assert_not_called()
        self.assertEqual([], self.manager.queue_data['queue'], "the unsafe entry should be gone")


class TestUnsafeHydrusFilenameIsRejected(unittest.TestCase):
    """save_image_to_queue must refuse before writing anything."""

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.queue_data = {"queue": []}
        self.manager.queue_loaded = True
        self.manager.hydrus = MagicMock()
        self.manager.hydrus.hydrus_service_key = {"downloader_tags": "DL"}
        self.manager.telegram = MagicMock()
        self.manager.save_queue = MagicMock()
        self.manager.image_is_queued = MagicMock(return_value=False)

    def test_traversal_extension_is_refused_before_download(self):
        self.manager.hydrus.get_metadata.return_value = {
            'metadata': [{'hash': 'abc123', 'ext': '../../../evil', 'file_id': 1, 'tags': {}}]
        }
        with patch('pathlib.Path.write_bytes') as write:
            result = self.manager.save_image_to_queue(1)

        self.assertIs(QueueResult.FAILED, result)
        write.assert_not_called()
        self.manager.hydrus.get_file_content.assert_not_called()

    def test_non_hex_hash_is_refused(self):
        """
        Pins the name validation specifically.

        This hash stays inside the queue directory, so the path-containment check
        cannot catch it; only safe_queue_filename can.
        """
        self.manager.hydrus.get_metadata.return_value = {
            'metadata': [{'hash': 'zzz-not-hex', 'ext': '.jpg', 'file_id': 1, 'tags': {}}]
        }
        with patch('pathlib.Path.write_bytes') as write:
            self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))
        write.assert_not_called()
        self.manager.hydrus.get_file_content.assert_not_called()

    def test_multi_dot_extension_is_refused(self):
        """Also inside the queue directory, so again only the name check catches it."""
        self.manager.hydrus.get_metadata.return_value = {
            'metadata': [{'hash': 'abc123', 'ext': '.jpg.exe', 'file_id': 1, 'tags': {}}]
        }
        with patch('pathlib.Path.write_bytes') as write:
            self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))
        write.assert_not_called()

    def test_escaping_extension_is_refused_by_containment(self):
        """Pins the second layer: a name that escapes even if the pattern let it by."""
        self.manager.hydrus.get_metadata.return_value = {
            'metadata': [{'hash': 'abc123', 'ext': '.jpg', 'file_id': 1, 'tags': {}}]
        }
        with patch('modules.queue_manager.safe_queue_filename', return_value='../../evil.jpg'), \
             patch('pathlib.Path.write_bytes') as write:
            self.assertIs(QueueResult.FAILED, self.manager.save_image_to_queue(1))
        write.assert_not_called()


class TestCaptionPreservesTagText(unittest.TestCase):
    """
    Tag text must reach the caption unaltered.

    The previous escaping replaced '&' with '+' and the angle brackets with
    lookalike Unicode, so a creator tagged "tom & jerry" was posted as
    "Tom + Jerry". Escaping is reversible; substitution is not.
    """

    @patch.object(QueueManager, '__init__', lambda self, config, queue_file: None)
    def setUp(self):
        self.manager = QueueManager(None, None)
        self.manager.logger = MagicMock()
        self.manager.config = MagicMock()
        self.manager.queue_data = {"queue": []}
        self.manager.queue_loaded = True
        self.manager.hydrus = MagicMock()
        self.manager.hydrus.hydrus_service_key = {"downloader_tags": "DL"}
        self.manager.hydrus.get_file_content.return_value = b"bytes"
        self.manager.save_queue = MagicMock()
        self.manager.image_is_queued = MagicMock(return_value=False)

        # Use the real escaping rather than a stub, since that is what is under test.
        from modules.telegram_manager import TelegramManager
        with patch.object(TelegramManager, '__init__', lambda s, c: None):
            telegram = TelegramManager(None)
        telegram.logger = MagicMock()
        self.manager.telegram = telegram

    def _enqueue(self, tags):
        self.manager.hydrus.get_metadata.return_value = {
            'metadata': [{'hash': 'abc123', 'ext': '.jpg', 'file_id': 1,
                          'tags': {"DL": {"storage_tags": {"0": tags}}}}]
        }
        with patch('pathlib.Path.write_bytes'):
            self.assertIs(QueueResult.ADDED, self.manager.save_image_to_queue(1))
        return self.manager.queue_data['queue'][0]

    def test_ampersand_in_creator_is_escaped_not_mangled(self):
        entry = self._enqueue(["creator:tom & jerry"])
        self.assertIn("&amp;", entry['creator'])
        self.assertNotIn("Tom + Jerry", entry['creator'])
        self.assertIn("Tom &amp; Jerry", entry['creator'])

    def test_creator_text_round_trips(self):
        import html as html_module
        import re as re_module
        entry = self._enqueue(["creator:tom & jerry"])
        # Strip the anchor, then unescape: the original text must come back.
        text = re_module.sub(r'<[^>]+>', '', entry['creator'])
        self.assertEqual("Tom & Jerry", html_module.unescape(text))

    def test_angle_brackets_in_character_are_escaped(self):
        entry = self._enqueue(["character:a <b> c"])
        self.assertIn("&lt;", entry['character'])
        self.assertIn("&gt;", entry['character'])
        self.assertNotIn("≺", entry['character'])

    def test_ampersand_in_the_href_is_percent_encoded(self):
        """The URL goes into an attribute, so it is encoded rather than escaped."""
        entry = self._enqueue(["creator:tom & jerry"])
        href = entry['creator'].split('href="')[1].split('"')[0]
        self.assertIn("%26", href)
        self.assertNotIn("&amp;", href)
        self.assertNotIn(" ", href)

    def test_generated_caption_is_parseable_html(self):
        """A stray bare '&' would make Telegram reject the whole caption."""
        import xml.etree.ElementTree as ElementTree
        entry = self._enqueue(["creator:tom & jerry", "character:a <b> c"])
        fragment = f"<root>{entry['creator']}\n{entry['character']}</root>"
        ElementTree.fromstring(fragment)  # raises if the markup is malformed
