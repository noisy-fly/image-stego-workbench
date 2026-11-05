import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from app import Main
from update_ui import UpdateController


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_ignore_persists_and_manual_check_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            settings_file = str(Path(temp) / 'settings.ini')
            settings = QSettings(settings_file, QSettings.Format.IniFormat)
            window = Main(); controller = UpdateController(window, settings); info = {'tag': 'v99.0.0'}
            def ignore():
                box = window.findChild(QMessageBox)
                next(b for b in box.buttons() if b.text() == '忽略此版本').click()
            QTimer.singleShot(10, ignore); controller.offer(info)
            saved = QSettings(settings_file, QSettings.Format.IniFormat)
            self.assertEqual(saved.value('ignored_release'), 'v99.0.0')
            with patch.object(controller, 'offer') as offer:
                controller.manual_pending = False; controller.checked(info, '')
                offer.assert_not_called()
                controller.manual_pending = True; controller.checked(info, '')
                offer.assert_called_once_with(info)
                offer.reset_mock(); controller.manual_pending = False; controller.checked({'tag':'v99.1.0'}, '')
                offer.assert_called_once()
            window.close()

    def test_manual_request_during_background_check(self):
        window = Main(); controller = UpdateController(window)
        controller.checking = True; controller.manual_pending = False
        controller.check(manual=True)
        self.assertTrue(controller.manual_pending)
        window.close()

    def test_offline_manual_reports_and_background_is_quiet(self):
        window = Main(); controller = UpdateController(window)
        with patch('update_ui.QMessageBox.warning') as warning:
            controller.manual_pending = False; controller.checked(None, '网络超时')
            warning.assert_not_called()
            controller.manual_pending = True; controller.checked(None, '网络超时')
            warning.assert_called_once()
        window.close()

    def test_validated_installer_launches_and_closes_app(self):
        window = Main(); controller = UpdateController(window)
        with patch('update_ui.QProcess.startDetached', return_value=(True, 123)) as launch, patch.object(window, 'close') as close:
            controller.downloaded('C:/temp/verified.exe', '')
            launch.assert_called_once_with('C:/temp/verified.exe', [])
            close.assert_called_once()
        window.close()


if __name__ == '__main__': unittest.main()
