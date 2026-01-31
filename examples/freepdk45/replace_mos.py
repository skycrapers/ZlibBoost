#!/usr/bin/env python3
import os
import re
import sys

def replace_transistors_in_file(file_path):
    """
    Replace all occurrences of 'pmos' with 'PMOS_VTH' and 'nmos' with 'NMOS_VTH' in a file,
    while preserving case sensitivity for other parts of the text.
    
    Args:
        file_path: Path to the file to process
    
    Returns:
        bool: True if any replacements were made, False otherwise
    """
    try:
        # Read the file content
        with open(file_path, 'r') as file:
            content = file.read()
        
        # Use regular expressions for case-sensitive replacement
        # This handles standalone words and preserves case context
        original_content = content
        
        # Replace whole word 'pmos' (case-insensitive) with 'PMOS_VTH'
        content = re.sub(r'\b(?i:pmos)\b', 'PMOS_VTH', content)
        
        # Replace whole word 'nmos' (case-insensitive) with 'NMOS_VTH'
        content = re.sub(r'\b(?i:nmos)\b', 'NMOS_VTH', content)
        
        # Write the modified content back to the file
        if content != original_content:
            with open(file_path, 'w') as file:
                file.write(content)
            return True
        else:
            return False
            
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return False

def process_directory(directory_path):
    """
    Process all files in the given directory
    
    Args:
        directory_path: Directory containing files to process
    """
    if not os.path.exists(directory_path):
        print(f"Error: Directory '{directory_path}' does not exist.")
        return
    
    # Statistics
    total_files = 0
    modified_files = 0
    
    # Process each file in the directory
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        
        # Skip directories and symbolic links
        if not os.path.isfile(file_path) or os.path.islink(file_path):
            continue
        
        total_files += 1
        print(f"Processing: {filename}")
        
        if replace_transistors_in_file(file_path):
            modified_files += 1
            print(f"  Modified: Replaced transistor references in {filename}")
    
    # Print summary
    print(f"\nSummary:")
    print(f"  Total files processed: {total_files}")
    print(f"  Files modified: {modified_files}")

if __name__ == "__main__":
    # Default directory path from the prompt
    directory_path = "/home/guocj/project/klib/examples/freepdk45/netlist"
    
    # Allow command-line override
    if len(sys.argv) > 1:
        directory_path = sys.argv[1]
    
    process_directory(directory_path)
    
