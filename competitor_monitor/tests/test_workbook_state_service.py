import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from excel_service import WorkbookLockedError
from workbook_state_service import WorkbookStateService


class WorkbookStateServiceTest(unittest.TestCase):
    def test_initial_status_uses_primary_workbook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "竞品监控.xlsx"
            primary.write_bytes(b"primary")
            service = WorkbookStateService(base_dir=base_dir)

            payload = service.status_payload(primary)

            self.assertEqual(payload["workbook_sync_status"], "synced")
            self.assertEqual(Path(payload["active_workbook_path"]), primary.resolve())
            self.assertEqual(Path(payload["primary_workbook_path"]), primary.resolve())
            self.assertEqual(payload["run_workbook_count"], 0)
            self.assertEqual(service.get_active_workbook_path(primary), primary.resolve())

    def test_mark_pending_sync_persists_active_workbook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "竞品监控.xlsx"
            active = base_dir / "output" / "latest" / "竞品监控.xlsx"
            primary.write_bytes(b"old")
            active.parent.mkdir(parents=True)
            active.write_bytes(b"new")
            service = WorkbookStateService(base_dir=base_dir)

            service.mark_pending_sync(active, primary, "locked")
            reloaded = WorkbookStateService(base_dir=base_dir)
            payload = reloaded.status_payload(primary)

            self.assertEqual(payload["workbook_sync_status"], "pending_sync")
            self.assertEqual(Path(payload["active_workbook_path"]), active.resolve())
            self.assertEqual(Path(payload["pending_sync_path"]), active.resolve())
            self.assertEqual(payload["last_workbook_sync_error"], "locked")

    def test_missing_cross_machine_active_path_resets_to_primary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "\u7ade\u54c1\u76d1\u63a7.xlsx"
            stale_active = Path("G:/old-machine/output/latest/\u7ade\u54c1\u76d1\u63a7.xlsx")
            primary.write_bytes(b"primary")
            service = WorkbookStateService(base_dir=base_dir)
            service.mark_pending_sync(stale_active, primary, "old machine path")

            payload = service.status_payload(primary)

            self.assertEqual(payload["workbook_sync_status"], "synced")
            self.assertEqual(Path(payload["active_workbook_path"]), primary.resolve())
            self.assertIsNone(payload["pending_sync_path"])
            self.assertEqual(service.get_active_workbook_path(primary), primary.resolve())

    def test_state_write_does_not_use_shared_fixed_tmp_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "绔炲搧鐩戞帶.xlsx"
            primary.write_bytes(b"primary")
            service = WorkbookStateService(base_dir=base_dir)
            original_replace = Path.replace

            def reject_shared_tmp(path, target):
                if path.name == "workbook_state.json.tmp":
                    raise PermissionError("shared tmp collision")
                return original_replace(path, target)

            with patch.object(Path, "replace", reject_shared_tmp):
                service.mark_synced(primary)

            self.assertEqual(service.status_payload(primary)["workbook_sync_status"], "synced")

    def test_try_sync_latest_to_primary_copies_active_and_deletes_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "竞品监控.xlsx"
            latest = base_dir / "output" / "latest" / "竞品监控.xlsx"
            primary.write_bytes(b"old")
            latest.parent.mkdir(parents=True)
            latest.write_bytes(b"new")
            service = WorkbookStateService(base_dir=base_dir)
            service.mark_pending_sync(latest, primary, "locked")

            result = service.try_sync_latest_to_primary(primary)

            self.assertEqual(result["sync_status"], "synced")
            self.assertEqual(primary.read_bytes(), b"new")
            self.assertFalse(latest.exists())
            self.assertEqual(service.get_active_workbook_path(primary), primary.resolve())

    def test_sync_failure_keeps_pending_workbook_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "竞品监控.xlsx"
            latest = base_dir / "output" / "latest" / "竞品监控.xlsx"
            primary.write_bytes(b"old")
            latest.parent.mkdir(parents=True)
            latest.write_bytes(b"new")
            service = WorkbookStateService(base_dir=base_dir)
            service.mark_pending_sync(latest, primary, "locked")

            with patch(
                "workbook_state_service.ExcelService._replace_file_with_retry",
                side_effect=WorkbookLockedError("still locked"),
            ):
                result = service.try_sync_latest_to_primary(primary)

            self.assertEqual(result["sync_status"], "pending_sync")
            self.assertIn("still locked", result["error"])
            self.assertEqual(primary.read_bytes(), b"old")
            self.assertEqual(service.get_active_workbook_path(primary), latest.resolve())

    def test_prepare_active_for_run_copies_locked_active_to_run_workbook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "竞品监控.xlsx"
            latest = base_dir / "output" / "latest" / "竞品监控.xlsx"
            primary.write_bytes(b"old")
            latest.parent.mkdir(parents=True)
            latest.write_bytes(b"new")
            service = WorkbookStateService(base_dir=base_dir)
            service.mark_pending_sync(latest, primary, "locked")

            with patch(
                "workbook_state_service.ExcelService.assert_workbook_writable",
                side_effect=WorkbookLockedError("active locked"),
            ):
                run_path = service.prepare_active_for_run(primary)

            self.assertIn("output", run_path.parts)
            self.assertIn("runs", run_path.parts)
            self.assertEqual(run_path.read_bytes(), b"new")
            self.assertEqual(service.get_active_workbook_path(primary), run_path.resolve())

    def test_cleanup_runs_keeps_active_pending_and_recent_copies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            primary = base_dir / "竞品监控.xlsx"
            primary.write_bytes(b"primary")
            runs_dir = base_dir / "output" / "runs"
            runs_dir.mkdir(parents=True)
            run_paths = []
            for index in range(12):
                path = runs_dir / f"竞品监控_20260707_15{index:02d}00.xlsx"
                path.write_bytes(str(index).encode("ascii"))
                os.utime(path, (index, index))
                run_paths.append(path)
            service = WorkbookStateService(base_dir=base_dir)
            service.mark_pending_sync(run_paths[0], primary, "locked")

            service.cleanup_runs(primary, keep=10)

            remaining = sorted(runs_dir.glob("*.xlsx"))
            self.assertIn(run_paths[0], remaining)
            self.assertEqual(len(remaining), 11)
            self.assertFalse(run_paths[1].exists())


if __name__ == "__main__":
    unittest.main()
