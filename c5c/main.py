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
    parser.add_argument("--lib", action="store_true", help="Compile as library (output .o file)")
    
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
            asm = compile_file(input_files[0], include_paths=args.include, is_library=args.lib)
        else:
            asm = compile_files(input_files, include_paths=args.include, is_library=args.lib)
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
    if args.lib:
        # Library mode: output a .o object file
        final_out = args.output if args.output else base_name + ".o"
        s_file = base_name + ".tmp.s"

        with open(s_file, "w") as f:
            f.write(asm)
            
        print(f"Assembling to object file...")
        res = subprocess.run(["gcc", "-c", s_file, "-o", final_out])
        if res.returncode != 0:
            print("Error assembling")
            if os.path.exists(s_file): os.remove(s_file)
            sys.exit(res.returncode)
            
        if os.path.exists(s_file): os.remove(s_file)
        print(f"Success! Library object file ready at: {final_out}")
    else:
        # Executable mode
        final_out = args.output if args.output else base_name
        s_file = base_name + ".tmp.s"
        o_file = base_name + ".tmp.o"

        with open(s_file, "w") as f:
            f.write(asm)
            
        print(f"Assembling...")
        res = subprocess.run(["gcc", "-c", s_file, "-o", o_file])
        if res.returncode != 0:
            print("Error assembling")
            if os.path.exists(s_file): os.remove(s_file)
            sys.exit(res.returncode)
            
        print(f"Linking...")
        res = subprocess.run(["gcc", o_file, "-o", final_out])
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
