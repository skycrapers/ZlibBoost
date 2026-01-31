import os
import json
import sys
import re
from collections import OrderedDict

TEMPLATE_WITH_SIZE_PATTERN = re.compile(r"_\d+x\d+(?:_|$)")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class Json2Liberty:
    def __init__(self):
        """Initialize"""
        pass

    def _format_value(self, value):
        """Format values, handle numbers and strings"""
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            return ",".join(map(str, value))
        return f'"{value}"'

    # def _write_timing_attributes(self, fh, indent, timing_data):
    #     """Write timing attributes"""
    #     indent_str = " " * indent
    #     for key, value in timing_data.items():
    #         if key not in ['cell_rise', 'cell_fall', 'rise_transition', 'fall_transition',
    #                       'rise_constraint', 'fall_constraint']:
    #             if isinstance(value, str):
    #                 fh.write(f'{indent_str}{key} : "{value}";\n')
    #             else:
    #                 fh.write(f'{indent_str}{key} : {value};\n')

    def _write_value_table(self, fh, indent, value_data):
        """Unified format for writing value tables"""
        indent_str = " " * indent
        # Write index
        if "index_1" in value_data:
            fh.write(
                f'{indent_str}  index_1("{",".join(map(str, value_data["index_1"]))}");\n'
            )
        if "index_2" in value_data:
            fh.write(
                f'{indent_str}  index_2("{",".join(map(str, value_data["index_2"]))}");\n'
            )

        # Write values
        if "values" in value_data:
            fh.write(f"{indent_str}  values(\n")
            values = value_data["values"]
            if isinstance(values, (int, float)):
                # Single value
                fh.write(f'{indent_str}    "{values}"\n')
            elif isinstance(values, list):
                if not isinstance(values[0], list):
                    # One-dimensional array
                    values_str = ",".join(map(str, values))
                    fh.write(f'{indent_str}    "{values_str}"\n')
                else:
                    # Two-dimensional array
                    for i, row in enumerate(values):
                        row_str = ",".join(map(str, row))
                        fh.write(f'{indent_str}    "{row_str}"')
                        if i < len(values) - 1:
                            fh.write(",\\\n")
                        else:
                            fh.write("\n")
            fh.write(f"{indent_str}  );\n")

    def _get_template_size(self, value_data):
        """Calculate template size"""
        len_1 = len(value_data.get("index_1", []))
        len_2 = len(
            value_data.get("index_2", [1])
        )  # If no index_2, default length is 1
        return f"{len_1}x{len_2}"

    def _resolve_template_name(self, template_name, value_data):
        """Return the correct template identifier for Liberty output."""
        if not template_name:
            return template_name
        if TEMPLATE_WITH_SIZE_PATTERN.search(template_name):
            return template_name
        template_size = self._get_template_size(value_data)
        return f"{template_name}_{template_size}"

    def _write_timing(self, fh, indent, timing_data):
        """Write timing group data"""
        indent_str = " " * indent
        fh.write(f"{indent_str}timing() {{\n")

        # Modify the when condition check, exclude empty or "()" cases
        if (
            "when" in timing_data
            and timing_data["when"]
            and timing_data["when"] != "()"
        ):
            fh.write(f'{indent_str}  when : "{timing_data["when"]}";\n')

        if "related_pin" in timing_data:
            fh.write(f'{indent_str}  related_pin : "{timing_data["related_pin"]}";\n')

        if "timing_type" in timing_data:
            fh.write(f'{indent_str}  timing_type : "{timing_data["timing_type"]}";\n')

        # Write timing tables, only when values are not empty
        for key, value in timing_data.items():
            if key in ["cell_rise", "cell_fall", "rise_transition", "fall_transition"]:
                if (
                    value
                    and isinstance(value, dict)
                    and "template" in value
                    and ("index_1" in value or "values" in value)
                ):
                    template_ref = self._resolve_template_name(value["template"], value)
                    fh.write(f"{indent_str}  {key}({template_ref}) {{\n")
                    self._write_value_table(fh, indent + 2, value)
                    fh.write(f"{indent_str}  }}\n")
            elif key in ["rise_constraint", "fall_constraint"]:
                if (
                    value
                    and isinstance(value, dict)
                    and "template" in value
                    and ("index_1" in value or "values" in value)
                ):
                    template_ref = self._resolve_template_name(value["template"], value)
                    fh.write(f"{indent_str}  {key}({template_ref}) {{\n")
                    self._write_value_table(fh, indent + 2, value)
                    fh.write(f"{indent_str}  }}\n")

        fh.write(f"{indent_str}}}\n")

    def _write_power(self, fh, indent, power_data):
        """Write power data"""
        indent_str = " " * indent
        fh.write(f"{indent_str}internal_power() {{\n")

        # Write basic attributes - skip empty or placeholder values
        related_pin = power_data.get("related_pin", "")
        if related_pin and related_pin != "-":
            fh.write(f'{indent_str}  related_pin : "{related_pin}";\n')
        when = power_data.get("when", "")
        if when and when != "()":
            fh.write(f'{indent_str}  when : "{when}";\n')

        # Write power tables
        for key, value in power_data.items():
            if isinstance(value, dict) and "template" in value:
                template_ref = self._resolve_template_name(value["template"], value)
                fh.write(f"{indent_str}  {key}({template_ref}) {{\n")
                self._write_value_table(fh, indent + 2, value)
                fh.write(f"{indent_str}  }}\n")

        fh.write(f"{indent_str}}}\n")

    def _write_leakage_power(self, fh, indent, leakage_data):
        """Write leakage_power data"""
        indent_str = " " * indent
        if isinstance(leakage_data, list):
            for item in leakage_data:
                fh.write(f"{indent_str}leakage_power() {{\n")
                if "when" in item:
                    fh.write(f'{indent_str}  when : "{item["when"]}";\n')
                if "value" in item:
                    fh.write(f"{indent_str}  value : {item['value']};\n")
                fh.write(f"{indent_str}}}\n")

    def _write_pin(self, fh, indent, pin_name, pin_data):
        """Write pin group data"""
        indent_str = " " * indent
        fh.write(f"{indent_str}pin({pin_name}) {{\n")

        # Write basic attributes
        for key, value in pin_data.items():
            if key not in [
                "timing",
                "internal_power",
                "capacitance_range",
                "rise_capacitance_range",
                "fall_capacitance_range",
            ]:
                fh.write(f"{indent_str}  {key} : {self._format_value(value)};\n")
            elif key.endswith("_range"):  # Handle capacitance ranges
                base_key = key.replace("_range", "")
                fh.write(
                    f"{indent_str}  {base_key}_range({self._format_value(value)});\n"
                )

        # Write timing data
        if "timing" in pin_data:
            for timing in pin_data["timing"]:
                self._write_timing(fh, indent + 2, timing)

        # Write internal_power data
        if "internal_power" in pin_data:
            for power in pin_data["internal_power"]:
                self._write_power(fh, indent + 2, power)

        fh.write(f"{indent_str}}}\n")

    def _write_operating_conditions(self, fh, operating_conditions):
        """Write operating_conditions data"""
        for cond_name, cond_data in operating_conditions.items():
            fh.write(f"  operating_conditions({cond_name}) {{\n")
            if "process" in cond_data:
                fh.write(f"    process : {cond_data['process']};\n")
            if "temperature" in cond_data:
                fh.write(f"    temperature : {cond_data['temperature']};\n")
            if "voltage" in cond_data:
                fh.write(f"    voltage : {cond_data['voltage']};\n")
            fh.write("  }\n")

    def _write_voltage_map(self, fh, voltage_map):
        """Write voltage_map data"""
        for pin_name, voltage in voltage_map.items():
            fh.write(f"  voltage_map({pin_name}, {voltage});\n")

    def _write_cell(self, fh, indent, cell_name, cell_data):
        """Write cell group data"""
        indent_str = " " * indent
        fh.write(f"{indent_str}cell({cell_name}) {{\n")

        # Write cell basic attributes
        if "cell_leakage_power" in cell_data:
            fh.write(
                f"{indent_str}  cell_leakage_power : {cell_data['cell_leakage_power']};\n"
            )

        # Write leakage_powers
        if "leakage_powers" in cell_data:
            self._write_leakage_power(fh, indent + 2, cell_data["leakage_powers"])

        # Write pins
        if "pins" in cell_data:
            for pin_name, pin_data in cell_data["pins"].items():
                self._write_pin(fh, indent + 2, pin_name, pin_data)

        # Write ff data - only when ff data is not empty
        if "ff(IQ,IQN)" in cell_data:
            ff_data = cell_data["ff(IQ,IQN)"]
            if ff_data:
                fh.write(f"{indent_str}  ff(IQ, IQN) {{\n")
                if "clocked_on" in ff_data:
                    fh.write(
                        f'{indent_str}    clocked_on : "{ff_data["clocked_on"]}";\n'
                    )
                if "next_state" in ff_data:
                    fh.write(
                        f'{indent_str}    next_state : "{ff_data["next_state"]}";\n'
                    )
                if "clear" in ff_data:
                    fh.write(f'{indent_str}    clear : "{ff_data["clear"]}";\n')
                if "preset" in ff_data:
                    fh.write(f'{indent_str}    preset : "{ff_data["preset"]}";\n')
                if "power_down_function" in ff_data:
                    fh.write(
                        f'{indent_str}    power_down_function : "{ff_data["power_down_function"]}";\n'
                    )
                fh.write(f"{indent_str}  }}\n")

        fh.write(f"{indent_str}}}\n")

    def _write_lu_table_templates(self, fh, templates_data):
        """Write lu_table_templates"""
        for template_name, template_data in templates_data.items():
            # Remove quotes around template name to fix formatting
            fh.write(f"  lu_table_template({template_name}) {{\n")

            # Write variables
            if "variable_1" in template_data:
                fh.write(f'    variable_1 : "{template_data["variable_1"]}";\n')
            if "variable_2" in template_data:
                fh.write(f'    variable_2 : "{template_data["variable_2"]}";\n')

            # Write indexes
            if "index_1" in template_data:
                index_1_str = ",".join(map(str, template_data["index_1"]))
                fh.write(f'    index_1("{index_1_str}");\n')
            if "index_2" in template_data:
                index_2_str = ",".join(map(str, template_data["index_2"]))
                fh.write(f'    index_2("{index_2_str}");\n')

            fh.write("  }\n")

    def _write_power_lut_templates(self, fh, templates_data):
        """Write power_lut_templates"""
        for template_name, template_data in templates_data.items():
            fh.write(f"  power_lut_template ({template_name}) {{\n")

            # Write variables
            if "variable_1" in template_data:
                fh.write(f'    variable_1 : "{template_data["variable_1"]}";\n')
            if "variable_2" in template_data:
                fh.write(f'    variable_2 : "{template_data["variable_2"]}";\n')

            # Write indexes
            if "index_1" in template_data:
                index_1_str = ",".join(map(str, template_data["index_1"]))
                fh.write(f'    index_1("{index_1_str}");\n')
            if "index_2" in template_data:
                index_2_str = ",".join(map(str, template_data["index_2"]))
                fh.write(f'    index_2("{index_2_str}");\n')

            fh.write("  }\n")

    def _write_library_attributes(self, fh, lib_data):
        """Write library-level attributes"""
        for key, value in lib_data.items():
            if key not in [
                "cells",
                "lu_table_templates",
                "power_lut_templates",
                "voltage_map",
                "operating_conditions",
            ]:
                if isinstance(value, str):
                    fh.write(f'  {key} : "{value}";\n')
                else:
                    fh.write(f"  {key} : {value};\n")
        if "voltage_map" in lib_data:
            self._write_voltage_map(fh, lib_data["voltage_map"])
        if "operating_conditions" in lib_data:
            self._write_operating_conditions(fh, lib_data["operating_conditions"])
        if "lu_table_templates" in lib_data:
            self._write_lu_table_templates(fh, lib_data["lu_table_templates"])
        if "power_lut_templates" in lib_data:
            self._write_power_lut_templates(fh, lib_data["power_lut_templates"])

    def _clean_content(self, content):
        """Clean content, remove specific power blocks and replace async"""
        # Remove rise_power blocks
        content = re.sub(r"rise_power\(power_template_0x1\)\s*{[^}]*}", "", content)
        # Remove fall_power blocks
        content = re.sub(r"fall_power\(power_template_0x1\)\s*{[^}]*}", "", content)
        # Replace async with clear
        content = content.replace("async", "clear")
        return content

    def convert(self, json_file, output_lib):
        """Convert JSON file to Liberty file"""
        # Read JSON data
        with open(json_file, "r") as f:
            data = json.load(f, object_pairs_hook=OrderedDict)

        # Create a temporary file to store initial output
        temp_output = output_lib + ".tmp"

        # Write Liberty file
        with open(temp_output, "w") as f:
            # Handle library structure
            if "library" in data:
                lib_name = data["library"].get("name", "my_library")
                f.write(f"library({lib_name}) {{\n")

                # Write library attributes
                self._write_library_attributes(f, data["library"])

                # Write cells
                if "cells" in data["library"]:
                    for cell_name, cell_data in data["library"]["cells"].items():
                        self._write_cell(f, 2, cell_name, cell_data)

                f.write("}\n")
            else:
                # Handle old format data
                f.write("library(my_library) {\n")
                for cell_name, cell_data in data.items():
                    if cell_name not in ["process", "voltage", "temperature"]:
                        self._write_cell(f, 2, cell_name, cell_data)
                f.write("}\n")

        # Read temporary file content
        with open(temp_output, "r") as f:
            content = f.read()

        # Clean content
        content = self._clean_content(content)

        # Write final file
        with open(output_lib, "w") as f:
            f.write(content)

        # Delete temporary file
        os.remove(temp_output)


def main():
    """This function is kept for standalone testing purposes"""
    if len(sys.argv) != 3:
        print("Usage: json2lib.py <input_json_file> <output_lib_file>")
        sys.exit(1)

    json_file = sys.argv[1]
    output_lib = sys.argv[2]

    converter = Json2Liberty()
    converter.convert(json_file, output_lib)


if __name__ == "__main__":
    main()
# def main():
#     # Initialize converter
#     converter = Json2Liberty()

#     # Set input and output directories
#     json_dir = "/home/guocj/project/LibertyMaster/json"
#     output_dir = "/home/guocj/project/LibertyMaster/libs"

#     # Ensure output directory exists
#     os.makedirs(output_dir, exist_ok=True)

#     # Process all JSON files
#     for json_file in os.listdir(json_dir):
#         if json_file.endswith('.json'):
#             input_path = os.path.join(json_dir, json_file)
#             output_path = os.path.join(output_dir, json_file.replace('.json', '.lib'))

#             print(f"Converting {json_file} to Liberty format...")
#             converter.convert(input_path, output_path)
#             print(f"Converted and saved to: {output_path}")

# if __name__ == "__main__":
#     main()
