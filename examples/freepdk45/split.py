import os
import re


output_folder = './netlist'
os.makedirs(output_folder, exist_ok=True)


with open('cells.sp', 'r') as file:
    content = file.read()


subckt_regex = re.compile(r'\.subckt\s+(\w+)\s+(.*?)\.ends', re.DOTALL)
matches = subckt_regex.findall(content)

for match in matches:
    subckt_name = match[0]
    subckt_content = match[1]
    file_name = os.path.join(output_folder, subckt_name + '.spi')

    file_content = f"""
    .subckt {subckt_name} {subckt_content}
.ENDS"""

    with open(file_name, 'w') as file:
        file.write(file_content)
