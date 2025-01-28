#pragma once

#include <string>
#include <vector>
#include <optional>
#include <utility>

/**
 * @brief PVT information
 *  - voltage: nominal voltage
 *  - temperature: nominal temperature
 *  - process: represents SS/TT/FF etc., stored as integer vector
 */
struct PVT {
    double voltage = 0.0;
    long temperature = 0;
    std::vector<int> process; 
};

/**
 * @brief DataLut: lookup table with index1/index2 and 2D values
 */
struct DataLut {
    std::vector<double> index1;
    std::vector<double> index2;
    std::vector<std::vector<double>> values;

    double &at(size_t i, size_t j) {
        return values[i][j];
    }
    const double &at(size_t i, size_t j) const {
        return values[i][j];
    }
};

/**
 * @brief TimingArc: represents timing arc
 *  - when/relatedPin/timingType/timingSense attributes
 *  - cell_rise/rise_transition/cell_fall/fall_transition/rise_constraint/fall_constraint tables
 */
struct TimingArc {
    std::string when;
    std::string relatedPin;
    std::string timingType;
    std::string timingSense;

    DataLut cellRise;
    DataLut riseTransition;
    DataLut cellFall;
    DataLut fallTransition;
    DataLut riseConstrain;
    DataLut fallConstrain;
};

/**
 * @brief PowerArc: represents internal power arc
 *  - when/relatedPin/relatedPGpin attributes 
 *  - rise_power/fall_power tables
 */
struct PowerArc {
    std::string when;
    std::string relatedPin;
    std::string relatedPGpin;

    DataLut cellRise;
    DataLut cellFall;
};

/**
 * @brief Output pin information
 */
struct outputPinInfo {
    std::string pinName;
    std::string function;
    std::vector<TimingArc> timingArcs;
    std::vector<PowerArc> powerArcs;
};

/**
 * @brief Input pin information
 *  - pin capacitance attributes
 *  - timing/power arcs
 */
struct inputPinInfo {
    std::string pinName;
    std::optional<double> capacitance;
    std::optional<double> rise_capacitance;
    std::optional<double> fall_capacitance;
    std::pair<std::optional<double>, std::optional<double>> rise_capacitance_range;
    std::pair<std::optional<double>, std::optional<double>> fall_capacitance_range;

    std::vector<TimingArc> timingArcs;
    std::vector<PowerArc> powerArcs;
};

/**
 * @brief Leakage power information
 */
struct LeakagePower {
    double value = 0.0;
    std::string when;
    std::string relatedPGpin;
};

/**
 * @brief Cell information containing input/output pins
 */
struct CellInfo {
    std::string cellName;
    std::vector<LeakagePower> leakages;
    std::vector<outputPinInfo> outputPins;
    std::vector<inputPinInfo>  inputPins;
};

/**
 * @brief Parse given Liberty file and return (PVT, Cells)
 *
 * @param libFile path to Liberty file to parse
 * @param process string for pvt.process ("SS"/"TT"/"FF" etc)
 * @param dumpJsonFile optional path to dump parse results as JSON
 * @return (pvt, cells) pair
 */
std::pair<PVT, std::vector<CellInfo>>
parseLibertyAndGetCells(const std::string &libFile,
                        const std::string &process,
                        const std::string &dumpJsonFile = "");