#include "lib_parser_api.hpp"
#include "si2dr_liberty.h"

#include <iostream>
#include <sstream>
#include <vector>
#include <string>
#include <fstream>
#include <optional>
#include <cstring>
#include <cstdlib>

#include <json.hpp>
using json = nlohmann::json;

//-------------------------------------
// Helper functions
//-------------------------------------

/**
 * @brief Convert DataLut to JSON
 */
static json dataLutToJson(const DataLut &lut)
{
    json j;
    if (!lut.index1.empty()) {
        j["index1"] = lut.index1;
    }
    if (!lut.index2.empty()) {
        j["index2"] = lut.index2;
    }
    if (!lut.values.empty()) {
        j["values"] = lut.values;
    }
    return j;
}

/**
 * @brief Convert TimingArc to JSON
 */
static json timingArcToJson(const TimingArc &arc)
{
    json j;
    if (!arc.when.empty()) j["when"] = arc.when;
    if (!arc.relatedPin.empty()) j["related_pin"] = arc.relatedPin;
    if (!arc.timingType.empty()) j["timing_type"] = arc.timingType;
    if (!arc.timingSense.empty()) j["timing_sense"] = arc.timingSense;

    if (!arc.cellRise.index1.empty() || !arc.cellRise.index2.empty() || !arc.cellRise.values.empty()) {
        j["cell_rise"] = dataLutToJson(arc.cellRise);
    }
    if (!arc.riseTransition.index1.empty() || !arc.riseTransition.index2.empty() || !arc.riseTransition.values.empty()) {
        j["rise_transition"] = dataLutToJson(arc.riseTransition);
    }
    if (!arc.cellFall.index1.empty() || !arc.cellFall.index2.empty() || !arc.cellFall.values.empty()) {
        j["cell_fall"] = dataLutToJson(arc.cellFall);
    }
    if (!arc.fallTransition.index1.empty() || !arc.fallTransition.index2.empty() || !arc.fallTransition.values.empty()) {
        j["fall_transition"] = dataLutToJson(arc.fallTransition);
    }
    if (!arc.riseConstrain.index1.empty() || !arc.riseConstrain.index2.empty() || !arc.riseConstrain.values.empty()) {
        j["rise_constraint"] = dataLutToJson(arc.riseConstrain);
    }
    if (!arc.fallConstrain.index1.empty() || !arc.fallConstrain.index2.empty() || !arc.fallConstrain.values.empty()) {
        j["fall_constraint"] = dataLutToJson(arc.fallConstrain);
    }

    return j;
}

/**
 * @brief Convert PowerArc to JSON
 */
static json powerArcToJson(const PowerArc &arc)
{
    json j;
    if (!arc.when.empty()) j["when"] = arc.when;
    if (!arc.relatedPin.empty()) j["related_pin"] = arc.relatedPin;
    if (!arc.relatedPGpin.empty()) j["related_pg_pin"] = arc.relatedPGpin;

    if (!arc.cellRise.index1.empty() || !arc.cellRise.index2.empty() || !arc.cellRise.values.empty()) {
        j["cell_rise"] = dataLutToJson(arc.cellRise);
    }
    if (!arc.cellFall.index1.empty() || !arc.cellFall.index2.empty() || !arc.cellFall.values.empty()) {
        j["cell_fall"] = dataLutToJson(arc.cellFall);
    }
    return j;
}

/**
 * @brief Convert LeakagePower to JSON
 */
static json leakageToJson(const LeakagePower &lp)
{
    json j;
    j["value"] = lp.value;
    if (!lp.when.empty()) {
        j["when"] = lp.when;
    }
    if (!lp.relatedPGpin.empty()) {
        j["related_pg_pin"] = lp.relatedPGpin;
    }
    return j;
}

/**
 * @brief Convert inputPinInfo to JSON
 */
