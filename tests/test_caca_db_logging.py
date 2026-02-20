import unittest
import asyncio
from unittest.mock import patch
import utils.caca_db as caca_db
import logging

class TestCacaDBLogging(unittest.TestCase):
    def test_reload_modes_logs_error(self):
        # Setup logger to capture logs
        logger = logging.getLogger('utils.caca_db')

        with patch('utils.caca_db._caca_db_load_modes', side_effect=Exception("Database error")):
             with self.assertLogs(logger, level='ERROR') as cm:
                 asyncio.run(caca_db.reload_modes())

             self.assertTrue(any("Error reloading modes" in o for o in cm.output))
             self.assertTrue(any("Database error" in o for o in cm.output))

    def test_load_groups_logs_error(self):
        # Setup logger to capture logs
        logger = logging.getLogger('utils.caca_db')

        with patch('utils.caca_db._caca_db_load_groups', side_effect=Exception("Group load error")):
             with self.assertLogs(logger, level='ERROR') as cm:
                 caca_db.load_groups()

             self.assertTrue(any("Error loading groups" in o for o in cm.output))
             self.assertTrue(any("Group load error" in o for o in cm.output))

if __name__ == '__main__':
    unittest.main()
