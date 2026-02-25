# C5 Programming Language

C5 is a high-performance, statically-typed programming language that compiles directly to x86_64 GAS (GNU Assembler). It is designed to be lightweight, memory-aware, and seamlessly compatible with the C ABI.

## 🚀 Key Features

- **Direct x86_64 GAS Compilation**: No heavy IR, just pure, readable assembly.
- **Strict C ABI Compatibility**: Call any C library function with zero overhead.
- **Automatic Namespacing**: Included headers (like `std.c5h`) are partitioned into namespaces to avoid symbol clobbering.
- **Smart String Handling**: Native support for string concatenation (`+`) and substring removal (`-`).
- **Pointer Arithmetic**: Full support for raw memory manipulation with automatic type scaling.
- **Modern CLI**: Compile to executables with `-o` or inspect assembly with `-S`.

## 🛠️ Getting Started

### Installation
```bash
# Clone the repository and install in editable mode
pip install -e .
```

### Basic Usage
```bash
# Compile and link to create an executable
c5c main.c5 -o my_app

# Add custom include paths
c5c main.c5 -I ./custom_headers -o my_app

# Setup global libraries (~/.c5/include)
c5c --setup-libs

# Compile and output only assembly
c5c main.c5 -S -o output.s
```

## 📂 Include Search Order
When you use `include <file.c5h>`, the compiler searches in this order:
1. Current directory of the source file.
2. Custom paths provided via `-I`.
3. Project-local `c5include/` directory.
4. Global `~/.c5/include/` directory (populated via `c5c --setup-libs`).

---

## 📖 Language Documentation

### 1. Basic Types
C5 uses explicit bit-widths for its types to ensure predictability across platforms.

| Type | Description | Alias of |
| :--- | :--- | :--- |
| `int` | 64-bit signed integer | `int<64>` |
| `int<32>` | 32-bit signed integer | - |
| `int<16>` | 16-bit signed integer | - |
| `int<8>` | 8-bit signed integer (byte) | - |
| `char` | 8-bit character | `int<8>` |
| `float` | 64-bit floating point | `float<64>` |
| `float<32>` | 32-bit floating point | - |
| `string` | UTF-8 encoded string | - |
| `void` | Empty return type | - |

### 2. Signed and Unsigned Modifiers
C5 supports `signed` and `unsigned` modifiers for integer types to explicitly specify the sign behavior:

```c
include <std.c5h>

unsigned int<32> get_positive() {
    return 4294967295;  // Maximum unsigned 32-bit value
}

void main() {
    unsigned int<32> a = get_positive();
    signed char b = 'b';
    
    // Unsigned types use zero-extension
    // Signed types use sign-extension
    std::printf("%u | %c\n", a, b);
}
```

| Modifier | Behavior |
| :--- | :--- |
| `signed` | Explicitly marks type as signed (sign-extension on load) |
| `unsigned` | Marks type as unsigned (zero-extension on load) |

**Key differences:**
- **Signed types**: Use sign-extension when loading smaller values (e.g., `movsbq`, `movswq`, `movslq`)
- **Unsigned types**: Use zero-extension when loading smaller values (e.g., `movzbq`, `movzwq`, `movl`)
- By default, `int`, `int<8>`, `int<16>`, `int<32>`, `int<64>`, and `char` are signed unless explicitly marked `unsigned`

### 3. Variables & Constants
```c
int<32> age = 25;
string name = "Jose";
float pi = 3.14159;
char initial = 'J';
```

### 4. Control Flow
C5 supports standard C control structures:
- `if` / `else`
- `while` loops
- `do` / `while` loops
- `for` loops
- `foreach` loops (for iterating over arrays)

```c
for (int i = 0; i < 10; i = i + 1) {
    if (i == 5) {
        std::printf("Halfway there!\n");
    }
}
```

#### Foreach Loops
The `foreach` loop provides a convenient way to iterate over arrays with both index and value:

```c
include <std.c5h>

void main() {
    array<int<32>> arr = {10, 20, 30, 40, 50};

    foreach (i, val in arr) {
        std::printf("arr[%d] = %d\n", i, val);
    }
}
```

