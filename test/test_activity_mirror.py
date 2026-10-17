import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge/device-runtime"))
import device_activity


@unittest.skipUnless(os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0,
                     "requires root POSIX descriptor operations")
class ActivityMirrorFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "MessageCenterActivity/runtime.activity.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_creates_only_owned_final_directory_and_atomic_readable_file(self):
        os.chown(self.root, 501, 501)
        device_activity._atomic_mirror_state_write(str(self.path), {"generation": 1})
        self.assertEqual(json.loads(self.path.read_text()), {"generation": 1})
        self.assertEqual(self.path.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        self.assertEqual(self.path.parent.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o755)
        device_activity._atomic_mirror_state_write(str(self.path), {"generation": 2})
        self.assertEqual(json.loads(self.path.read_text()), {"generation": 2})
        self.assertEqual([item.name for item in self.path.parent.iterdir()], [self.path.name])

    def test_rejects_existing_wrong_owner_or_mode_without_chmod(self):
        self.path.parent.mkdir(mode=0o755)
        os.chmod(self.path.parent, 0o755)
        os.chown(self.path.parent, 501, 501)
        with self.assertRaises(device_activity.ActivityStateError):
            device_activity._atomic_mirror_state_write(str(self.path), {})
        self.assertEqual(self.path.parent.stat().st_uid, 501)
        self.assertFalse(self.path.exists())
        os.chown(self.path.parent, 0, 0)
        os.chmod(self.path.parent, 0o777)
        with self.assertRaises(device_activity.ActivityStateError):
            device_activity._atomic_mirror_state_write(str(self.path), {})
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o777)

    def test_rejects_ancestor_symlink_and_existing_target_symlink(self):
        real = self.root / "real"
        real.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            device_activity._atomic_mirror_state_write(
                str(alias / "MessageCenterActivity/runtime.activity.json"), {})
        self.assertFalse((real / "MessageCenterActivity").exists())
        self.path.parent.mkdir(mode=0o755)
        os.chmod(self.path.parent, 0o755)
        protected = self.root / "protected"
        protected.write_text("preserved")
        self.path.symlink_to(protected)
        with self.assertRaises(device_activity.ActivityStateError):
            device_activity._atomic_mirror_state_write(str(self.path), {})
        self.assertEqual(protected.read_text(), "preserved")

    def test_parent_rename_race_cannot_redirect_write_outside_open_directory(self):
        device_activity._atomic_mirror_state_write(str(self.path), {"generation": 1})
        original = self.path.parent
        renamed = self.root / "old"
        outside = self.root / "outside"
        outside.mkdir()
        real_replace = os.replace

        def switch_parent(source, target, **kwargs):
            original.rename(renamed)
            original.symlink_to(outside, target_is_directory=True)
            return real_replace(source, target, **kwargs)

        with patch.object(device_activity.os, "replace", side_effect=switch_parent):
            device_activity._atomic_mirror_state_write(str(self.path), {"generation": 2})
        self.assertFalse((outside / self.path.name).exists())
        self.assertEqual(json.loads((renamed / self.path.name).read_text()), {"generation": 2})

    def test_missing_library_is_not_created(self):
        missing = self.root / "missing/MessageCenterActivity/runtime.activity.json"
        with self.assertRaises(FileNotFoundError):
            device_activity._atomic_mirror_state_write(str(missing), {})
        self.assertFalse((self.root / "missing").exists())


if __name__ == "__main__":
    unittest.main()
