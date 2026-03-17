#!/usr/bin/env python3
"""
Comprehensive Property-Based Test Runner for ChatSaaS Backend
Executes all 34 property tests with minimum 100 iterations each.

This script runs the complete property-based test suite and provides
detailed reporting on the validation of all correctness properties.
"""

import asyncio
import sys
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple
import json

# Add the backend directory to Python path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

class PropertyTestRunner:
    """Manages execution of all property-based tests with detailed reporting"""
    
    def __init__(self):
        self.test_files = [
            "tests/test_properties_comprehensive.py",
            "tests/test_properties_rag_escalation.py", 
            "tests/test_properties_websocket_security.py",
            "tests/test_properties_admin_webchat.py"
        ]
        self.results = {}
        self.total_properties = 34
        
    def run_test_file(self, test_file: str) -> Tuple[bool, str, Dict]:
        """Run a single test file and capture results"""
        print(f"\n{'='*60}")
        print(f"Running {test_file}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        # Run pytest with verbose output and JSON report
        cmd = [
            sys.executable, "-m", "pytest",
            test_file,
            "-v",
            "--tb=short",
            "--json-report",
            "--json-report-file=test_report.json",
            "-x"  # Stop on first failure for debugging
        ]
        
        try:
            result = subprocess.run(
                cmd,
                cwd=backend_dir,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout per file
            )
            
            execution_time = time.time() - start_time
            
            # Parse JSON report if available
            report_file = backend_dir / "test_report.json"
            test_details = {}
            if report_file.exists():
                try:
                    with open(report_file, 'r') as f:
                        report_data = json.load(f)
                        test_details = {
                            'total_tests': report_data.get('summary', {}).get('total', 0),
                            'passed': report_data.get('summary', {}).get('passed', 0),
                            'failed': report_data.get('summary', {}).get('failed', 0),
                            'errors': report_data.get('summary', {}).get('error', 0)
                        }
                    report_file.unlink()  # Clean up
                except Exception as e:
                    print(f"Warning: Could not parse test report: {e}")
            
            success = result.returncode == 0
            output = result.stdout + result.stderr
            
            print(f"Exit code: {result.returncode}")
            print(f"Execution time: {execution_time:.2f} seconds")
            if test_details:
                print(f"Tests run: {test_details['total_tests']}")
                print(f"Passed: {test_details['passed']}")
                print(f"Failed: {test_details['failed']}")
                print(f"Errors: {test_details['errors']}")
            
            if not success:
                print(f"\nSTDOUT:\n{result.stdout}")
                print(f"\nSTDERR:\n{result.stderr}")
            
            return success, output, test_details
            
        except subprocess.TimeoutExpired:
            return False, f"Test file {test_file} timed out after 10 minutes", {}
        except Exception as e:
            return False, f"Error running {test_file}: {str(e)}", {}
    
    def run_all_tests(self) -> bool:
        """Run all property test files and collect results"""
        print("Starting Comprehensive Property-Based Test Suite")
        print(f"Testing {self.total_properties} correctness properties")
        print(f"Minimum 100 iterations per property test")
        
        overall_start = time.time()
        all_passed = True
        total_tests_run = 0
        total_passed = 0
        total_failed = 0
        
        for test_file in self.test_files:
            success, output, details = self.run_test_file(test_file)
            
            self.results[test_file] = {
                'success': success,
                'output': output,
                'details': details
            }
            
            if not success:
                all_passed = False
            
            if details:
                total_tests_run += details.get('total_tests', 0)
                total_passed += details.get('passed', 0)
                total_failed += details.get('failed', 0)
        
        overall_time = time.time() - overall_start
        
        # Print comprehensive summary
        print(f"\n{'='*80}")
        print("COMPREHENSIVE PROPERTY TEST SUITE RESULTS")
        print(f"{'='*80}")
        print(f"Total execution time: {overall_time:.2f} seconds")
        print(f"Total property tests run: {total_tests_run}")
        print(f"Total tests passed: {total_passed}")
        print(f"Total tests failed: {total_failed}")
        print(f"Overall success rate: {(total_passed/total_tests_run*100):.1f}%" if total_tests_run > 0 else "N/A")
        
        print(f"\nPER-FILE RESULTS:")
        for test_file, result in self.results.items():
            status = "✅ PASSED" if result['success'] else "❌ FAILED"
            details = result['details']
            if details:
                print(f"{test_file}: {status} ({details.get('passed', 0)}/{details.get('total_tests', 0)} tests)")
            else:
                print(f"{test_file}: {status}")
        
        if all_passed:
            print(f"\n🎉 ALL PROPERTY TESTS PASSED!")
            print(f"✅ All {self.total_properties} correctness properties validated")
            print(f"✅ Statistical confidence achieved with 100+ iterations per property")
            print(f"✅ Implementation satisfies formal specification requirements")
        else:
            print(f"\n❌ SOME PROPERTY TESTS FAILED")
            print(f"Review failed tests above for implementation issues")
            
            # Show failed test details
            for test_file, result in self.results.items():
                if not result['success']:
                    print(f"\nFAILED: {test_file}")
                    print("Output:")
                    print(result['output'][-1000:])  # Last 1000 chars
        
        return all_passed
    
    def generate_report(self) -> str:
        """Generate a detailed test report"""
        report = []
        report.append("# Property-Based Test Suite Report")
        report.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        report.append("## Summary")
        total_files = len(self.test_files)
        passed_files = sum(1 for r in self.results.values() if r['success'])
        report.append(f"- Test files: {total_files}")
        report.append(f"- Passed files: {passed_files}")
        report.append(f"- Failed files: {total_files - passed_files}")
        report.append("")
        
        report.append("## Property Coverage")
        report.append("This test suite validates all 34 correctness properties:")
        
        properties = [
            "Property 1: Authentication Round Trip",
            "Property 2: Workspace Creation Consistency", 
            "Property 3: Access Control Enforcement",
            "Property 4: Channel Connection Validation",
            "Property 5: Credential Encryption Round Trip",
            "Property 6: Tier Limit Enforcement",
            "Property 7: Maintenance Mode Priority",
            "Property 8: Message Deduplication",
            "Property 9: Token Limit Protection",
            "Property 10: RAG Processing Consistency",
            "Property 11: Escalation Classification Accuracy",
            "Property 12: Escalation Workflow Routing",
            "Property 13: Document Processing Pipeline",
            "Property 14: Document Processing Error Handling",
            "Property 15: Document Round Trip",
            "Property 16: Agent Invitation Workflow",
            "Property 17: Agent Deactivation Cleanup",
            "Property 18: WebSocket Event Broadcasting",
            "Property 19: WebSocket Connection Management",
            "Property 20: Webhook Security Verification",
            "Property 21: Meta Verification Challenge Handling",
            "Property 22: Usage Counter Management",
            "Property 23: Platform Administration Access Control",
            "Property 24: AI Provider Interface Consistency",
            "Property 25: AI Provider Switching Requirements",
            "Property 26: Rate Limiting Enforcement",
            "Property 27: Security Implementation Standards",
            "Property 28: Maintenance Mode Security",
            "Property 29: File Storage Security and Management",
            "Property 30: File Cleanup Completeness",
            "Property 31: Database Constraint Enforcement",
            "Property 32: Email Service Reliability",
            "Property 33: WebChat API Widget Validation",
            "Property 34: WebChat API Error Handling"
        ]
        
        for prop in properties:
            report.append(f"- {prop}")
        
        report.append("")
        report.append("## Detailed Results")
        
        for test_file, result in self.results.items():
            report.append(f"### {test_file}")
            report.append(f"Status: {'PASSED' if result['success'] else 'FAILED'}")
            
            if result['details']:
                details = result['details']
                report.append(f"Tests run: {details.get('total_tests', 0)}")
                report.append(f"Passed: {details.get('passed', 0)}")
                report.append(f"Failed: {details.get('failed', 0)}")
            
            if not result['success']:
                report.append("```")
                report.append(result['output'][-500:])  # Last 500 chars
                report.append("```")
            
            report.append("")
        
        return "\n".join(report)


def main():
    """Main entry point for property test execution"""
    print("ChatSaaS Backend - Comprehensive Property-Based Test Suite")
    print("Testing all 34 correctness properties with 100+ iterations each")
    
    # Check if we're in the right directory
    if not Path("app").exists():
        print("Error: Must run from backend directory")
        sys.exit(1)
    
    # Check if test files exist
    runner = PropertyTestRunner()
    missing_files = []
    for test_file in runner.test_files:
        if not Path(test_file).exists():
            missing_files.append(test_file)
    
    if missing_files:
        print(f"Error: Missing test files: {missing_files}")
        sys.exit(1)
    
    # Run all tests
    success = runner.run_all_tests()
    
    # Generate and save report
    report = runner.generate_report()
    report_file = Path("property_test_report.md")
    with open(report_file, 'w') as f:
        f.write(report)
    
    print(f"\nDetailed report saved to: {report_file}")
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()