**Syntax:** `foreach (index_var, value_var in array_expr) { body }`

- `index_var`: A variable that holds the current index (0-based)
- `value_var`: A variable that holds the current element value
- `array_expr`: An array expression (can be a variable or function return)

The `foreach` loop automatically:
- Determines the element type from the array
- Iterates from index 0 to length-1
- Provides both the index and value in each iteration

### 5. Directives & Namespacing
When you `include <std.c5h>`, all functions inside are placed in the `std::` namespace.
```c
include <std.c5h>

void main() {
    std::printf("Hello, C5!\n");
}
```

### 6. String Power
Strings in C5 are more than just pointers; they support arithmetic.
```c
string s = "Hello";
s = s + " World";   // Concatenation
s = s - " Hello";   // Result: " World"
```

#### C String Interoperability
C5 provides seamless interoperability with C strings through the built-in `c_str()` function and string indexing:

```c
include <std.c5h>

void main() {
    // Convert a C5 string to a C string (char*)
    char* a = c_str("Hello, world!");
    
    // Index into C strings
    char b = a[1];  // 'e'
    std::printf("str: %s\nchar: %c\n", a, b);
    
    // Index into C5 strings directly
    string a2 = "Hello, world!";
    char b2 = a2[1];  // 'e'
    std::printf("str: %s\nchar: %c\n", a2, b2);
}
```

**Key features:**
- `c_str(string)`: Converts a C5 `string` to a C `char*` pointer for use with C library functions
- `[]` operator: Works on both `string` and `char*` types to access individual characters
- Returns `char` type when indexing into strings

### 7. Structs & Enums
```c
struct Point {
    int<32> x;
    int<32> y;
};

enum Color { RED, GREEN, BLUE };

void main() {
    Point p = {10, 20};
    int<32> my_color = Color::RED;
}
```

### 8. Arrow Operator
When accessing struct members through a pointer, use the `->` operator:
```c
include <std.c5h>

struct Point {
    int<32> x;
    int<32> y;
};

void main() {
    Point pt = {0, 0};
    Point* ptr = &pt;

    ptr->x = 42;
    ptr->y = 99;

    std::printf("x = %d\n", ptr->x);
    std::printf("y = %d\n", ptr->y);
}
```

### 9. Arrays
C5 provides a dynamic `array<T>` type with built-in methods for managing collections:
```c
include <std.c5h>

void main() {
    // Create an array with initial values
    array<int<32>> arr = {1, 2, 3, 4, 5};

    // Access elements by index
    std::printf("arr[0]: %d\n", arr[0]);

    // Push a new element to the end
    arr.push(6);

    // Pop and return the last element
    int<32> last = arr.pop();

    // Get the length
    int<64> len = arr.length();

    // Clear all elements
    arr.clear();
}
```

Arrays can also be passed to and returned from functions:
```c
array<int<32>> append_value(array<int<32>> arr) {
    arr.push(arr[arr.length() - 1] + 1);
    return arr;
}
```

### 10. Pointers & Memory
C5 provides full access to memory with C-like syntax.
```c
include <std.c5h>

void main() {
    int<32> val = 42;
    int<32>* ptr = &val;       // Address-of
    *ptr = 100;                // Dereference
    
    // Pointer arithmetic (automatically scales by sizeof(int<32>))
    int<32>* arr = std::malloc(10 * 4);
    *(arr + 1) = 50; 
    std::free(arr);
}
```

### 11. Public Variables (Globals)
Use the `let` keyword at the top level to declare global variables.
```c
let int<32> counter = 0;

void main() {
    counter = counter + 1;
    std::printf("Counter: %d\n", counter);
}
```

### 12. Macros
C5 supports simple macros that are expanded at compile time. Macros are defined using the `macro` keyword and work like inline functions.

```c
include <std.c5h>

// Define a macro that adds two values
macro add(a, b) {
    a + b
}

void main() {
    int<32> result = add(10, 20);
    std::printf("Sum: %d\n", result);  // Output: Sum: 30
}
```

