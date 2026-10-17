# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""回归检查：英文系统区域设置下仍可生成中文日期。"""

import locale
import unittest
from datetime import datetime
from unittest.mock import patch

from kag.common import utils


class RuntimeCompatibilityTests(unittest.TestCase):
    def test_date_format_in_c_locale(self):
        previous = locale.setlocale(locale.LC_TIME)
        try:
            locale.setlocale(locale.LC_TIME, "C")
            with patch.object(utils.datetime, "datetime") as clock:
                clock.now.return_value = datetime(2026, 10, 17)
                self.assertEqual(utils.get_now("zh"), "2026年10月17日 (周六)")
                self.assertEqual(utils.get_now("en"), "2026-10-17 (Saturday)")
                with self.assertRaises(ValueError):
                    utils.get_now("unknown")
        finally:
            locale.setlocale(locale.LC_TIME, previous)
