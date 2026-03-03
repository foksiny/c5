import sys
import os
import subprocess
import argparse
from .compiler import compile_file, compile_files

def main():
    parser = argparse.ArgumentParser(description="C5 Compiler (c5c)")
    parser.add_argument("inputs", nargs="*", help="Source .c5 file(s)")
    parser.add_argument("-o", "--output", help="Output filename")
    parser.add_argument("-S", action="store_true", help="Output assembly only")
    parser.add_argument("-I", "--include", action="append", help="Add include search path")
    parser.add_argument("--setup-libs", action="store_true", help="Setup global C5 libraries")
    parser.add_argument("--lib", choices=['dynamic', 'static'], help="Compile as library. Use 'static' for static library (.a) or 'dynamic' for shared library (.so)")
    
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
        import shutil
        for f in os.listdir(local_path):
            shutil.copy2(os.path.join(local_path, f), os.path.join(global_path, f))
        print("Success!")
        sys.exit(0)
    
    input_files = args.inputs
    if not input_files:
        print("Error: No input files provided")
        sys.exit(1)
    
    for input_file in input_files:
        if not input_file.endswith('.c5'):
            print(f"Error: Expected a .c5 file, got {input_file}")
            sys.exit(1)
    
    # Use first file as base for output naming if not specified
    base_name = os.path.splitext(input_files[0])[0]
    
    # Assembly phase
    print(f"Compiling {', '.join(input_files)} to GAS assembly...")
    try:
        if len(input_files) == 1:
            result = compile_file(input_files[0], include_paths=args.include, is_library=(args.lib is not None))
        else:
            result = compile_files(input_files, include_paths=args.include, is_library=(args.lib is not None))
        # result is (asm, lib_includes)
        asm, lib_includes = result
    except Exception as e:
        print(f"Compilation error: {e}")
        sys.exit(1)

    if args.S:
        out_s = args.output if args.output else base_name + ".s"
        with open(out_s, "w") as f:
            f.write(asm)
        print(f"Success! Assembly generated at: {out_s}")
        return

    # Full compilation phase
    # Write assembly to temporary file
    s_file = base_name + ".tmp.s"
    o_file = base_name + ".tmp.o"
    
    with open(s_file, "w") as f:
        f.write(asm)
    
    # Determine if we're making a library and what type
    is_lib = args.lib is not None
    lib_type = args.lib if is_lib else None
    
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
    
    if is_lib:
        # Library output
        if lib_type == 'static':
            extension = '.a'
        else:
            extension = '.so'
        
        if args.output:
            final_out = args.output
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
        
        # Clean up intermediate files
        if os.path.exists(s_file): os.remove(s_file)
        if os.path.exists(o_file): os.remove(o_file)
    else:
        # Executable mode: link with libraries
        final_out = args.output if args.output else base_name
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

if __name__ == '__main__':
    main()
