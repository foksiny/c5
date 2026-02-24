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

```c
for (int i = 0; i < 10; i = i + 1) {
    if (i == 5) {
        std::printf("Halfway there!\n");
    }
}
```

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

---

## 📜 License
This project is licensed under the [MIT License](LICENSE).
