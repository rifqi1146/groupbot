import os
import sqlite3
import unittest
from handlers import welcome

# Helper to mock DB path
TEST_DB_PATH = "test_welcome_verify.sqlite3"

class TestWelcomeDB(unittest.TestCase):
    def setUp(self):
        # Override the DB path in the module for testing
        self.original_db_path = welcome.WELCOME_VERIFY_DB
        welcome.WELCOME_VERIFY_DB = os.path.abspath(TEST_DB_PATH)

        # Clean up previous test run
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    def tearDown(self):
        # Restore DB path
        welcome.WELCOME_VERIFY_DB = self.original_db_path

        # Clean up
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

    def test_init_db_creates_tables(self):
        # Call init
        welcome.init_welcome_db()

        con = sqlite3.connect(TEST_DB_PATH)
        cursor = con.cursor()

        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}

        self.assertIn('welcome_chats', tables)
        self.assertIn('verified_users', tables)
        self.assertIn('pending_welcome', tables)

        con.close()

    def test_load_save_welcome_chats(self):
        welcome.init_welcome_db()

        welcome.WELCOME_ENABLED_CHATS = {123, 456}
        welcome.save_welcome_chats()

        # Clear memory
        welcome.WELCOME_ENABLED_CHATS = set()

        welcome.load_welcome_chats()
        self.assertEqual(welcome.WELCOME_ENABLED_CHATS, {123, 456})

    def test_verify_user_flow(self):
        welcome.init_welcome_db()

        chat_id = 100
        user_id = 200

        welcome.save_verified_user(chat_id, user_id)

        welcome.VERIFIED_USERS = {}
        welcome.load_verified()

        self.assertIn(chat_id, welcome.VERIFIED_USERS)
        self.assertIn(user_id, welcome.VERIFIED_USERS[chat_id])

    def test_save_fails_without_init(self):
        # Ensure DB does not exist
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

        welcome.WELCOME_ENABLED_CHATS = {123}

        # Should raise OperationalError because table doesn't exist
        with self.assertRaises(sqlite3.OperationalError):
            welcome.save_welcome_chats()

if __name__ == '__main__':
    unittest.main()
