# ZlibBoost

## Introduction
ZlibBoost is an open-source framework designed for standard cell library characterization.It offers multi-threaded simulation capabilities for both sequential and combinational cells, supporting industry-standard simulators like Spectre and HSPICE, as well as the open-source simulator Ngspice. The tool uses separate TCL files for configuration parameters and template parameters, providing a structured and organized approach. Examples of library characterization are provided using the open-source FreePDK45 technology nodes.

## Configuration Parameters
Configuration parameters are provided via `set_var <name> <value>` in the config TCL files passed to `-c/--config`. The refactored CLI merges config files in order and auto-detects the timing TCL from `template_file`. Required by the pipeline: `extsim_deck_dir`, `template_file`, `spicefiles`, and `report_path`.
| Command                 | Example                    | Description                                                                 |
| :---------------------- | :------------------------- | :-------------------------------------------------------------------------- |
| extsim_deck_dir         | ./spice_deck               | Output directory for generated SPICE decks.                                 |
| template_file           | ./t65.tcl                  | Timing/characterization TCL file (auto-detected by CLI).                    |
| spicefiles              | ./examples/sky130/netlist  | Directory containing cell netlists.                                         |
| spicefiles_format       | sp                         | Netlist file extension (sp/spi/scs/spice); defaults by simulator.           |
| modelfiles              | ./models/tt.scs            | Model include path; used with `.inc` or `.lib` directives.                  |
| lib_corner              | tt                         | Optional corner name for `.lib`; omit to use `.inc`.                        |
| report_path             | ./report                   | Output directory for JSON/Liberty exports and pipeline reports.             |
| simulate_out_dir        | ./t65_spectre             | Optional simulation output root; defaults to deck output directory.         |
| simulate_types          | hidden,leakage,delay       | Optional sim type filter (comma/space separated; hidden/leakage/delay/setup/hold/recovery/removal/mpw). |
| spice_simulator         | spectre                    | SPICE engine: spectre, hspice, ngspice.                                     |
| voltage                 | 1.2                        | Supply voltage (V).                                                         |
| temp                    | 25                         | Temperature (C).                                                            |
| threads                 | 4                          | Worker threads for simulation scheduler.                                    |
| vdd_name                | VDD                        | VDD net name in decks.                                                      |
| gnd_name                | VSS                        | Ground net name in decks.                                                   |
| vpw_name                | VPB                        | Optional p-well net name (set with `vnw_name`).                             |
| vnw_name                | VNB                        | Optional n-well net name (set with `vpw_name`).                             |
| gnw_name                | VNB                        | Sky130 n-well net name (stored for compatibility).                          |
| delay_inp_rise          | 0.5                        | Input rise threshold for delay measurement.                                 |
| delay_inp_fall          | 0.5                        | Input fall threshold for delay measurement.                                 |
| delay_out_rise          | 0.5                        | Output rise threshold for delay measurement.                                |
| delay_out_fall          | 0.5                        | Output fall threshold for delay measurement.                                |
| measure_slew_lower_rise | 0.3                        | Lower threshold for rise slew measurement.                                  |
| measure_slew_upper_rise | 0.7                        | Upper threshold for rise slew measurement.                                  |
| measure_slew_lower_fall | 0.3                        | Lower threshold for fall slew measurement.                                  |
| measure_slew_upper_fall | 0.7                        | Upper threshold for fall slew measurement.                                  |
| measure_cap_lower_rise  | 0.2                        | Lower threshold for rise capacitance measurement.                           |
| measure_cap_upper_rise  | 0.8                        | Upper threshold for rise capacitance measurement.                           |
| measure_cap_lower_fall  | 0.2                        | Lower threshold for fall capacitance measurement.                           |
| measure_cap_upper_fall  | 0.8                        | Upper threshold for fall capacitance measurement.                           |
| mpw_search_bound        | 5e-9                       | Initial search bound for min pulse width measurements.                      |
| driver_waveform         | 2                          | Driver waveform type: 1=linear, 2=exp, 3=mixed.                              |
| subtract_hidden_power   | 0                          | Legacy switch for hidden-power subtraction (stored in config).              |
| arc_mode                | 1                          | Legacy arc flag; auto-arc is controlled by `ZLIBBOOST_AUTO_ARC`.             |


## Template Parameters
The template (timing/characterization) TCL defines cells, templates, arcs, and waveforms. These commands are parsed after the config files and can be mixed with `set_var` if needed.
| Command                 | Description                                                                |
| :---------------------- |:-------------------------------------------------------------------------- |
| set cells                       | Specify the cells to be characterized.                           |
| define_driver_waveform          | Defines the input waveform used to stimulate the cell during characterization.  |  
| define_template                 | Defines a template to be used for characterization.                |
| define_cell                     | Defines how a cell is to be characterized.                         |
| define_function                 | Defines the logical function of the cell.                                  |
| define_leakage                  | Defines the logic conditions under which leakage power is calculated for the selected cells.    |
| define_arc                      | Specify a user-defined arc to override automatic arc determination                       |

Note: waveform shape selection uses `driver_waveform` (config) or `DRIVER_WAVEFORM_TYPE` (env); the `-type` field in `define_driver_waveform` is preserved as metadata.

## Environment Variables
The refactored CLI also accepts environment variables:
| Variable                | Example                 | Description                                                                 |
| :---------------------- | :---------------------- | :-------------------------------------------------------------------------- |
| ZLIBBOOST_LOG_LEVEL     | DEBUG                   | Logging level (DEBUG/INFO/WARNING/ERROR/CRITICAL).                          |
| ZLIBBOOST_SIM_ENGINE    | spectre                 | Simulation engine override (spectre/hspice/ngspice/mock).                   |
| ZLIBBOOST_SIMULATE      | 0                       | Default for simulation when `--simulate/--no-simulate` is not set.          |
| ZLIBBOOST_AUTO_ARC      | 1                       | Enable/disable auto arc generation (default on).                            |
| ZLIBBOOST_SIM_TYPES     | hidden,leakage,delay    | Fallback sim type filter if `simulate_types` is not set in config.          |
| DRIVER_WAVEFORM_TYPE    | 2                       | Driver waveform shape (1=linear, 2=exp, 3=mixed); usually set via config.   |

## Usage
To run a simulation, specify the necessary parameters according to your simulation requirements. The parameters can be provided in a configuration file or directly on the command line, depending on the implementation of your simulation framework.

### Example

```bash
❯ python -m zlibboost.cli.main -h                        
usage: zlibboost [-h] [-c CONFIG] [--simulate | --no-simulate]

options:
  -h, --help            show this help message and exit
  -c, --config CONFIG   Config TCL file (repeatable). Template files referenced inside the config will be auto-detected.
  --simulate, --no-simulate
                        Run simulations after deck generation. Use --no-simulate to skip.
```

```
python -m zlibboost.cli.main -c examples/config_f45.tcl
```

## Related Project
- [ZlibValidation](https://github.com/Cedar17/ZlibValidation) — Command line tool to validate standard cell libraries in `.lib` format.
