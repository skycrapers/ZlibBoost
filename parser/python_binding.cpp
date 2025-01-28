#include <pybind11/pybind11.h>
#include <pybind11/stl.h> // For automatic STL type conversion
#include "lib_parser_api.hpp"
#include "lib_modify_api.hpp"

namespace py = pybind11;

PYBIND11_MODULE(liberty_api, m) {
    m.doc() = "Python bindings for Liberty file parsing and modification";

    // DataLut
    py::class_<DataLut>(m, "DataLut")
        .def(py::init<>())
        .def_readwrite("index1", &DataLut::index1)
        .def_readwrite("index2", &DataLut::index2)
        .def_readwrite("values", &DataLut::values);

    py::class_<TimingArc>(m, "TimingArc")
        .def(py::init<>())
        .def_readwrite("when", &TimingArc::when)
        .def_readwrite("related_pin", &TimingArc::relatedPin)
        .def_readwrite("timing_type", &TimingArc::timingType)
        .def_readwrite("timing_sense", &TimingArc::timingSense)
        .def_readwrite("cell_rise", &TimingArc::cellRise)
        .def_readwrite("rise_transition", &TimingArc::riseTransition)
        .def_readwrite("cell_fall", &TimingArc::cellFall)
        .def_readwrite("fall_transition", &TimingArc::fallTransition)
        .def_readwrite("rise_constraint", &TimingArc::riseConstrain)
        .def_readwrite("fall_constraint", &TimingArc::fallConstrain);

    py::class_<PowerArc>(m, "PowerArc")
        .def(py::init<>())
        .def_readwrite("when", &PowerArc::when)
        .def_readwrite("related_pin", &PowerArc::relatedPin)
        .def_readwrite("related_pg_pin", &PowerArc::relatedPGpin)
        .def_readwrite("cell_rise", &PowerArc::cellRise)
        .def_readwrite("cell_fall", &PowerArc::cellFall);

    py::class_<LeakagePower>(m, "LeakagePower")
        .def(py::init<>())
        .def_readwrite("value", &LeakagePower::value)
        .def_readwrite("when", &LeakagePower::when)
        .def_readwrite("related_pg_pin", &LeakagePower::relatedPGpin);

    py::class_<outputPinInfo>(m, "OutputPinInfo")
        .def(py::init<>())
        .def_readwrite("pin_name", &outputPinInfo::pinName)
        .def_readwrite("function", &outputPinInfo::function)
        .def_readwrite("timing_arcs", &outputPinInfo::timingArcs)
        .def_readwrite("power_arcs", &outputPinInfo::powerArcs);

    py::class_<inputPinInfo>(m, "InputPinInfo")
        .def(py::init<>())
        .def_readwrite("pin_name", &inputPinInfo::pinName)
        .def_readwrite("capacitance", &inputPinInfo::capacitance)
        .def_readwrite("rise_capacitance", &inputPinInfo::rise_capacitance)
        .def_readwrite("fall_capacitance", &inputPinInfo::fall_capacitance)
        .def_readwrite("rise_capacitance_range", &inputPinInfo::rise_capacitance_range)
        .def_readwrite("fall_capacitance_range", &inputPinInfo::fall_capacitance_range)
        .def_readwrite("timing_arcs", &inputPinInfo::timingArcs)
        .def_readwrite("power_arcs", &inputPinInfo::powerArcs);

    py::class_<CellInfo>(m, "CellInfo")
        .def(py::init<>())
        .def_readwrite("cell_name", &CellInfo::cellName)
        .def_readwrite("output_pins", &CellInfo::outputPins)
        .def_readwrite("input_pins", &CellInfo::inputPins)
        .def_readwrite("leakages", &CellInfo::leakages);

    py::class_<PVT>(m, "PVT")
        .def(py::init<>())
        .def_readwrite("voltage", &PVT::voltage)
        .def_readwrite("temperature", &PVT::temperature)
        .def_readwrite("process", &PVT::process);

    // Parse interface
    m.def("parse_liberty",
          [](const std::string &libFile,
             const std::string &process,
             const std::string &dumpJsonFile) {
              auto result = parseLibertyAndGetCells(libFile, process, dumpJsonFile);
              return py::make_tuple(result.first, result.second);
          },
          py::arg("lib_file"),
          py::arg("process") = "TT",
          py::arg("dump_json_file") = "",
          "Parse Liberty file and optionally dump to JSON. Returns (pvt, cells).");

    // Modify interface
    m.def("modify_liberty",
          [](const std::string &originalLib,
             const std::string &jsonFile,
             const std::string &outputLib) {
              bool ok = modifyLibertyFile(originalLib, jsonFile, outputLib);
              return ok;
          },
          py::arg("original_lib_file"),
          py::arg("json_file"),
          py::arg("output_lib_file"),
          R"doc(
             使用 JSON 文件中的信息更新原始 .lib，并将结果写到新的 .lib。
             返回是否成功（bool）。
          )doc");
}
