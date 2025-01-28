# Liberty Parser & Modifier

A Python binding for parsing and modifying Liberty (.lib) files.

## Prerequisites

- CMake (>= 3.10)
- Python3 with development headers
- pybind11
- C++17 compatible compiler

## Building

1. Create and enter build directory:
```bash
mkdir build
cd build
```

2. Configure CMake:
```bash
cmake ..
```

3. Build:
```bash
make
```

This will generate a Python module named `liberty_api`.

## Usage Example

```python
import liberty_api

# 1) Parse Liberty file
pvt, cells = liberty_api.parse_liberty(
    lib_file="/path/to/input.lib",    # Input Liberty file
    process="FF",                      # Process corner (SS/TT/FF)
    dump_json_file="test.json"        # Optional: dump parse result to JSON
)

# Access parse results
print("Voltage =", pvt.voltage)
print("Temperature =", pvt.temperature)

for c in cells:
    print("Cell:", c.cell_name)
    print("  #output pins:", len(c.output_pins))
    print("  #input pins:", len(c.input_pins))

# 2) Modify Liberty file
success = liberty_api.modify_liberty(
    original_lib_file="/path/to/input.lib",  # Original Liberty file
    json_file="test.json",                   # JSON file with modifications
    output_lib_file="modified.lib"           # Output Liberty file
)
print("Modify success?", success)
```

## API Reference

### liberty_api.parse_liberty()
Parse Liberty file and optionally dump to JSON.

Parameters:
- `lib_file` (str): Path to input Liberty file
- `process` (str): Process corner ("SS"/"TT"/"FF"), default "TT" 
- `dump_json_file` (str): Optional path to dump parse results as JSON

Returns:
- Tuple(PVT, List[CellInfo]): PVT information and list of cell data

### liberty_api.modify_liberty()
Modify Liberty file using JSON data.

Parameters:
- `original_lib_file` (str): Path to original Liberty file
- `json_file` (str): Path to JSON file containing modifications
- `output_lib_file` (str): Path to write modified Liberty file

Returns:
- bool: True if successful, False otherwise
