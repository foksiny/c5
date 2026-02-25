#!/usr/bin/env python3
"""
Test runner for C5 example files.
Compiles and executes all .c5 files in the examples directory.
"""

import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

# Colors for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def colorize(text, color):
    """Apply color to text if terminal supports it."""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.END}"
    return text

def find_c5_files(examples_dir):
    """Find all .c5 files in the examples directory, excluding subdirectories like lib_test."""
    c5_files = []
    for item in os.listdir(examples_dir):
        item_path = os.path.join(examples_dir, item)
        if os.path.isfile(item_path) and item.endswith('.c5'):
            c5_files.append(item_path)
    return sorted(c5_files)

def compile_c5_file(c5_file, output_binary):
    """Compile a .c5 file to an executable binary."""
    result = subprocess.run(
        [sys.executable, "-m", "c5c.main", c5_file, "-o", output_binary],
        capture_output=True,
        text=True
    )
    return result

def run_binary(binary_path, timeout=5):
    """Run the compiled binary and capture output."""
    try:
        result = subprocess.run(
            [binary_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result, None
    except subprocess.TimeoutExpired:
        return None, "Timeout expired"
    except Exception as e:
        return None, str(e)

def test_example(c5_file, temp_dir):
    """Test a single .c5 file."""
    filename = os.path.basename(c5_file)
    binary_name = os.path.splitext(filename)[0]
    binary_path = os.path.join(temp_dir, binary_name)
    
    result = {
        "file": filename,
        "compile_success": False,
        "run_success": False,
        "compile_output": "",
        "runtime_output": "",
        "runtime_error": "",
        "exit_code": None
    }
    
    # Compile
    compile_result = compile_c5_file(c5_file, binary_path)
    result["compile_output"] = compile_result.stderr + compile_result.stdout
    
    if compile_result.returncode != 0:
        result["compile_output"] = f"Compilation failed with code {compile_result.returncode}\n{compile_result.stderr}"
        return result
    
    result["compile_success"] = True
    
    # Run
    run_result, error = run_binary(binary_path)
    
    if error:
        result["runtime_error"] = error
        return result
    
    result["run_success"] = run_result.returncode == 0
    result["runtime_output"] = run_result.stdout
    result["runtime_error"] = run_result.stderr
    result["exit_code"] = run_result.returncode
    
    return result

def print_result(result, index, total):
    """Print the result of a single test."""
    print(f"\n{Colors.BOLD}[{index}/{total}] {result['file']}{Colors.END}")
    print("-" * 50)
    
    if result["compile_success"]:
        print(colorize("✓ Compilation: SUCCESS", Colors.GREEN))
    else:
        print(colorize("✗ Compilation: FAILED", Colors.RED))
        print(f"  Output: {result['compile_output']}")
        return
    
    if result["run_success"]:
        print(colorize("✓ Execution: SUCCESS", Colors.GREEN))
    elif result["runtime_error"] and not result["runtime_output"]:
        print(colorize("✗ Execution: FAILED", Colors.RED))
        print(f"  Error: {result['runtime_error']}")
        return
    else:
        print(colorize(f"⚠ Execution: Completed with exit code {result['exit_code']}", Colors.YELLOW))
    
    if result["runtime_output"]:
        print(f"  Output: {result['runtime_output'].strip()}")
    if result["runtime_error"]:
        print(f"  Stderr: {result['runtime_error'].strip()}")

def main():
    """Main test runner."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    examples_dir = os.path.join(script_dir, "examples")
    
    if not os.path.exists(examples_dir):
        print(colorize("Error: examples directory not found!", Colors.RED))
        sys.exit(1)
    
    c5_files = find_c5_files(examples_dir)
    
    if not c5_files:
        print(colorize("No .c5 files found in examples directory!", Colors.YELLOW))
        sys.exit(0)
    
    print(colorize(f"\n{'='*50}", Colors.BLUE))
    print(colorize(f"C5 Example Files Test Runner", Colors.BOLD))
    print(colorize(f"{'='*50}", Colors.BLUE))
    print(f"Found {len(c5_files)} example files to test\n")
    
    # Create temporary directory for binaries
    temp_dir = tempfile.mkdtemp(prefix="c5_test_")
    
    try:
        results = []
        passed = 0
        failed = 0
        
        for i, c5_file in enumerate(c5_files, 1):
            result = test_example(c5_file, temp_dir)
            results.append(result)
            print_result(result, i, len(c5_files))
            
            if result["compile_success"] and result["run_success"]:
                passed += 1
            else:
                failed += 1
        
        # Summary
        print(f"\n{Colors.BOLD}{'='*50}{Colors.END}")
        print(colorize(f"SUMMARY: {passed} passed, {failed} failed", Colors.BOLD))
        print(colorize(f"{'='*50}", Colors.END))
        
        # List failed files
        if failed > 0:
            print(colorize("\nFailed files:", Colors.RED))
            for r in results:
                if not (r["compile_success"] and r["run_success"]):
                    status = "compile error" if not r["compile_success"] else "runtime error"
                    print(f"  - {r['file']} ({status})")
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    # Return exit code based on results
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
