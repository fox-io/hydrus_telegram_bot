import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.file_manager import FileManager


class FileManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'queue.json')
        self.manager = FileManager.__new__(FileManager)
        self.manager.logger = MagicMock()

    def _leftovers(self):
        return [n for n in os.listdir(self.tmp) if n != 'queue.json']


class TestAtomicWrite(FileManagerTestCase):
    """
    Tests for FileManager.atomic_write().

    Writing in place truncated the file on open, so an interrupted write left a
    fragment that is not valid JSON. operation() then treated it as corrupt and
    recreated it from the caller's default, silently replacing the whole queue
    index with an empty one while the media stayed on disk as orphans.
    """

    def test_writes_the_payload(self):
        self.manager.atomic_write(self.path, {'queue': [{'path': 'a.jpg'}]})
        self.assertEqual({'queue': [{'path': 'a.jpg'}]}, json.load(open(self.path)))

    def test_overwrites_existing_content(self):
        Path(self.path).write_text('{"queue": [{"path": "old.jpg"}]}')
        self.manager.atomic_write(self.path, {'queue': [{'path': 'new.jpg'}]})
        self.assertEqual('new.jpg', json.load(open(self.path))['queue'][0]['path'])

    def test_leaves_no_temporary_file(self):
        self.manager.atomic_write(self.path, {'queue': []})
        self.assertEqual([], self._leftovers())

    def test_original_survives_a_failed_write(self):
        """The property the whole change exists for."""
        original = {'queue': [{'path': f'{i}.jpg'} for i in range(100)]}
        Path(self.path).write_text(json.dumps(original))

        def dies_partway(obj, fp, *a, **kw):
            fp.write('{"queue": [{"pa')
            raise KeyboardInterrupt("power loss")

        with patch('modules.file_manager.json.dump', dies_partway):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.atomic_write(self.path, {'queue': []})

        self.assertEqual(original, json.load(open(self.path)))

    def test_temporary_file_is_cleaned_up_after_failure(self):
        Path(self.path).write_text('{"queue": []}')
        with patch('modules.file_manager.json.dump', side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.manager.atomic_write(self.path, {'queue': []})
        self.assertEqual([], self._leftovers())

    def test_temporary_file_is_created_beside_the_target(self):
        """A rename is only atomic within one filesystem."""
        seen = {}
        real = tempfile.mkstemp

        def record(*args, **kwargs):
            seen['dir'] = kwargs.get('dir')
            return real(*args, **kwargs)

        with patch('modules.file_manager.tempfile.mkstemp', record):
            self.manager.atomic_write(self.path, {'queue': []})

        self.assertEqual(Path(self.tmp), Path(seen['dir']))

    def test_contents_are_flushed_before_the_rename(self):
        """Renaming a file whose bytes are still buffered would defeat the point."""
        with patch('modules.file_manager.os.fsync') as fsync:
            self.manager.atomic_write(self.path, {'queue': []})
        fsync.assert_called_once()

    def test_creates_a_file_that_did_not_exist(self):
        target = os.path.join(self.tmp, 'new.json')
        self.manager.atomic_write(target, {'queue': []})
        self.assertTrue(os.path.exists(target))

    def test_unicode_survives(self):
        self.manager.atomic_write(self.path, {'queue': [{'title': 'ロボット'}]})
        self.assertEqual('ロボット', json.load(open(self.path))['queue'][0]['title'])


class TestReplaceRetries(FileManagerTestCase):
    """
    os.replace is atomic on both platforms but can fail transiently on Windows
    when a scanner or indexer holds the destination open.
    """

    def test_retries_a_transient_permission_error(self):
        calls = []
        real_replace = os.replace   # captured before patching, or flaky recurses

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("locked by another process")
            real_replace(src, dst)

        with patch('modules.file_manager.os.replace', flaky), \
             patch('modules.file_manager.time.sleep'):
            self.manager.atomic_write(self.path, {'queue': [{'path': 'a.jpg'}]})

        self.assertEqual(3, len(calls))
        self.assertEqual('a.jpg', json.load(open(self.path))['queue'][0]['path'])

    def test_gives_up_eventually(self):
        with patch('modules.file_manager.os.replace', side_effect=PermissionError("locked")), \
             patch('modules.file_manager.time.sleep'):
            with self.assertRaises(PermissionError):
                self.manager.atomic_write(self.path, {'queue': []})
        self.assertEqual([], self._leftovers(), "the temporary file must still be cleaned up")


class TestOperationStillWorks(FileManagerTestCase):
    """The public contract of operation() is unchanged."""

    def test_round_trip(self):
        self.manager.operation(self.path, 'w+', {'queue': [{'path': 'a.jpg'}]})
        self.assertEqual({'queue': [{'path': 'a.jpg'}]}, self.manager.operation(self.path, 'r'))

    def test_write_returns_none(self):
        self.assertIsNone(self.manager.operation(self.path, 'w+', {'queue': []}))

    def test_missing_file_is_created_from_the_default(self):
        result = self.manager.operation(self.path, 'r', {'queue': []})
        self.assertEqual({'queue': []}, result)
        self.assertTrue(os.path.exists(self.path))

    def test_corrupt_file_is_recreated_from_the_default(self):
        Path(self.path).write_text('{"queue": [{"pa')
        self.assertEqual({'queue': []}, self.manager.operation(self.path, 'r', {'queue': []}))

    def test_read_without_default_returns_none_when_missing(self):
        self.assertIsNone(self.manager.operation(self.path, 'r'))

    def test_operation_write_survives_an_interruption(self):
        """
        Pins the guarantee at the entry point the queue actually calls.

        Testing atomic_write() alone is not enough: operation() could still write
        in place and every atomic_write test would keep passing.
        """
        original = {'queue': [{'path': f'{i}.jpg'} for i in range(100)]}
        Path(self.path).write_text(json.dumps(original))

        def dies_partway(obj, fp, *a, **kw):
            fp.write('{"queue": [{"pa')
            raise KeyboardInterrupt("power loss")

        with patch('modules.file_manager.json.dump', dies_partway):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.operation(self.path, 'w+', {'queue': []})

        self.assertEqual(original, json.load(open(self.path)),
                         "an interrupted operation() write must leave the original intact")
        self.assertEqual([], self._leftovers())

    def test_operation_write_goes_through_atomic_write(self):
        with patch.object(self.manager, 'atomic_write') as atomic:
            self.manager.operation(self.path, 'w+', {'queue': []})
        atomic.assert_called_once()

    def test_recovery_write_goes_through_atomic_write(self):
        """The corrupt-file recovery path writes too, and must be atomic as well."""
        Path(self.path).write_text('{"queue": [{"pa')
        with patch.object(self.manager, 'atomic_write') as atomic:
            self.manager.operation(self.path, 'r', {'queue': []})
        atomic.assert_called_once()
