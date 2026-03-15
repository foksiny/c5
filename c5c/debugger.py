import os
import sys
import subprocess
import re
import tempfile
import shutil
from pathlib import Path


class Debugger:
    """Debug compiled C5 executables and analyze crashes."""
    
    def __init__(self, executable_path, source_files=None, assembly_file=None):
        # Convert to absolute path if relative
        if not os.path.isabs(executable_path):
            self.executable_path = os.path.abspath(executable_path)
        else:
            self.executable_path = executable_path
        self.source_files = source_files or []
        self.assembly_file = assembly_file
        self.source_lines = {}
        self.asm_lines = []
        self.symbol_table = {}
        self.asm_to_source_map = {}  # Map assembly addresses to source lines
        self.function_ranges = {}  # Map function names to address ranges
        
    def _load_source_files(self):
        """Load source files for line mapping."""
        for source_file in self.source_files:
            if os.path.exists(source_file):
                with open(source_file, 'r') as f:
                    lines = f.readlines()
                    self.source_lines[source_file] = lines
    
    def _load_assembly(self):
        """Load assembly file if available."""
        if self.assembly_file and os.path.exists(self.assembly_file):
            with open(self.assembly_file, 'r') as f:
                self.asm_lines = f.readlines()
            # Parse assembly to build address-to-source mapping
            self._build_asm_source_map()
            # Parse function ranges
            self._build_function_ranges()
    
    def _build_asm_source_map(self):
        """Build a mapping from assembly addresses to source file/line."""
        # Look for .loc directives in assembly (DWARF debug info)
        # Format: .loc fileno lineno [column]
        current_file = None
        current_line = None
        
        for line in self.asm_lines:
            line = line.strip()
            
            # Parse .file directive
            if line.startswith('.file'):
                # .file fileno "filename"
                match = re.search(r'\.file\s+(\d+)\s+"([^"]+)"', line)
                if match:
                    fileno = int(match.group(1))
                    filename = match.group(2)
                    # Store file mapping (simplified - just use the filename)
                    current_file = filename
            
            # Parse .loc directive
            if line.startswith('.loc'):
                # .loc fileno lineno [column]
                match = re.search(r'\.loc\s+(\d+)\s+(\d+)', line)
                if match:
                    fileno = int(match.group(1))
                    lineno = int(match.group(2))
                    current_line = lineno
            
            # Parse label with address (e.g., .L3:)
            if line.startswith('.L') and line.endswith(':'):
                # This is a label, we can associate it with current file/line
                if current_file and current_line:
                    label = line[:-1]
                    self.asm_to_source_map[label] = (current_file, current_line)
    
    def _build_function_ranges(self):
        """Build a mapping of function names to their address ranges."""
        if not self.asm_lines:
            return
        
        current_func = None
        func_start = None
        
        for line in self.asm_lines:
            line = line.strip()
            
            # Function labels end with : and don't start with .
            if line.endswith(':') and not line.startswith('.'):
                func_name = line[:-1]
                # Filter out local labels (starting with .L)
                if not func_name.startswith('.L'):
                    if current_func and func_start:
                        # Store the previous function's range
                        self.function_ranges[current_func] = (func_start, None)
                    current_func = func_name
                    func_start = None
            
            # Look for addresses in instructions
            if current_func and ':' in line:
                # Try to extract address from instruction
                parts = line.split(':')
                if len(parts) > 0:
                    addr_part = parts[0].strip()
                    if addr_part.startswith('0x'):
                        try:
                            addr = int(addr_part, 16)
                            if func_start is None:
                                func_start = addr
                            # Update end address
                            self.function_ranges[current_func] = (func_start, addr)
                        except ValueError:
                            pass
    
    def _extract_symbols(self):
        """Extract symbol information from the executable using nm."""
        try:
            result = subprocess.run(
                ['nm', '-n', self.executable_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 3:
                            addr = parts[0]
                            sym_type = parts[1]
                            name = ' '.join(parts[2:])
                            self.symbol_table[addr] = {
                                'type': sym_type,
                                'name': name
                            }
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    
    def _get_function_at_address(self, address):
        """Find the function containing a given address."""
        try:
            # Use addr2line to get function name
            result = subprocess.run(
                ['addr2line', '-f', '-e', self.executable_path, address],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    func_name = lines[0]
                    location = lines[1]
                    return func_name, location
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None, None
    
    def _get_source_location(self, address):
        """Get source file and line number for an address."""
        try:
            result = subprocess.run(
                ['addr2line', '-e', self.executable_path, address],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                location = result.stdout.strip()
                if location and location != '??:?':
                    # Parse file:line format
                    if ':' in location:
                        file_path, line_num = location.rsplit(':', 1)
                        try:
                            return file_path, int(line_num)
                        except ValueError:
                            pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Fallback: try to find source location from assembly mapping
        # This is less accurate but works without debug symbols
        return self._get_source_from_asm(address)
    
    def _get_source_from_asm(self, address):
        """Try to find source location from assembly file (without debug symbols)."""
        if not self.asm_lines:
            return None, None
        
        # Convert address to integer
        try:
            if address.startswith('0x'):
                addr_int = int(address, 16)
            else:
                addr_int = int(address, 16)
        except ValueError:
            return None, None
        
        # Look for the address in assembly and find associated source info
        # This is a heuristic approach - look for comments or patterns
        for i, line in enumerate(self.asm_lines):
            # Look for address in assembly
            if address[2:] in line or f'0x{addr_int:x}' in line:
                # Look backwards for source line comments
                for j in range(i, max(0, i - 20), -1):
                    asm_line = self.asm_lines[j].strip()
                    # Look for source line comments (format: # filename:line)
                    if asm_line.startswith('#') and ':' in asm_line:
                        # Try to parse filename:line
                        comment = asm_line[1:].strip()
                        if ':' in comment:
                            parts = comment.split(':', 1)
                            if len(parts) == 2:
                                file_path = parts[0].strip()
                                try:
                                    line_num = int(parts[1].strip())
                                    return file_path, line_num
                                except ValueError:
                                    pass
                break
        
        return None, None
    
    def _disassemble_around_address(self, address, context=10):
        """Disassemble around a specific address."""
        try:
            # Get disassembly around the address
            result = subprocess.run(
                ['objdump', '-d', '--start-address', f'0x{int(address, 16) - 0x20:x}',
                 '--stop-address', f'0x{int(address, 16) + 0x40:x}', self.executable_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None
    
    def _parse_signal_info(self, return_code):
        """Parse signal information from return code."""
        # Signal number is return_code - 128 for normal termination
        # or negative return_code for direct signal
        if return_code < 0:
            signal_num = -return_code
        elif return_code > 128:
            signal_num = return_code - 128
        else:
            return None
        
        signals = {
            1: ("SIGHUP", "Hangup"),
            2: ("SIGINT", "Interrupt (Ctrl+C)"),
            3: ("SIGQUIT", "Quit"),
            4: ("SIGILL", "Illegal instruction"),
            5: ("SIGTRAP", "Trace/breakpoint trap"),
            6: ("SIGABRT", "Abort"),
            7: ("SIGBUS", "Bus error"),
            8: ("SIGFPE", "Floating point exception"),
            9: ("SIGKILL", "Kill"),
            11: ("SIGSEGV", "Segmentation fault"),
            13: ("SIGPIPE", "Broken pipe"),
            14: ("SIGALRM", "Alarm clock"),
            15: ("SIGTERM", "Termination"),
        }
        
        if signal_num in signals:
            return signals[signal_num]
        return (f"Signal {signal_num}", "Unknown signal")
    
    def _get_crash_address_from_core(self):
        """Try to get crash address from core dump (if available)."""
        # Check if core dump exists
        core_files = ['core', 'core.%p', f'core.{os.getpid()}']
        for core_file in core_files:
            if os.path.exists(core_file):
                try:
                    # Use gdb to get crash info
                    gdb_script = """
                    bt
                    info registers
                    quit
                    """
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.gdb', delete=False) as f:
                        f.write(gdb_script)
                        gdb_script_path = f.name
                    
                    result = subprocess.run(
                        ['gdb', '-batch', '-x', gdb_script_path, self.executable_path, core_file],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    os.unlink(gdb_script_path)
                    
                    if result.returncode == 0:
                        return result.stdout
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
        return None
    
    def _analyze_crash_with_gdb(self):
        """Analyze crash using GDB if available."""
        try:
            # Create a GDB script to run the program and catch crashes
            gdb_script = f"""
            set pagination off
            set confirm off
            run
            backtrace
            info registers
            disassemble $pc-0x20,$pc+0x40
            quit
            """
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.gdb', delete=False) as f:
                f.write(gdb_script)
                gdb_script_path = f.name
            
            result = subprocess.run(
                ['gdb', '-batch', '-x', gdb_script_path, self.executable_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            os.unlink(gdb_script_path)
            
            if result.returncode == 0 or result.returncode == 1:
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None
    
    def _extract_rip_from_gdb(self, gdb_output):
        """Extract RIP (instruction pointer) from GDB output."""
        # Look for RIP register value
        rip_match = re.search(r'rip\s+(0x[0-9a-fA-F]+)', gdb_output)
        if rip_match:
            return rip_match.group(1)
        
        # Look for fault address in segfault message
        fault_match = re.search(r'fault.*?(0x[0-9a-fA-F]+)', gdb_output, re.IGNORECASE)
        if fault_match:
            return fault_match.group(1)
        
        return None
    
    def _format_source_context(self, file_path, line_num, context=3):
        """Format source code context around a line."""
        if file_path not in self.source_lines:
            return ""
        
        lines = self.source_lines[file_path]
        if line_num < 1 or line_num > len(lines):
            return ""
        
        start = max(0, line_num - context - 1)
        end = min(len(lines), line_num + context)
        
        output = []
        for i in range(start, end):
            line_marker = ">>>" if i == line_num - 1 else "   "
            output.append(f"{line_marker} {i+1:4d} | {lines[i].rstrip()}")
        
        return '\n'.join(output)
    
    def _format_asm_context(self, address, context=5):
        """Format assembly context around an address."""
        if not self.asm_lines:
            return ""
        
        # Try to find the address in assembly
        try:
            if address.startswith('0x'):
                addr_int = int(address, 16)
            else:
                addr_int = int(address, 16)
        except ValueError:
            return "(Invalid address format)"
        
        output = []
        found = False
        for i, line in enumerate(self.asm_lines):
            # Look for address in assembly
            if address[2:] in line or f'0x{addr_int:x}' in line:
                found = True
                start = max(0, i - context)
                end = min(len(self.asm_lines), i + context + 1)
                
                for j in range(start, end):
                    marker = ">>>" if j == i else "   "
                    output.append(f"{marker} {self.asm_lines[j].rstrip()}")
                break
        
        if not found:
            # If address not found, show the main function assembly
            # This is useful because the crash is likely in main
            output.append("(Address not found in assembly file - showing main function)")
            output.append("")
            
            # Find main function in assembly
            in_main = False
            for i, line in enumerate(self.asm_lines):
                if line.strip() == 'main:' or line.strip().startswith('main:'):
                    in_main = True
                    start = i
                    # Find end of main function (next function or end of file)
                    end = len(self.asm_lines)
                    for j in range(i + 1, len(self.asm_lines)):
                        if self.asm_lines[j].strip().endswith(':') and not self.asm_lines[j].strip().startswith('.'):
                            end = j
                            break
                    
                    # Show main function with context
                    for j in range(start, min(end, start + 30)):
                        marker = ">>>" if j == start else "   "
                        output.append(f"{marker} {self.asm_lines[j].rstrip()}")
                    break
        
        return '\n'.join(output)
    
    def _find_function_in_asm(self, address):
        """Find function name from assembly file."""
        if not self.asm_lines:
            return None
        
        try:
            if address.startswith('0x'):
                addr_int = int(address, 16)
            else:
                addr_int = int(address, 16)
        except ValueError:
            return None
        
        # Look for function labels before the address
        for i, line in enumerate(self.asm_lines):
            if address[2:] in line or f'0x{addr_int:x}' in line:
                # Look backwards for function label
                for j in range(i, max(0, i - 50), -1):
                    asm_line = self.asm_lines[j].strip()
                    # Function labels end with : and don't start with .
                    if asm_line.endswith(':') and not asm_line.startswith('.'):
                        func_name = asm_line[:-1]
                        # Filter out local labels (starting with .L)
                        if not func_name.startswith('.L'):
                            return func_name
                break
        
        return None
    
    def _analyze_crash_pattern(self, gdb_output, crash_addr):
        """Analyze crash pattern to provide intelligent suggestions."""
        suggestions = []
        
        # Check for NULL pointer dereference
        if 'rax' in gdb_output and '0x0' in gdb_output:
            # Look for mov instructions that might be dereferencing NULL
            if 'mov' in gdb_output and '(%rax)' in gdb_output:
                suggestions.append("Likely NULL pointer dereference - the program tried to read from address 0x0")
        
        # Check for stack overflow
        if 'rsp' in gdb_output:
            rsp_match = re.search(r'rsp\s+(0x[0-9a-fA-F]+)', gdb_output)
            if rsp_match:
                rsp = int(rsp_match.group(1), 16)
                # Check if RSP is very low (near stack bottom)
                if rsp < 0x1000:
                    suggestions.append("Possible stack overflow - stack pointer is very low")
        
        # Check for division by zero
        if 'SIGFPE' in gdb_output:
            suggestions.append("Floating point exception - likely division by zero or integer overflow")
        
        # Check for illegal instruction
        if 'SIGILL' in gdb_output:
            suggestions.append("Illegal instruction - the program tried to execute invalid code")
        
        return suggestions
    
    def run_and_debug(self, timeout=30):
        """Run the executable and debug any crashes."""
        print(f"\033[94m[DEBUG]\033[0m Running executable: {self.executable_path}")
        print(f"\033[94m[DEBUG]\033[0m Timeout: {timeout} seconds")
        print("-" * 60)
        
        # Load source files and assembly
        self._load_source_files()
        self._load_assembly()
        self._extract_symbols()
        
        try:
            # Run the executable
            result = subprocess.run(
                [self.executable_path],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Print program output
            if result.stdout:
                print("\033[92m[PROGRAM OUTPUT]\033[0m")
                print(result.stdout)
            
            if result.stderr:
                print("\033[91m[PROGRAM STDERR]\033[0m")
                print(result.stderr)
            
            # Check for crash
            if result.returncode != 0:
                print("\n" + "=" * 60)
                print("\033[91m[CRASH DETECTED]\033[0m")
                print("=" * 60)
                
                signal_name, signal_desc = self._parse_signal_info(result.returncode)
                if signal_name:
                    print(f"\n\033[91mSignal:\033[0m {signal_name} - {signal_desc}")
                    print(f"\033[91mReturn Code:\033[0m {result.returncode}")
                    
                    # Special handling for common crashes
                    if signal_name == "SIGSEGV":
                        print("\n\033[93mThis is a SEGMENTATION FAULT!\033[0m")
                        print("The program tried to access memory it doesn't have permission to access.")
                        print("\nCommon causes:")
                        print("  - Dereferencing a NULL pointer")
                        print("  - Accessing freed memory")
                        print("  - Buffer overflow")
                        print("  - Stack overflow")
                        print("  - Accessing memory out of bounds")
                    elif signal_name == "SIGABRT":
                        print("\n\033[93mThis is an ABORT signal!\033[0m")
                        print("The program called abort() or an assertion failed.")
                    elif signal_name == "SIGFPE":
                        print("\n\033[93mThis is a FLOATING POINT EXCEPTION!\033[0m")
                        print("Common causes:")
                        print("  - Division by zero")
                        print("  - Integer overflow")
                    elif signal_name == "SIGILL":
                        print("\n\033[93mThis is an ILLEGAL INSTRUCTION!\033[0m")
                        print("The program tried to execute an invalid instruction.")
                
                # Try to get more detailed crash info using GDB
                print("\n\033[94m[ANALYZING CRASH...]\033[0m")
                gdb_output = self._analyze_crash_with_gdb()
                
                if gdb_output:
                    # Extract crash address
                    crash_addr = self._extract_rip_from_gdb(gdb_output)
                    
                    if crash_addr:
                        print(f"\n\033[91mCrash Address:\033[0m {crash_addr}")
                        
                        # Get function and source location
                        func_name, location = self._get_function_at_address(crash_addr)
                        if func_name and func_name != '??':
                            print(f"\033[91mFunction:\033[0m {func_name}")
                        else:
                            # Try to find function from assembly
                            asm_func = self._find_function_in_asm(crash_addr)
                            if asm_func:
                                print(f"\033[91mFunction:\033[0m {asm_func}")
                        
                        if location and location != '??:?':
                            print(f"\033[91mLocation:\033[0m {location}")
                            
                            # Parse and show source context
                            if ':' in location:
                                file_path, line_num = location.rsplit(':', 1)
                                try:
                                    line_num = int(line_num)
                                    print(f"\n\033[94m[SOURCE CODE CONTEXT]\033[0m")
                                    print(f"File: {file_path}, Line: {line_num}")
                                    print("-" * 60)
                                    source_ctx = self._format_source_context(file_path, line_num)
                                    if source_ctx:
                                        print(source_ctx)
                                except ValueError:
                                    pass
                        else:
                            # Try to get source location from assembly
                            file_path, line_num = self._get_source_from_asm(crash_addr)
                            if file_path and line_num:
                                print(f"\033[91mLocation (from assembly):\033[0m {file_path}:{line_num}")
                                print(f"\n\033[94m[SOURCE CODE CONTEXT]\033[0m")
                                print(f"File: {file_path}, Line: {line_num}")
                                print("-" * 60)
                                source_ctx = self._format_source_context(file_path, line_num)
                                if source_ctx:
                                    print(source_ctx)
                        
                        # Show disassembly around crash
                        print(f"\n\033[94m[DISASSEMBLY AROUND CRASH]\033[0m")
                        print("-" * 60)
                        disasm = self._disassemble_around_address(crash_addr)
                        if disasm:
                            print(disasm)
                        else:
                            print("(Could not disassemble)")
                    
                    # Show backtrace
                    print(f"\n\033[94m[BACKTRACE]\033[0m")
                    print("-" * 60)
                    # Extract backtrace from GDB output
                    bt_lines = []
                    in_bt = False
                    for line in gdb_output.split('\n'):
                        if line.startswith('#'):
                            in_bt = True
                        if in_bt:
                            if line.strip() and not line.startswith('#'):
                                break
                            bt_lines.append(line)
                    
                    if bt_lines:
                        print('\n'.join(bt_lines[:20]))  # Show first 20 frames
                    else:
                        print("(No backtrace available)")
                    
                    # Show registers
                    print(f"\n\033[94m[REGISTERS AT CRASH]\033[0m")
                    print("-" * 60)
                    reg_lines = []
                    in_regs = False
                    for line in gdb_output.split('\n'):
                        if 'info registers' in line.lower() or 'rax' in line.lower():
                            in_regs = True
                        if in_regs:
                            if line.strip() and not any(r in line.lower() for r in ['rax', 'rbx', 'rcx', 'rdx', 'rsi', 'rdi', 'rbp', 'rsp', 'rip', 'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15', 'eflags']):
                                if 'quit' in line.lower():
                                    break
                                continue
                            reg_lines.append(line)
                    
                    if reg_lines:
                        print('\n'.join(reg_lines[:20]))
                    else:
                        print("(No register info available)")
                    
                    # Analyze crash pattern and provide suggestions
                    suggestions = self._analyze_crash_pattern(gdb_output, crash_addr)
                    if suggestions:
                        print(f"\n\033[94m[INTELLIGENT ANALYSIS]\033[0m")
                        print("-" * 60)
                        for suggestion in suggestions:
                            print(f"\033[93m• {suggestion}\033[0m")
                
                # Show assembly context if available
                if self.asm_lines and crash_addr:
                    print(f"\n\033[94m[ASSEMBLY FILE CONTEXT]\033[0m")
                    print("-" * 60)
                    asm_ctx = self._format_asm_context(crash_addr)
                    print(asm_ctx)
                
                print("\n" + "=" * 60)
                print("\033[91m[DEBUGGING COMPLETE]\033[0m")
                print("=" * 60)
                
                return False
            else:
                print("\n" + "=" * 60)
                print("\033[92m[PROGRAM EXITED SUCCESSFULLY]\033[0m")
                print("=" * 60)
                return True
                
        except subprocess.TimeoutExpired:
            print("\n" + "=" * 60)
            print("\033[91m[TIMEOUT]\033[0m")
            print("=" * 60)
            print(f"\nProgram did not complete within {timeout} seconds.")
            print("This might indicate an infinite loop or deadlock.")
            return False
        except Exception as e:
            print(f"\n\033[91m[ERROR]\033[0m Failed to run executable: {e}")
            return False


def debug_executable(executable_path, source_files=None, assembly_file=None, timeout=30):
    """Convenience function to debug an executable."""
    debugger = Debugger(executable_path, source_files, assembly_file)
    return debugger.run_and_debug(timeout)
