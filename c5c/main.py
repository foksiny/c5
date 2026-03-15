import sys
import os
import subprocess
import argparse
import shutil
import tempfile
from .compiler import compile_file, compile_files, analyze_file, analyze_files
from .debugger import debug_executable

def parse_build_file(content):
    config = {
        'type': 'program',
        'libtype': 'static',
        'files': [],
        'h_files': [],
        'outfolder': '',
        'outname': '',
        'install': 'no',
        'noutfolder': False
    }
    
    lines = content.split('\n')
    current_key = None
    
    for line in lines:
        line = line.split('//')[0].strip()
        if not line: continue
        
        if line.endswith(':'):
            current_key = line[:-1].strip()
            continue
            
        if ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip().strip('"')
            if key == 'noutfolder':
                config[key] = (val == '1')
            elif key in config:
                config[key] = val
            current_key = key
        elif current_key and (line.startswith('"') or line.startswith(' ')):
            val = line.strip().strip('"')
            if current_key in ('files', 'h_files'):
                config[current_key].append(val)
                    
    return config

def main():
    parser = argparse.ArgumentParser(description="C5 Compiler (c5c)")
    parser.add_argument("inputs", nargs="*", help="Source .c5, .c5h, or .c5b file(s)")
    parser.add_argument("-o", "--output", help="Output filename")
    parser.add_argument("-S", action="store_true", help="Output assembly only")
    parser.add_argument("-I", "--include", action="append", help="Add include search path")
    parser.add_argument("--setup-libs", action="store_true", help="Setup global C5 libraries")
    parser.add_argument("--lib", choices=['dynamic', 'static'], help="Compile as library. Use 'static' for static library (.a) or 'dynamic' for shared library (.so)")
    parser.add_argument("--build", nargs="?", const="build.c5b", help="Build project using a build file (.c5b)")
    parser.add_argument("-a", "--analyze", action="store_true", help="Analyze source files for errors and warnings without compiling")
    parser.add_argument("-d", "--debug", action="store_true", help="Compile and debug the executable, showing crash details if it fails")
    
    args = parser.parse_args()

    if args.setup_libs:
        global_path = os.path.expanduser("~/.c5/include")
        local_path = os.path.join(os.path.dirname(__file__), "..", "c5include")
        if not os.path.exists(local_path):
            local_path = os.path.join(os.getcwd(), "c5include")
        
        if not os.path.exists(local_path):
            print("Error: Local c5include/ not found. Run from project root.")
            sys.exit(1)
            
        print(f"Installing libraries to {global_path}...")
        os.makedirs(global_path, exist_ok=True)
        
        # First, copy all non-.c5 files as-is (headers, etc.)
        # But skip .a files that have a corresponding .c5 source (they'll be rebuilt)
        for f in os.listdir(local_path):
            src = os.path.join(local_path, f)
            dst = os.path.join(global_path, f)
            if os.path.isfile(src):
                if f.endswith('.c5'):
                    continue  # skip .c5 files, they'll be compiled
                # Check if it's a .a file with a corresponding .c5 source
                if f.endswith('.a'):
                    base = os.path.splitext(f)[0]
                    corresponding_c5 = f"{base}.c5"
                    if corresponding_c5 in os.listdir(local_path):
                        # Skip this .a, it will be rebuilt from .c5
                        continue
                # Copy other files directly (headers, standalone .a files)
                shutil.copy2(src, dst)
                print(f"Copied {f}")
        
        # Now compile all .c5 files to static libraries
        c5_files = [f for f in os.listdir(local_path) if f.endswith('.c5')]
        if c5_files:
            print(f"Found {len(c5_files)} .c5 library file(s) to compile:")
            for c5_file in c5_files:
                print(f"  - {c5_file}")
                
            for c5_file in c5_files:
                src_c5 = os.path.join(local_path, c5_file)
                base_name = os.path.splitext(c5_file)[0]
                
                # Create temporary directory for build artifacts
                with tempfile.TemporaryDirectory() as tmpdir:
                    s_file = os.path.join(tmpdir, f"{base_name}.s")
                    o_file = os.path.join(tmpdir, f"{base_name}.o")
                    a_file = os.path.join(global_path, f"{base_name}.a")
                    
                    try:
                        # Compile .c5 to assembly (as a library)
                        print(f"  Compiling {c5_file} to assembly...")
                        asm, lib_includes = compile_file(src_c5, include_paths=args.include, is_library=True)
                        
                        # Write assembly to temp file
                        with open(s_file, "w") as f:
                            f.write(asm)
                        
                        # Assemble to object file
                        print(f"  Assembling {base_name}.s to {base_name}.o...")
                        res = subprocess.run(["gcc", "-c", s_file, "-o", o_file])
                        if res.returncode != 0:
                            print(f"  Error assembling {c5_file}")
                            continue
                        
                        # Remove existing .a file if present to avoid adding to it
                        if os.path.exists(a_file):
                            os.remove(a_file)
                        
                        # Create static library
                        print(f"  Creating static library {base_name}.a...")
                        res = subprocess.run(["ar", "rcs", a_file, o_file])
                        if res.returncode != 0:
                            print(f"  Error creating static library for {c5_file}")
                            continue
                        
                        # Also copy the .c5 source file to global path (if not already there)
                        dst_c5 = os.path.join(global_path, c5_file)
                        if src_c5 != dst_c5:
                            shutil.copy2(src_c5, dst_c5)
                            print(f"  Copied {c5_file} source")
                        
                        print(f"  Successfully built {base_name}.a")
                        
                    except Exception as e:
                        print(f"  Error compiling {c5_file}: {e}")
                        continue
        else:
            print("No .c5 files found in c5include to compile.")
            
        print("Success!")
        sys.exit(0)
    
    input_files = args.inputs
    if args.build:
        build_path = args.build
        if os.path.isdir(build_path):
            build_path = os.path.join(build_path, "build.c5b")
        
        if not os.path.exists(build_path):
            print(f"Error: Build file not found: {build_path}")
            sys.exit(1)
        input_files = [build_path]

    if not input_files:
        print("Error: No input files provided")
        sys.exit(1)
    
    # Handle build file (.c5b)
    if input_files[0].endswith('.c5b'):
        if len(input_files) > 1:
            print("Warning: Multiple files provided with a build file. Only the build file will be used.")
        
        build_file = input_files[0]
        dir_path = os.path.dirname(os.path.abspath(build_file))
        with open(build_file, 'r') as f:
            content = f.read()
        
        config = parse_build_file(content)
        
        # Override args with config from build file
        input_files = [os.path.join(dir_path, f) for f in config['files']]
        if not input_files:
            print(f"Error: No source files specified in {build_file}")
            sys.exit(1)
            
        is_lib = (config['type'] == 'library')
        lib_type = config['libtype'] if is_lib else None
        
        out_name = config['outname'] or os.path.splitext(os.path.basename(input_files[0]))[0]
        out_folder = config['outfolder']
        
        if out_folder:
            out_folder_path = os.path.join(dir_path, out_folder)
            os.makedirs(out_folder_path, exist_ok=True)
            output_path = os.path.join(out_folder_path, out_name)
        else:
            output_path = os.path.join(dir_path, out_name)
            
        # Update args object
        args.lib = lib_type
        args.output = output_path
        
        # Prepare for compilation
        print(f"Building project: {build_file}")
    else:
        for input_file in input_files:
            if not (input_file.endswith('.c5') or input_file.endswith('.c5h')):
                print(f"Error: Expected a .c5 or .c5h file, got {input_file}")
                sys.exit(1)
        is_lib = (args.lib is not None)
        lib_type = args.lib if is_lib else None
        output_path = args.output

    # Use first file as base for output naming if not specified
    base_name = os.path.splitext(input_files[0])[0]
    
    # Analyze mode - check for errors and warnings without compiling
    if args.analyze:
        print(f"Analyzing {', '.join([os.path.basename(f) for f in input_files])}...")
        try:
            if len(input_files) == 1:
                has_errors, error_count, warning_count = analyze_file(input_files[0], include_paths=args.include, is_library=is_lib)
            else:
                has_errors, error_count, warning_count = analyze_files(input_files, include_paths=args.include, is_library=is_lib)
            
            if has_errors:
                print(f"\n\033[91mAnalysis failed with {error_count} error(s) and {warning_count} warning(s)\033[0m")
                sys.exit(1)
            else:
                print(f"\n\033[92mAnalysis passed with {warning_count} warning(s)\033[0m")
                sys.exit(0)
        except Exception as e:
            print(f"Analysis error: {e}")
            sys.exit(1)
    
    # Assembly phase
    print(f"Compiling {', '.join([os.path.basename(f) for f in input_files])} to GAS assembly...")
    try:
        if len(input_files) == 1:
            result = compile_file(input_files[0], include_paths=args.include, is_library=is_lib)
        else:
            result = compile_files(input_files, include_paths=args.include, is_library=is_lib)
        # result is (asm, lib_includes)
        asm, lib_includes = result
    except Exception as e:
        print(f"Compilation error: {e}")
        sys.exit(1)

    if args.S:
        out_s = output_path + ".s" if output_path else base_name + ".s"
        with open(out_s, "w") as f:
            f.write(asm)
        print(f"Success! Assembly generated at: {out_s}")
        return
    
    # Debug mode: save assembly file for debugging
    debug_asm_file = None
    if args.debug:
        debug_asm_file = base_name + ".debug.s"
        with open(debug_asm_file, "w") as f:
            f.write(asm)

    # Full compilation phase
    # Write assembly to temporary file
    s_file = base_name + ".tmp.s"
    o_file = base_name + ".tmp.o"
    
    with open(s_file, "w") as f:
        f.write(asm)
    
    # Assemble to object file
    if lib_type == 'dynamic':
        print(f"Assembling to position-independent object file...")
        res = subprocess.run(["gcc", "-c", "-fPIC", s_file, "-o", o_file])
    else:
        print(f"Assembling...")
        res = subprocess.run(["gcc", "-c", s_file, "-o", o_file])
    
    # Check for missing libraries early (before linking)
    lib_paths = [path for path, _ in lib_includes]
    for lib_path in lib_paths:
        if not os.path.exists(lib_path):
            print(f"Error: Library not found: {lib_path}")
            if os.path.exists(s_file): os.remove(s_file)
            if os.path.exists(o_file): os.remove(o_file)
            sys.exit(1)
    
    if res.returncode != 0:
        print("Error assembling")
        if os.path.exists(s_file): os.remove(s_file)
        if os.path.exists(o_file): os.remove(o_file)
        sys.exit(res.returncode)
    
    final_out = output_path
    if is_lib:
        # Library output
        if lib_type == 'static':
            extension = '.a'
        else:
            extension = '.so'
        
        if final_out:
            if not final_out.endswith(extension):
                final_out += extension
        else:
            final_out = base_name + extension
        
        if lib_type == 'static':
            print(f"Creating static library...")
            res = subprocess.run(["ar", "rcs", final_out, o_file])
            if res.returncode != 0:
                print("Error creating static library")
                if os.path.exists(s_file): os.remove(s_file)
                if os.path.exists(o_file): os.remove(o_file)
                sys.exit(res.returncode)
            print(f"Success! Static library ready at: {final_out}")
        else:
            # Shared library: link with dependencies
            print(f"Creating shared library...")
            cmd = ["gcc", "-shared", o_file] + lib_paths + ["-o", final_out]
            res = subprocess.run(cmd)
            if res.returncode != 0:
                print("Error creating shared library")
                if os.path.exists(s_file): os.remove(s_file)
                if os.path.exists(o_file): os.remove(o_file)
                sys.exit(res.returncode)
            print(f"Success! Shared library ready at: {final_out}")
            
        # Copy headers to output folder if using build system
        if 'config' in locals() and config.get('h_files'):
            out_dir = os.path.dirname(final_out)
            for i, h_file in enumerate(config['h_files']):
                src_h = os.path.join(dir_path, h_file)
                if os.path.exists(src_h):
                    if i == 0:
                        lib_base = os.path.splitext(os.path.basename(final_out))[0]
                        dest_name = lib_base + ".c5h"
                        
                        # Prepend libinclude for the main header
                        lib_file = os.path.basename(final_out)
                        lib_directive = f"libinclude <{lib_file}> #{lib_type}\n"
                        
                        with open(src_h, 'r') as f:
                            content = f.read()
                        
                        if lib_directive.strip() not in content:
                            content = lib_directive + content
                        
                        dst_h = os.path.join(out_dir, dest_name)
                        with open(dst_h, 'w') as f:
                            f.write(content)
                        print(f"Saved header: {dest_name} to {out_dir} (with libinclude)")
                    else:
                        dest_name = os.path.basename(h_file)
                        dst_h = os.path.join(out_dir, dest_name)
                        if os.path.abspath(src_h) != os.path.abspath(dst_h):
                            shutil.copy2(src_h, dst_h)
                            print(f"Saved header: {dest_name} to {out_dir}")
            
        # Installation logic for build system
        if 'config' in locals():
            install_opt = config.get('install', 'no')
            do_install = False
            if install_opt == 'ask':
                ans = input(f"Do you want to install library '{out_name}'? (Y/n): ")
                if ans.lower() != 'n':
                    do_install = True
            elif install_opt == 'force':
                print(f"Installing library '{out_name}'...")
                do_install = True
            
            if do_install:
                global_path = os.path.expanduser("~/.c5/include")
                os.makedirs(global_path, exist_ok=True)
                
                # Copy output file
                dest_lib = os.path.join(global_path, os.path.basename(final_out))
                shutil.copy2(final_out, dest_lib)
                
                # Copy header files
                h_files = config.get('h_files', [])
                for i, h_file in enumerate(h_files):
                    src_h = os.path.join(dir_path, h_file)
                    if os.path.exists(src_h):
                        # If this is the main header (first one), rename it to match the library name
                        if i == 0:
                            lib_base = os.path.splitext(os.path.basename(final_out))[0]
                            dest_name = lib_base + ".c5h"
                            
                            # Prepend libinclude for the main header
                            lib_file = os.path.basename(final_out)
                            lib_directive = f"libinclude <{lib_file}> #{lib_type}\n"
                            
                            with open(src_h, 'r') as f:
                                content = f.read()
                            
                            if lib_directive.strip() not in content:
                                content = lib_directive + content
                            
                            dest_h = os.path.join(global_path, dest_name)
                            with open(dest_h, 'w') as f:
                                f.write(content)
                            print(f"Installed header: {dest_name} (with libinclude)")
                        else:
                            dest_name = os.path.basename(h_file)
                            dest_h = os.path.join(global_path, dest_name)
                            shutil.copy2(src_h, dest_h)
                            print(f"Installed header: {dest_name}")
                
                # Copy outfolder if requested and noutfolder is False
                if out_folder and not config.get('noutfolder', False):
                    src_folder = os.path.join(dir_path, out_folder)
                    dest_folder = os.path.join(global_path, out_folder)
                    if os.path.exists(src_folder) and os.path.abspath(src_folder) != os.path.abspath(dest_folder):
                        if os.path.exists(dest_folder):
                            shutil.rmtree(dest_folder)
                        shutil.copytree(src_folder, dest_folder)
                        print(f"Installed output folder: {out_folder}")
                
                print(f"Successfully installed to {global_path}")

        # Clean up intermediate files
        if os.path.exists(s_file): os.remove(s_file)
        if os.path.exists(o_file): os.remove(o_file)
    else:
        # Executable mode: link with libraries
        if not final_out:
            final_out = base_name
        print(f"Linking...")
        cmd = ["gcc", o_file] + lib_paths + ["-o", final_out]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print("Error linking")
            if os.path.exists(s_file): os.remove(s_file)
            if os.path.exists(o_file): os.remove(o_file)
            sys.exit(res.returncode)
        print("Cleaning up intermediate files...")
        if os.path.exists(s_file): os.remove(s_file)
        if os.path.exists(o_file): os.remove(o_file)
        print(f"Success! Executable ready at: {final_out}")
        
        # Debug mode: run the executable and analyze crashes
        if args.debug:
            print("\n" + "=" * 60)
            print("\033[94m[DEBUG MODE]\033[0m")
            print("=" * 60)
            
            # Get source files for debugging
            source_files = input_files if 'input_files' in locals() else []
            
            # Run debugger
            success = debug_executable(
                final_out,
                source_files=source_files,
                assembly_file=debug_asm_file,
                timeout=30
            )
            
            # Keep debug assembly file for future debugging (don't clean up)
            # if debug_asm_file and os.path.exists(debug_asm_file):
            #     os.remove(debug_asm_file)
            
            if not success:
                sys.exit(1)

if __name__ == '__main__':
    main()