**Key features of C5 macros:**
- **Parameter substitution**: Macro parameters are replaced with the actual arguments
- **Expression bodies**: The last expression in the macro body becomes the result
- **Zero overhead**: Macros are expanded at compile time, no runtime cost
- **Type flexibility**: Macros work with any compatible types

### 13. Lambda Expressions
C5 supports lambda expressions (anonymous functions) that can be assigned to variables and called like regular functions.

```c
include <std.c5h>

void main() {
    // Define a lambda that adds two integers
    int<32> sum = fnct(int<32> a, int<32> b) {
        return a + b;
    };

    // Call the lambda
    std::printf("%d\n", sum(10, 20));  // Output: 30
}
```

**Lambda syntax:**
```
fnct(parameters) { body }
```

**Key features:**
- **Anonymous functions**: Lambdas are unnamed functions that can be defined inline
- **First-class values**: Lambdas can be assigned to variables and passed around
- **Type inference**: The return type is inferred from the body
- **Closures**: Lambdas capture their surrounding scope

**Example with multiple lambdas:**
```c
include <std.c5h>

void main() {
    int<32> add = fnct(int<32> a, int<32> b) {
        return a + b;
    };
    
    int<32> mul = fnct(int<32> a, int<32> b) {
        return a * b;
    };
    
    std::printf("Add: %d\n", add(5, 3));   // Output: Add: 8
    std::printf("Mul: %d\n", mul(5, 3));   // Output: Mul: 15
}
```

---

## 📚 Library Creation

C5 supports creating and using libraries through a combination of header files (`.c5h`) and implementation files (`.c5`).

### Library Structure

A typical C5 library consists of two files:

1. **Header file (`.c5h`)**: Contains function declarations (prototypes)
2. **Implementation file (`.c5`)**: Contains the actual function definitions

#### Example: Math Library

**math.c5h** (header file):
```c
// Function declarations for the math library
int<32> add(int<32> a, int<32> b);
int<32> sub(int<32> a, int<32> b);
int<32> mul(int<32> a, int<32> b);
int<32> div(int<32> a, int<32> b);
```

**math.c5** (implementation file):
```c
int<32> add(int<32> a, int<32> b) {
    return a + b;
}

int<32> sub(int<32> a, int<32> b) {
    return a - b;
}

int<32> mul(int<32> a, int<32> b) {
    return a * b;
}

int<32> div(int<32> a, int<32> b) {
    return a / b;
}
```

### Using Libraries

To use a library in your C5 project:

**main.c5**:
```c
include <std.c5h>
include <math.c5h>  // Include the library header

void main() {
    int<32> a = 10;
    int<32> b = 20;

    // Call library functions using the namespace (derived from filename)
    int<32> result = math::add(a, b);
    
    std::printf("Result: %d\n", result);
}
```

### Compiling with Libraries

When compiling a project that uses local libraries, pass both the main file and the library implementation file(s) to the compiler:

```bash
# Compile main.c5 with math.c5 library
c5c main.c5 math.c5 -o myapp

# Multiple libraries can be included
c5c main.c5 math.c5 utils.c5 -o myapp
```

### Creating Reusable Object Libraries

You can also compile library implementation files into object files (`.o`) for later linking:

```bash
# Compile math.c5 to an object file (no main function required)
c5c math.c5 --lib -o math.o

# Later, link with your main program
gcc main.o math.o -o myapp
```

### Library Namespacing

When you include a header file (e.g., `include <math.c5h>`), all functions declared in that header are automatically placed in a namespace derived from the filename:

- `math.c5h` → `math::` namespace
- `utils.c5h` → `utils::` namespace
- `std.c5h` → `std::` namespace

This prevents symbol collisions between different libraries.

### Best Practices

1. **One library per header/implementation pair**: Keep related functions together
2. **Consistent naming**: Use the same base name for `.c5h` and `.c5` files
3. **Document your API**: Add comments in the header file describing each function
4. **Type consistency**: Ensure declarations in `.c5h` match definitions in `.c5`

---

## 📜 License
This project is licensed under the [MIT License](LICENSE).