static json inputPinInfoToJson(const inputPinInfo &pin)
{
    json j;
    j["pin_name"] = pin.pinName;
    if (pin.capacitance.has_value()) {
        j["capacitance"] = pin.capacitance.value();
    }
    if (pin.rise_capacitance.has_value()) {
        j["rise_capacitance"] = pin.rise_capacitance.value();
    }
    if (pin.fall_capacitance.has_value()) {
        j["fall_capacitance"] = pin.fall_capacitance.value();
    }
    if (pin.rise_capacitance_range.first.has_value() || pin.rise_capacitance_range.second.has_value()) {
        j["rise_capacitance_range"] = {
            pin.rise_capacitance_range.first.value_or(0.0),
            pin.rise_capacitance_range.second.value_or(0.0)
        };
    }
    if (pin.fall_capacitance_range.first.has_value() || pin.fall_capacitance_range.second.has_value()) {
        j["fall_capacitance_range"] = {
            pin.fall_capacitance_range.first.value_or(0.0),
            pin.fall_capacitance_range.second.value_or(0.0)
        };
    }
    // timing_arcs
    if (!pin.timingArcs.empty()) {
        json tarcs = json::array();
        for (auto &ta : pin.timingArcs) {
            tarcs.push_back(timingArcToJson(ta));
        }
        j["timing_arcs"] = tarcs;
    }
    // power_arcs
    if (!pin.powerArcs.empty()) {
        json parcs = json::array();
        for (auto &pa : pin.powerArcs) {
            parcs.push_back(powerArcToJson(pa));
        }
        j["power_arcs"] = parcs;
    }
    return j;
}

/**
 * @brief Convert outputPinInfo to JSON
 */
static json outputPinInfoToJson(const outputPinInfo &pin)
{
    json j;
    j["pin_name"] = pin.pinName;
    if (!pin.function.empty()) {
        j["function"] = pin.function;
    }
    // timing_arcs
    if (!pin.timingArcs.empty()) {
        json tarcs = json::array();
        for (auto &ta : pin.timingArcs) {
            tarcs.push_back(timingArcToJson(ta));
        }
        j["timing_arcs"] = tarcs;
    }
    // power_arcs
    if (!pin.powerArcs.empty()) {
        json parcs = json::array();
        for (auto &pa : pin.powerArcs) {
            parcs.push_back(powerArcToJson(pa));
        }
        j["power_arcs"] = parcs;
    }
    return j;
}

/**
 * @brief Convert CellInfo to JSON
 */
static json cellInfoToJson(const CellInfo &cell)
{
    json j;
    j["cell_name"] = cell.cellName;

    // output_pins
    if (!cell.outputPins.empty()) {
        json outs = json::array();
        for (auto &op : cell.outputPins) {
            outs.push_back(outputPinInfoToJson(op));
        }
        j["output_pins"] = outs;
    }
    // input_pins
    if (!cell.inputPins.empty()) {
        json ins = json::array();
        for (auto &ip : cell.inputPins) {
            ins.push_back(inputPinInfoToJson(ip));
        }
        j["input_pins"] = ins;
    }
    // leakages
    if (!cell.leakages.empty()) {
        json leaks = json::array();
        for (auto &lk : cell.leakages) {
            leaks.push_back(leakageToJson(lk));
        }
        j["leakage_power"] = leaks;  // Store multiple leakage_power
    }
    return j;
}

/**
 * @brief Export all cells + pvt to JSON
 */
static void dumpCellsToJson(const std::vector<CellInfo> &cells,
                            const PVT &pvt,
                            const std::string &fileName)
{
    json root;
    root["voltage"] = pvt.voltage;
    root["temperature"] = pvt.temperature;
    root["process"] = pvt.process;

    json cellsArr = json::array();
    for (auto &c : cells) {
        cellsArr.push_back(cellInfoToJson(c));
    }
    root["cells"] = cellsArr;

    std::ofstream ofs(fileName);
    if (ofs.is_open()) {
        // Output in a neat format
        ofs << root.dump(2) << std::endl;
        ofs.close();
        std::cout << "Dumped parse result to JSON: " << fileName << std::endl;
    } else {
        std::cerr << "Failed to open " << fileName << " for writing.\n";
    }
}

//-------------------------------------

// Main logic for parsing Liberty (including parseLeakage)

/**
 * @brief Parse single "leakage_power" group
 */
static void parseLeakage(si2drGroupIdT leakageGroup,
                         LeakagePower &lp,
                         si2drErrorT *err)
{
    // 1) value
    si2drAttrIdT valAttr =
        si2drGroupFindAttrByName(leakageGroup, const_cast<char*>("value"), err);
    if (!si2drObjectIsNull(valAttr, err)) {
        double val = si2drSimpleAttrGetFloat64Value(valAttr, err);
        lp.value = val;
    }
    // 2) when
    si2drAttrIdT whenAttr =
        si2drGroupFindAttrByName(leakageGroup, const_cast<char*>("when"), err);
    if (!si2drObjectIsNull(whenAttr, err)) {
        si2drStringT wh = si2drSimpleAttrGetStringValue(whenAttr, err);
        if (wh) {
            lp.when = wh;
        }
    }
    // 3) related_pg_pin
    si2drAttrIdT rpgAttr =
        si2drGroupFindAttrByName(leakageGroup, const_cast<char*>("related_pg_pin"), err);
    if (!si2drObjectIsNull(rpgAttr, err)) {
        si2drStringT rpg = si2drSimpleAttrGetStringValue(rpgAttr, err);
        if (rpg) {
            lp.relatedPGpin = rpg;
        }
    }
}

