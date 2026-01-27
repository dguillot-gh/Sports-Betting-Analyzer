import asyncio
import unittest
from unittest.mock import patch, MagicMock
from scripts.college_baseball_importer import run_college_baseball_import

class TestCollegeBaseballImporterRefactor(unittest.IsolatedAsyncioTestCase):
    
    @patch('scripts.college_baseball_importer._import_via_python')
    @patch('scripts.college_baseball_importer._import_via_r')
    @patch('scripts.college_baseball_importer.sync_to_postgresql')
    async def test_bulk_import_logic(self, mock_sync, mock_r, mock_python):
        """Verify that division=0 triggers all divisions and merges results."""
        
        # Mock successful Python import for all divisions
        mock_python.return_value = {"success": True, "total_teams": 10}
        mock_r.return_value = {"success": False} # Not needed if Python succeeds in 'auto' mode
        mock_sync.return_value = None
        
        # Run bulk import
        result = await run_college_baseball_import(division=0, year=2024, source="auto")
        
        # Verify result structure
        self.assertTrue(result["success"])
        self.assertEqual(result["divisions"], [1, 2, 3])
        self.assertEqual(result["total_teams"], 30) # 10 * 3
        self.assertTrue(result["synced_to_db"])
        
        # Verify mock calls
        self.assertEqual(mock_python.call_count, 3)
        self.assertEqual(mock_sync.call_count, 3)
        
        # Verify divisions were passed correctly
        called_divisions = [call.args[0] for call in mock_python.call_args_list]
        self.assertEqual(called_divisions, [1, 2, 3])

    @patch('scripts.college_baseball_importer._import_via_python')
    @patch('scripts.college_baseball_importer._import_via_r')
    @patch('scripts.college_baseball_importer.sync_to_postgresql')
    async def test_single_division_import(self, mock_sync, mock_r, mock_python):
        """Verify that specific division import still works."""
        
        mock_python.return_value = {"success": True, "total_teams": 5}
        mock_sync.return_value = None
        
        result = await run_college_baseball_import(division=2, year=2024, source="python")
        
        self.assertTrue(result["success"])
        self.assertEqual(result["divisions"], [2])
        self.assertEqual(result["total_teams"], 5)
        self.assertEqual(mock_python.call_count, 1)
        self.assertEqual(mock_python.call_args[0][0], 2)

if __name__ == "__main__":
    unittest.main()
