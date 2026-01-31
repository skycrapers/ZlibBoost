set_var extsim_deck_dir ./f45_spice_deck
set_var template_file ./freepdk45.tcl

set_var measure_slew_lower_rise 0.3
set_var measure_slew_lower_fall 0.3
set_var measure_slew_upper_rise 0.7
set_var measure_slew_upper_fall 0.7

set_var delay_inp_rise 0.5
set_var delay_inp_fall 0.5
set_var delay_out_rise 0.5
set_var delay_out_fall 0.5

set_var measure_cap_lower_fall 0.2
set_var measure_cap_upper_fall 0.8
set_var measure_cap_lower_rise 0.2
set_var measure_cap_upper_rise 0.8

set_var subtract_hidden_power 0
set_var mpw_search_bound 5e-9
set_var driver_waveform 3
set_var arc_mode 1

set_var voltage 1.2
set_var temp 25
set_var threads 24
set_var vdd_name vdd
set_var gnd_name vss
set_var spice_simulator hspice

set_var spicefiles ./examples/freepdk45/netlist
set_var spicefiles_format spi
set_var modelfiles ./examples/freepdk45/models/hspice/hspice_nom.include
set_var lib_corner tt
set_var report_path ./f45_report
set_var simulate_out_dir ./f45_simulate