/**
 * @brief Parse "leakage_power" groups at the same level as pin in cell
 */
static void processLeakage(si2drGroupIdT cellGroup,
                           std::vector<LeakagePower> &leaks,
                           si2drErrorT *err)
{
    si2drGroupsIdT subGrps = si2drGroupGetGroups(cellGroup, err);
    si2drGroupIdT oneGroup;
    while (!si2drObjectIsNull((oneGroup = si2drIterNextGroup(subGrps, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(oneGroup, err);
        if (strcmp(groupType, "leakage_power") == 0) {
            LeakagePower lp;
            parseLeakage(oneGroup, lp, err);
            leaks.push_back(lp);
        }
    }
    si2drIterQuit(subGrps, err);
}

//-------------------------------------

// (The rest of the parse logic is the same, just added processing for leakage_power)

static void getPVT(si2drGroupIdT group, PVT &pvt, si2drErrorT *err)
{
    si2drAttrIdT voltageAttr =
        si2drGroupFindAttrByName(group, const_cast<char *>("nom_voltage"), err);
    if (!si2drObjectIsNull(voltageAttr, err)) {
        pvt.voltage = si2drSimpleAttrGetFloat64Value(voltageAttr, err);
    }

    si2drAttrIdT temperatureAttr =
        si2drGroupFindAttrByName(group, const_cast<char *>("nom_temperature"), err);
    if (!si2drObjectIsNull(temperatureAttr, err)) {
        pvt.temperature = si2drSimpleAttrGetInt32Value(temperatureAttr, err);
    }
}

static std::vector<double>
parseComplexAttrToFloats(si2drAttrIdT attr, si2drErrorT *err)
{
    std::vector<double> result;
    si2drValuesIdT valuesId = si2drComplexAttrGetValues(attr, err);
    si2drValueTypeT valueType;
    si2drStringT strVal;
    si2drInt32T intVal;
    si2drFloat64T floatVal;
    si2drBooleanT boolVal;
    si2drExprT *exprVal;

    while (true) {
        si2drIterNextComplexValue(valuesId, &valueType,
                                  &intVal, &floatVal, &strVal,
                                  &boolVal, &exprVal, err);
        if (valueType == SI2DR_UNDEFINED_VALUETYPE) {
            break;
        }
        if (valueType == SI2DR_STRING) {
            std::stringstream ss(strVal);
            std::string token;
            while (std::getline(ss, token, ',')) {
                if(!token.empty()) {
                    double val = std::stod(token);
                    result.push_back(val);
                }
            }
        } else if (valueType == SI2DR_FLOAT64) {
            result.push_back(floatVal);
        }
    }
    si2drIterQuit(valuesId, err);
    return result;
}

static std::vector<std::vector<double>>
parseComplexAttrValuesToFloats(si2drAttrIdT attr, si2drErrorT *err)
{
    std::vector<std::vector<double>> result;
    si2drValuesIdT valuesId = si2drComplexAttrGetValues(attr, err);
    si2drValueTypeT valueType;
    si2drStringT strVal;
    si2drInt32T intVal;
    si2drFloat64T floatVal;
    si2drBooleanT boolVal;
    si2drExprT *exprVal;

    while (true) {
        si2drIterNextComplexValue(valuesId, &valueType,
                                  &intVal, &floatVal, &strVal,
                                  &boolVal, &exprVal, err);
        if (valueType == SI2DR_UNDEFINED_VALUETYPE) {
            break;
        }
        if (valueType == SI2DR_STRING) {
            std::stringstream ss(strVal);
            std::string line;
            while (std::getline(ss, line)) {
                if(line.empty()) continue;
                std::vector<double> row;
                std::stringstream lineStream(line);
                std::string token;
                while (std::getline(lineStream, token, ',')) {
                    if(!token.empty()) {
                        double val = std::stod(token);
                        row.push_back(val);
                    }
                }
                if(!row.empty()) {
                    result.push_back(row);
                }
            }
        }
    }
    si2drIterQuit(valuesId, err);
    return result;
}

static void fillDataLut(si2drGroupIdT group, DataLut &dataLut, si2drErrorT *err)
{
    si2drAttrIdT index1Attr =
        si2drGroupFindAttrByName(group, const_cast<char *>("index_1"), err);
    if (!si2drObjectIsNull(index1Attr, err)) {
        dataLut.index1 = parseComplexAttrToFloats(index1Attr, err);
    }

    si2drAttrIdT index2Attr =
        si2drGroupFindAttrByName(group, const_cast<char *>("index_2"), err);
    if (!si2drObjectIsNull(index2Attr, err)) {
        dataLut.index2 = parseComplexAttrToFloats(index2Attr, err);
    }

    si2drAttrIdT valuesAttr =
        si2drGroupFindAttrByName(group, const_cast<char *>("values"), err);
    if (!si2drObjectIsNull(valuesAttr, err)) {
        dataLut.values = parseComplexAttrValuesToFloats(valuesAttr, err);
    }
}

static void findTimingGroups(si2drGroupIdT timingGroup,
                             TimingArc &timingArc,
                             si2drErrorT *err)
{
    si2drGroupsIdT subGroups = si2drGroupGetGroups(timingGroup, err);
    si2drGroupIdT subGroup;

    while (!si2drObjectIsNull((subGroup = si2drIterNextGroup(subGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(subGroup, err);
        if (strcmp(groupType, "cell_rise") == 0) {
            fillDataLut(subGroup, timingArc.cellRise, err);
        } else if (strcmp(groupType, "rise_transition") == 0) {
            fillDataLut(subGroup, timingArc.riseTransition, err);
        } else if (strcmp(groupType, "cell_fall") == 0) {
            fillDataLut(subGroup, timingArc.cellFall, err);
        } else if (strcmp(groupType, "fall_transition") == 0) {
            fillDataLut(subGroup, timingArc.fallTransition, err);
        } else if (strcmp(groupType, "rise_constraint") == 0) {
            fillDataLut(subGroup, timingArc.riseConstrain, err);
        } else if (strcmp(groupType, "fall_constraint") == 0) {
            fillDataLut(subGroup, timingArc.fallConstrain, err);
        }
    }
    si2drIterQuit(subGroups, err);
}

static void findPowerGroups(si2drGroupIdT powerGroup,
                            PowerArc &powerArc,
                            si2drErrorT *err)
{
    si2drGroupsIdT subGroups = si2drGroupGetGroups(powerGroup, err);
    si2drGroupIdT subGroup;

    while (!si2drObjectIsNull((subGroup = si2drIterNextGroup(subGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(subGroup, err);
        if (strcmp(groupType, "rise_power") == 0) {
            fillDataLut(subGroup, powerArc.cellRise, err);
        } else if (strcmp(groupType, "fall_power") == 0) {
            fillDataLut(subGroup, powerArc.cellFall, err);
        }
    }
    si2drIterQuit(subGroups, err);
}

static void processTimingArcs(si2drGroupIdT pinGroup,
                              si2drErrorT *err,
                              std::vector<TimingArc> &arcStorage)
{
    si2drGroupsIdT pinGroups = si2drGroupGetGroups(pinGroup, err);
    si2drGroupIdT timingGroup;

    while (!si2drObjectIsNull((timingGroup = si2drIterNextGroup(pinGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(timingGroup, err);
        if (strcmp(groupType, "timing") == 0) {
            TimingArc arc;
            // related_pin
            si2drAttrIdT rp = si2drGroupFindAttrByName(timingGroup, const_cast<char *>("related_pin"), err);
            if (!si2drObjectIsNull(rp, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(rp, err);
                if(val) arc.relatedPin = val;
            }
            // when
            si2drAttrIdT wh = si2drGroupFindAttrByName(timingGroup, const_cast<char *>("when"), err);
            if (!si2drObjectIsNull(wh, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(wh, err);
                if(val) arc.when = val;
            }
            // timing_type
            si2drAttrIdT tt = si2drGroupFindAttrByName(timingGroup, const_cast<char *>("timing_type"), err);
            if (!si2drObjectIsNull(tt, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(tt, err);
                if(val) arc.timingType = val;
            }
            // timing_sense
            si2drAttrIdT ts = si2drGroupFindAttrByName(timingGroup, const_cast<char *>("timing_sense"), err);
            if (!si2drObjectIsNull(ts, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(ts, err);
                if(val) arc.timingSense = val;
            }
            // LUT
            findTimingGroups(timingGroup, arc, err);
            arcStorage.push_back(arc);
        }
    }
    si2drIterQuit(pinGroups, err);
}

static void processPowerArcs(si2drGroupIdT pinGroup,
                             si2drErrorT *err,
                             std::vector<PowerArc> &arcStorage)
{
    si2drGroupsIdT pinGroups = si2drGroupGetGroups(pinGroup, err);
    si2drGroupIdT powerGroup;

    while (!si2drObjectIsNull((powerGroup = si2drIterNextGroup(pinGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(powerGroup, err);
        if (strcmp(groupType, "internal_power") == 0) {
            PowerArc arc;
            // when
            si2drAttrIdT wh = si2drGroupFindAttrByName(powerGroup, const_cast<char *>("when"), err);
            if (!si2drObjectIsNull(wh, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(wh, err);
                if(val) arc.when = val;
            }
            // related_pin
            si2drAttrIdT rp = si2drGroupFindAttrByName(powerGroup, const_cast<char *>("related_pin"), err);
            if (!si2drObjectIsNull(rp, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(rp, err);
                if(val) arc.relatedPin = val;
            }
            // related_pg_pin
            si2drAttrIdT rpg = si2drGroupFindAttrByName(powerGroup, const_cast<char *>("related_pg_pin"), err);
            if (!si2drObjectIsNull(rpg, err)) {
                si2drStringT val = si2drSimpleAttrGetStringValue(rpg, err);
                if(val) arc.relatedPGpin = val;
            }
            // LUT
            findPowerGroups(powerGroup, arc, err);
            arcStorage.push_back(arc);
        }
    }
    si2drIterQuit(pinGroups, err);
}

static void processCellPins(si2drGroupIdT cellGroup,
                            CellInfo &cellInfo,
                            si2drErrorT *err)
{
    si2drGroupsIdT cellSubgroups = si2drGroupGetGroups(cellGroup, err);
    si2drGroupIdT pinGroup;

    while (!si2drObjectIsNull((pinGroup = si2drIterNextGroup(cellSubgroups, err)), err)) {
        si2drStringT pinGroupType = si2drGroupGetGroupType(pinGroup, err);
        if (strcmp(pinGroupType, "pin") == 0) {
            // direction
            si2drAttrIdT dirAttr =
                si2drGroupFindAttrByName(pinGroup, const_cast<char *>("direction"), err);
            si2drStringT dirVal = si2drSimpleAttrGetStringValue(dirAttr, err);

            // pin name
            si2drNamesIdT pinNames = si2drGroupGetNames(pinGroup, err);
            si2drStringT pName = si2drIterNextName(pinNames, err);
            si2drIterQuit(pinNames, err);

            std::string pinNameStr = pName ? pName : "";
            if (dirVal && strcmp(dirVal, "output") == 0) {
                // output pin
                outputPinInfo outPin;
                outPin.pinName = pinNameStr;

                // function
                si2drAttrIdT funcAttr =
                    si2drGroupFindAttrByName(pinGroup, const_cast<char *>("function"), err);
                si2drStringT funcVal = si2drSimpleAttrGetStringValue(funcAttr, err);
                if (funcVal) {
                    outPin.function = funcVal;
                }

                // timing arcs
                processTimingArcs(pinGroup, err, outPin.timingArcs);
                // power arcs
                processPowerArcs(pinGroup, err, outPin.powerArcs);

                cellInfo.outputPins.push_back(outPin);

            } else if (dirVal && strcmp(dirVal, "input") == 0) {
                // input pin
                inputPinInfo inPin;
                inPin.pinName = pinNameStr;

                // capacitance
                si2drAttrIdT capAttr =
                    si2drGroupFindAttrByName(pinGroup, const_cast<char *>("capacitance"), err);
                if (!si2drObjectIsNull(capAttr, err)) {
                    double capv = si2drSimpleAttrGetFloat64Value(capAttr, err);
                    inPin.capacitance = capv;
                }

                // rise_capacitance
                si2drAttrIdT riseCapAttr =
                    si2drGroupFindAttrByName(pinGroup, const_cast<char *>("rise_capacitance"), err);
                if (!si2drObjectIsNull(riseCapAttr, err)) {
                    double rcapv = si2drSimpleAttrGetFloat64Value(riseCapAttr, err);
                    inPin.rise_capacitance = rcapv;
                }

                // fall_capacitance
                si2drAttrIdT fallCapAttr =
                    si2drGroupFindAttrByName(pinGroup, const_cast<char *>("fall_capacitance"), err);
                if (!si2drObjectIsNull(fallCapAttr, err)) {
                    double fcapv = si2drSimpleAttrGetFloat64Value(fallCapAttr, err);
                    inPin.fall_capacitance = fcapv;
                }

                // rise_capacitance_range
                si2drAttrIdT riseCapRangeAttr =
                    si2drGroupFindAttrByName(pinGroup, const_cast<char *>("rise_capacitance_range"), err);
                if (!si2drObjectIsNull(riseCapRangeAttr, err)) {
                    auto vals = parseComplexAttrToFloats(riseCapRangeAttr, err);
                    if(vals.size() == 2) {
                        inPin.rise_capacitance_range = {vals[0], vals[1]};
                    }
                }

                // fall_capacitance_range
                si2drAttrIdT fallCapRangeAttr =
                    si2drGroupFindAttrByName(pinGroup, const_cast<char *>("fall_capacitance_range"), err);
                if (!si2drObjectIsNull(fallCapRangeAttr, err)) {
                    auto vals = parseComplexAttrToFloats(fallCapRangeAttr, err);
                    if(vals.size() == 2) {
                        inPin.fall_capacitance_range = {vals[0], vals[1]};
                    }
                }

                // timing arcs
                processTimingArcs(pinGroup, err, inPin.timingArcs);
                // power arcs
                processPowerArcs(pinGroup, err, inPin.powerArcs);

                cellInfo.inputPins.push_back(inPin);
            }
            // Other directions (inout/internal) can be extended
        }
    }
    si2drIterQuit(cellSubgroups, err);
}

static void processCells(si2drGroupIdT libraryGroup,
                         si2drErrorT *err,
                         std::vector<CellInfo> &cells,
                         PVT &pvt)
{
    getPVT(libraryGroup, pvt, err);

    si2drGroupsIdT groups = si2drGroupGetGroups(libraryGroup, err);
    si2drGroupIdT cellGroup;

    while (!si2drObjectIsNull((cellGroup = si2drIterNextGroup(groups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(cellGroup, err);
        if (strcmp(groupType, "cell") == 0) {
            CellInfo cellInfo;

            // cell name
            si2drNamesIdT names = si2drGroupGetNames(cellGroup, err);
            si2drStringT cname = si2drIterNextName(names, err);
            si2drIterQuit(names, err);

            if (cname) {
                cellInfo.cellName = cname;
            }

            // Process pins first
            processCellPins(cellGroup, cellInfo, err);

            // Then process leakage_power (at the same level as pin)
            processLeakage(cellGroup, cellInfo.leakages, err);

            cells.push_back(cellInfo);
        }
    }
    si2drIterQuit(groups, err);
}

std::pair<PVT, std::vector<CellInfo>>
parseLibertyAndGetCells(const std::string &libFile,
                        const std::string &process,
                        const std::string &dumpJsonFile)
{
    // 1) Set pvt.process based on process
    std::vector<int> procVal;
    if(process == "SS") {
        procVal = {1};
    } else if(process == "TT") {
        procVal = {2};
    } else if(process == "FF") {
        procVal = {3};
    } else {
        procVal = {};
    }

    // 2) Initialize
    si2drErrorT err;
    si2drPIInit(&err);

    si2drReadLibertyFile(const_cast<char*>(libFile.c_str()), &err);
    if(err != SI2DR_NO_ERROR) {
        std::cerr << "[ERROR] Failed to read Liberty file: " << libFile << std::endl;
        si2drPIQuit(&err);
        return {};
    }

    PVT pvt;
    pvt.process = procVal;
    std::vector<CellInfo> cells;

    // 3) Traverse top-level groups
    si2drGroupsIdT topGroups = si2drPIGetGroups(&err);
    si2drGroupIdT group;
    while (!si2drObjectIsNull((group = si2drIterNextGroup(topGroups, &err)), &err)) {
        processCells(group, &err, cells, pvt);
    }
    si2drIterQuit(topGroups, &err);

    si2drPIQuit(&err);

    // 4) If dumpJsonFile is not empty, write the result to JSON
    if (!dumpJsonFile.empty()) {
        dumpCellsToJson(cells, pvt, dumpJsonFile);
    }

    return { pvt, cells };
}
