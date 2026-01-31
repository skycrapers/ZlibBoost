set cells { \
  AND2X1\
  NAND2X1\
  DFFPOSX1 \
  DFFNEGX1 \
  XOR2X1 \
}

define_driver_waveform -type delay \
       -index_1 {0.0049 0.0125 0.0277 0.0582 0.1192 0.2412 0.4851 } \
       -index_2 {0 0.065 0.195367 0.3 0.354322 0.40575 0.505974 0.554744 0.605641 0.7 0.778634 0.855336 0.940439 0.988381 0.999 } \
       delay_waveform

define_driver_waveform -type constraint \
       -index_1 {0.0049 0.0582 0.4851} \
       -index_2 {0 0.065 0.195367 0.3 0.354322 0.40575 0.505974 0.554744 0.605641 0.7 0.778634 0.855336 0.940439 0.988381 0.999}\
       constraint_waveform

define_template -type delay \
         -index_1 {0.0049 0.0125 0.0277 0.0582 0.1192 0.2412 0.4851 } \
         -index_2 {0.00053 0.00099 0.00191 0.00375 0.00744 0.01481 0.02955 } \
         delay_template_7x7

define_template -type power \
         -index_1 {0.0049 0.0125 0.0277 0.0582 0.1192 0.2412 0.4851 } \
         -index_2 {0.00053 0.00099 0.00191 0.00375 0.00744 0.01481 0.02955 } \
         power_template_7x7

define_template -type constraint \
         -index_1 {0.0049 0.0582  0.4851 } \
         -index_2 {0.0049 0.0582  0.4851 } \
         constraint_template_3x3

define_template -type delay \
         -index_1 {0.0049 0.0125 0.0277 0.0582 0.1192 0.2412 0.4851 } \
         -index_2 {0.00077 0.0017 0.00355 0.00725 0.01466 0.02947 0.0591 } \
         delay_template_7x7_1

define_template -type power \
         -index_1 {0.0049 0.0125 0.0277 0.0582 0.1192 0.2412 0.4851 } \
         -index_2 {0.00077 0.0017 0.00355 0.00725 0.01466 0.02947 0.0591 } \
         power_template_7x7_1


if {[ALAPI_active_cell "AND2X1"]} {
define_cell \
       -input { A B } \
       -output { Y } \
       -pinlist { Y B A } \
       -delay delay_template_7x7 \
       -power power_template_7x7 \
       AND2X1

define_function -function Y=A*B AND2X1
}

if {[ALAPI_active_cell "NAND2X1"]} {
define_cell \
       -input { A B } \
       -output { Y } \
       -pinlist { Y A B } \
       -delay delay_template_7x7_1 \
       -power power_template_7x7_1 \
       NAND2X1

define_function -function Y=!(A*B) NAND2X1
}

if {[ALAPI_active_cell "DFFPOSX1"]} {
define_cell \
       -clock { CLK } \
       -input { D } \
       -data { D }\
       -output { Q } \
       -pinlist { CLK D Q } \
       -delay delay_template_7x7_1 \
       -power power_template_7x7_1 \
       -constraint constraint_template_3x3 \
       DFFPOSX1

define_function -function Q=D DFFPOSX1
}

if {[ALAPI_active_cell "DFFNEGX1"]} {
define_cell \
       -clocknegative { CLK } \
       -input { D} \
       -data { D }\
       -output { Q } \
       -pinlist { CLK D Q } \
       -delay delay_template_7x7_1 \
       -power power_template_7x7_1 \
       -constraint constraint_template_3x3 \
       DFFNEGX1

define_function -function Q=D DFFNEGX1
}

if {[ALAPI_active_cell "XOR2X1"]} {
define_cell \
       -input { A B} \
       -output { Y } \
       -pinlist { Y B A } \
       -delay delay_template_7x7_1 \
       -power power_template_7x7_1 \
       XOR2X1

define_function -function Y=A^B XOR2X1
}
