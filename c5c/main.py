import sys
import os
import subprocess
import argparse
from .compiler import compile_file

def main():
    parser = argparse.ArgumentParser(description="C5 Compiler (c5c)")
    parser.add_argument("input", nargs="?", help="Source .c5 file")
    parser.add_argument("-o", "--output", help="Output filename")
    parser.add_argument("-S", action="store_true", help="Output assembly only")
    parser.add_argument("-I", "--include", action="append", help="Add include search path")
    parser.add_argument("--setup-libs", action="store_true", help="Setup global C5 libraries")
    
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
    
    input_file = args.input
    if not input_file.endswith('.c5'):
        print("Error: Expected a .c5 file")
        sys.exit(1)
        
    base_name = os.path.splitext(input_file)[0]
    
    # Assembly phase
    print(f"Compiling {input_file} to GAS assembly...")
    try:
        asm = compile_file(input_file, include_paths=args.include)
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
