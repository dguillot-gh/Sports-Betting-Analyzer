#!/usr/bin/env python3
"""
Test script for the versioning system
"""

import sys
import os
import requests
import json
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend', 'src'))

def test_version_module():
    """Test the version module directly"""
    print("=== Testing Version Module ===")
    try:
        from version import get_version, get_version_info
        
        version = get_version()
        version_info = get_version_info()
        
        print(f"Version: {version}")
        print(f"Version Info: {json.dumps(version_info, indent=2)}")
        return True
    except Exception as e:
        print(f"Error testing version module: {e}")
        return False

def test_api_endpoints():
    """Test the API endpoints"""
    print("\n=== Testing API Endpoints ===")
    
    base_url = "http://localhost:8000"
    if os.getenv("PYTHON_ML_BASE_URL"):
        base_url = os.getenv("PYTHON_ML_BASE_URL")
    
    endpoints = [
        "/version",
        "/deployments/current",
        "/deployments/register-simple"
    ]
    
    results = {}
    
    for endpoint in endpoints:
        try:
            url = f"{base_url}{endpoint}"
            print(f"Testing {url}...")
            
            if endpoint == "/deployments/register-simple":
                response = requests.post(url, timeout=5)
            else:
                response = requests.get(url, timeout=5)
            
            results[endpoint] = {
                "status": response.status_code,
                "success": response.status_code < 400,
                "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text[:200]
            }
            
            print(f"  Status: {response.status_code}")
            if response.headers.get("content-type", "").startswith("application/json"):
                print(f"  Response: {json.dumps(response.json(), indent=4)}")
            
        except requests.exceptions.ConnectionError:
            print(f"  Connection failed - service may not be running")
            results[endpoint] = {"status": "connection_error", "success": False}
        except Exception as e:
            print(f"  Error: {e}")
            results[endpoint] = {"status": "error", "success": False, "error": str(e)}
    
    return results

def test_database_schema():
    """Test database schema (if available)"""
    print("\n=== Testing Database Schema ===")
    
    try:
        # Try to connect to the database
        import asyncpg
        import asyncio
        
        async def test_db():
            try:
                conn = await asyncpg.connect(
                    host="localhost",
                    port=5432,
                    user="sports_user",
                    password="sportsbetting2024",
                    database="sports_betting"
                )
                
                # Check if deployment tables exist
                tables = await conn.fetch("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name IN ('deployments', 'deployment_components', 'deployment_rollbacks')
                """)
                
                table_names = [row['table_name'] for row in tables]
                print(f"Deployment tables found: {table_names}")
                
                if len(table_names) == 3:
                    print("✅ All deployment tracking tables are present")
                    
                    # Check current deployments
                    deployments = await conn.fetch("SELECT COUNT(*) as count FROM deployments")
                    print(f"Total deployments in database: {deployments[0]['count']}")
                    
                    return True
                else:
                    print("❌ Missing deployment tracking tables")
                    return False
                    
            except Exception as e:
                print(f"Database connection error: {e}")
                return False
            finally:
                try:
                    await conn.close()
                except:
                    pass
        
        return asyncio.run(test_db())
        
    except ImportError:
        print("Database libraries not available - skipping database test")
        return None

def main():
    """Run all tests"""
    print("Sports Betting Analyzer - Version System Test")
    print("=" * 50)
    print(f"Test started at: {datetime.now().isoformat()}")
    
    # Test version module
    version_test = test_version_module()
    
    # Test API endpoints
    api_results = test_api_endpoints()
    
    # Test database schema
    db_test = test_database_schema()
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    
    print(f"Version Module: {'✅ PASS' if version_test else '❌ FAIL'}")
    
    if api_results:
        for endpoint, result in api_results.items():
            status = "✅ PASS" if result.get("success") else "❌ FAIL"
            print(f"API {endpoint}: {status}")
    
    if db_test is not None:
        print(f"Database Schema: {'✅ PASS' if db_test else '❌ FAIL'}")
    else:
        print("Database Schema: ⚠️  SKIPPED")
    
    print(f"\nTest completed at: {datetime.now().isoformat()}")

if __name__ == "__main__":
    main()
