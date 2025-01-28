#include "lib_modify_api.hpp"
#include "lib_parser_api.hpp"
#include "si2dr_liberty.h"
#include "json.hpp"
#include <fstream>
#include <iostream>
#include <sstream>
#include <algorithm>

using json = nlohmann::json;

/**
 * @brief Check if two TimingArcs match (for locating objects to update)
 */
static bool timingArcEquals(const TimingArc &a, const TimingArc &b) {
    return (a.when == b.when) && (a.relatedPin == b.relatedPin) && (a.timingType == b.timingType);
}

/**
 * @brief Check if two PowerArcs match (for locating objects to update)
 */
static bool powerArcEquals(const PowerArc &a, const PowerArc &b) {
    return (a.when == b.when) && (a.relatedPin == b.relatedPin)
           && (a.relatedPGpin == b.relatedPGpin);
}

static bool leakageEquals(const LeakagePower &a, const LeakagePower &b) {
    return (a.when == b.when) && (a.relatedPGpin == b.relatedPGpin);
}

/**
 * @brief Delete and recreate complex attributes (like index_1/index_2/values) for inserting new data
 */
static si2drAttrIdT recreateComplexAttr(si2drGroupIdT group, const char *attrName,
                                        si2drErrorT *err) {
    si2drAttrIdT attr = si2drGroupFindAttrByName(group, const_cast<char *>(attrName), err);
    if (!si2drObjectIsNull(attr, err)) {
        // Delete
        si2drObjectDelete(attr, err);
        if (*err != SI2DR_NO_ERROR) {
            std::cerr << "Failed to delete attribute '" << attrName << "'.\n";
            return si2drPIGetNullId(err);
        }
    }

    // Recreate
    attr = si2drGroupCreateAttr(group, const_cast<char *>(attrName), SI2DR_COMPLEX, err);
    if (*err != SI2DR_NO_ERROR || si2drObjectIsNull(attr, err)) {
        std::cerr << "Failed to create complex attribute '" << attrName << "'.\n";
        return si2drPIGetNullId(err);
    }
    return attr;
}

/**
 * @brief Update DataLut (index1/index2/values) to specified group (cell_rise / rise_transition etc)
 */
static void addArcLut(si2drGroupIdT parentGroup, const std::string &lutGroupType,
                      const DataLut &lut, si2drErrorT *err) {
    si2drGroupsIdT subGroups = si2drGroupGetGroups(parentGroup, err);
    si2drGroupIdT subGroup;
    while (!si2drObjectIsNull((subGroup = si2drIterNextGroup(subGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(subGroup, err);

        // If the subgroup type == the lutGroupType we want to update, e.g., "cell_rise", "fall_power", etc.
        if (std::string(groupType) == lutGroupType) {
            // 1) index_1
            {
                // Delete old and create new attribute
                si2drAttrIdT idx1 = recreateComplexAttr(subGroup, "index_1", err);
                if (si2drObjectIsNull(idx1, err)) {
                    continue; // Skip on error
                }
                // Concatenate to string
                std::ostringstream oss;
                for (size_t i = 0; i < lut.index1.size(); ++i) {
                    oss << lut.index1[i];
                    if (i + 1 < lut.index1.size()) {
                        oss << ", ";
                    }
                }
                // Write
                si2drComplexAttrAddStringValue(idx1, const_cast<char *>(oss.str().c_str()), err);
            }

            // 2) index_2 (only write if lut.index2 is not empty)
            if (!lut.index2.empty()) {
                si2drAttrIdT idx2 = recreateComplexAttr(subGroup, "index_2", err);
                if (!si2drObjectIsNull(idx2, err)) {
                    std::ostringstream oss;
                    for (size_t i = 0; i < lut.index2.size(); ++i) {
                        oss << lut.index2[i];
                        if (i + 1 < lut.index2.size()) {
                            oss << ", ";
                        }
                    }
                    si2drComplexAttrAddStringValue(idx2, const_cast<char *>(oss.str().c_str()),
                                                   err);
                }
            }

            // 3) values
            {
                si2drAttrIdT vals = recreateComplexAttr(subGroup, "values", err);
                if (si2drObjectIsNull(vals, err))
                    continue;

                // One string per line
                for (auto &row : lut.values) {
                    std::ostringstream oss;
                    for (size_t i = 0; i < row.size(); ++i) {
                        oss << row[i];
                        if (i + 1 < row.size()) {
                            oss << ", ";
                        }
                    }
                    si2drComplexAttrAddStringValue(vals, const_cast<char *>(oss.str().c_str()),
                                                   err);
                }
            }
        }
    }
    si2drIterQuit(subGroups, err);
}

/**
 * @brief Update complex attribute with capacitance range values
 */
static void addCapacitanceRangeValues(
    si2drAttrIdT attr, const std::pair<std::optional<double>, std::optional<double>> &range,
    si2drErrorT *err) {
    if (range.first.has_value()) {
        si2drComplexAttrAddFloat64Value(attr, range.first.value(), err);
    }
    if (range.second.has_value()) {
        si2drComplexAttrAddFloat64Value(attr, range.second.value(), err);
    }
}

/**
 * @brief Update LUTs for a timing group (cell_rise, rise_transition, etc)
 */
static void addTimingArcValues(si2drGroupIdT group, const TimingArc &arc, si2drErrorT *err) {
    addArcLut(group, "cell_rise", arc.cellRise, err);
    addArcLut(group, "rise_transition", arc.riseTransition, err);
    addArcLut(group, "cell_fall", arc.cellFall, err);
    addArcLut(group, "fall_transition", arc.fallTransition, err);
    addArcLut(group, "rise_constraint", arc.riseConstrain, err);
    addArcLut(group, "fall_constraint", arc.fallConstrain, err);
}

/**
 * @brief Update power values for an internal_power group
 */
static void addPowerArcValues(si2drGroupIdT group, const PowerArc &arc, si2drErrorT *err) {
    addArcLut(group, "rise_power", arc.cellRise, err);
    addArcLut(group, "fall_power", arc.cellFall, err);
}

/**
 * @brief Update input pin capacitance attributes
 */
static void updateInputCapacitance(const inputPinInfo &jsonPin, si2drGroupIdT pinGroup,
                                   si2drErrorT *err) {
    // capacitance
    if (jsonPin.capacitance.has_value()) {
        si2drAttrIdT capAttr =
            si2drGroupFindAttrByName(pinGroup, const_cast<char *>("capacitance"), err);
        if (!si2drObjectIsNull(capAttr, err)) {
            si2drSimpleAttrSetFloat64Value(capAttr, jsonPin.capacitance.value(), err);
        }
    }

    // rise_capacitance
    if (jsonPin.rise_capacitance.has_value()) {
        si2drAttrIdT riseCapAttr =
            si2drGroupFindAttrByName(pinGroup, const_cast<char *>("rise_capacitance"), err);
        if (!si2drObjectIsNull(riseCapAttr, err)) {
            si2drSimpleAttrSetFloat64Value(riseCapAttr, jsonPin.rise_capacitance.value(), err);
        }
    }

    // fall_capacitance
    if (jsonPin.fall_capacitance.has_value()) {
        si2drAttrIdT fallCapAttr =
            si2drGroupFindAttrByName(pinGroup, const_cast<char *>("fall_capacitance"), err);
        if (!si2drObjectIsNull(fallCapAttr, err)) {
            si2drSimpleAttrSetFloat64Value(fallCapAttr, jsonPin.fall_capacitance.value(), err);
        }
    }

    // rise_capacitance_range
    if (jsonPin.rise_capacitance_range.first.has_value()
        || jsonPin.rise_capacitance_range.second.has_value()) {
        si2drAttrIdT riseCapRangeAttr =
            recreateComplexAttr(pinGroup, "rise_capacitance_range", err);
        if (!si2drObjectIsNull(riseCapRangeAttr, err)) {
            addCapacitanceRangeValues(riseCapRangeAttr, jsonPin.rise_capacitance_range, err);
        }
    }

    // fall_capacitance_range
    if (jsonPin.fall_capacitance_range.first.has_value()
        || jsonPin.fall_capacitance_range.second.has_value()) {
        si2drAttrIdT fallCapRangeAttr =
            recreateComplexAttr(pinGroup, "fall_capacitance_range", err);
        if (!si2drObjectIsNull(fallCapRangeAttr, err)) {
            addCapacitanceRangeValues(fallCapRangeAttr, jsonPin.fall_capacitance_range, err);
        }
    }
}

/**
 * @brief Update timing arcs under pinGroup
 */
static void updateTimingArcs(std::vector<TimingArc> &jsonArcs, si2drGroupIdT pinGroup,
                             si2drErrorT *err) {
    si2drGroupsIdT pinGroups = si2drGroupGetGroups(pinGroup, err);
    si2drGroupIdT timingGroup;

    while (!si2drObjectIsNull((timingGroup = si2drIterNextGroup(pinGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(timingGroup, err);
        if (strcmp(groupType, "timing") == 0) {
            // related_pin
            si2drAttrIdT rpAttr =
                si2drGroupFindAttrByName(timingGroup, const_cast<char *>("related_pin"), err);
            si2drStringT rpVal = si2drSimpleAttrGetStringValue(rpAttr, err);

            // when
            si2drAttrIdT whenAttr =
                si2drGroupFindAttrByName(timingGroup, const_cast<char *>("when"), err);
            si2drStringT whenVal = si2drSimpleAttrGetStringValue(whenAttr, err);

            // timing_type
            si2drAttrIdT ttAttr =
                si2drGroupFindAttrByName(timingGroup, const_cast<char *>("timing_type"), err);
            si2drStringT ttVal = si2drSimpleAttrGetStringValue(ttAttr, err);

            TimingArc existingArc;
            if (rpVal)
                existingArc.relatedPin = rpVal;
            if (whenVal)
                existingArc.when = whenVal;
            if (ttVal)
                existingArc.timingType = ttVal;

            // Find match in jsonArcs
            auto it = std::find_if(jsonArcs.begin(), jsonArcs.end(), [&](const TimingArc &arc) {
                return timingArcEquals(existingArc, arc);
            });
            if (it != jsonArcs.end()) {
                addTimingArcValues(timingGroup, *it, err);
            }
        }
    }
    si2drIterQuit(pinGroups, err);
}

/**
 * @brief Update power arcs under pinGroup
 */
static void updatePowerArcs(std::vector<PowerArc> &jsonArcs, si2drGroupIdT pinGroup,
                            si2drErrorT *err) {
    si2drGroupsIdT pinGroups = si2drGroupGetGroups(pinGroup, err);
    si2drGroupIdT powerGroup;

    while (!si2drObjectIsNull((powerGroup = si2drIterNextGroup(pinGroups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(powerGroup, err);
        if (strcmp(groupType, "internal_power") == 0) {
            // related_pin
            si2drAttrIdT rpAttr =
                si2drGroupFindAttrByName(powerGroup, const_cast<char *>("related_pin"), err);
            si2drStringT rpVal = si2drSimpleAttrGetStringValue(rpAttr, err);

            // when
            si2drAttrIdT whAttr =
                si2drGroupFindAttrByName(powerGroup, const_cast<char *>("when"), err);
            si2drStringT whVal = si2drSimpleAttrGetStringValue(whAttr, err);

            // related_pg_pin
            si2drAttrIdT rpgAttr =
                si2drGroupFindAttrByName(powerGroup, const_cast<char *>("related_pg_pin"), err);
            si2drStringT rpgVal = si2drSimpleAttrGetStringValue(rpgAttr, err);

            PowerArc existingArc;
            if (rpVal)
                existingArc.relatedPin = rpVal;
            if (whVal)
                existingArc.when = whVal;
            if (rpgVal)
                existingArc.relatedPGpin = rpgVal;

            // Find match
            auto it = std::find_if(jsonArcs.begin(), jsonArcs.end(), [&](const PowerArc &arc) {
                return powerArcEquals(existingArc, arc);
            });
            if (it != jsonArcs.end()) {
                addPowerArcValues(powerGroup, *it, err);
            }
        }
    }
    si2drIterQuit(pinGroups, err);
}

/**
 * @brief Update leakage_power group's value/when/related_pg_pin
 */
static void updateLeakagePower(si2drGroupIdT leakageGroup, const LeakagePower &info,
                               si2drErrorT *err) {
    // 1) value
    {
        si2drAttrIdT valAttr =
            si2drGroupFindAttrByName(leakageGroup, const_cast<char *>("value"), err);
        if (si2drObjectIsNull(valAttr, err)) {
            // Create if not exist
            valAttr =
                si2drGroupCreateAttr(leakageGroup, const_cast<char *>("value"), SI2DR_SIMPLE, err);
        }
        // Set float
        si2drSimpleAttrSetFloat64Value(valAttr, info.value, err);
    }

    // 2) when
    if (!info.when.empty()) {
        si2drAttrIdT whenAttr =
            si2drGroupFindAttrByName(leakageGroup, const_cast<char *>("when"), err);
        if (si2drObjectIsNull(whenAttr, err)) {
            whenAttr =
                si2drGroupCreateAttr(leakageGroup, const_cast<char *>("when"), SI2DR_SIMPLE, err);
        }
        si2drSimpleAttrSetStringValue(whenAttr, const_cast<char *>(info.when.c_str()), err);
    }

    // 3) related_pg_pin
    if (!info.relatedPGpin.empty()) {
        si2drAttrIdT rpgAttr =
            si2drGroupFindAttrByName(leakageGroup, const_cast<char *>("related_pg_pin"), err);
        if (si2drObjectIsNull(rpgAttr, err)) {
            rpgAttr = si2drGroupCreateAttr(leakageGroup, const_cast<char *>("related_pg_pin"),
                                           SI2DR_SIMPLE, err);
        }
        si2drSimpleAttrSetStringValue(rpgAttr, const_cast<char *>(info.relatedPGpin.c_str()), err);
    }
}

/**
 * @brief Traverse leakage_power groups under cell and update as needed
 */
static void updateLeakages(std::vector<LeakagePower> &jsonLeakages, si2drGroupIdT cellGroup,
                           si2drErrorT *err) {
    si2drGroupsIdT subGrps = si2drGroupGetGroups(cellGroup, err);
    si2drGroupIdT oneGroup;

    while (!si2drObjectIsNull((oneGroup = si2drIterNextGroup(subGrps, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(oneGroup, err);
        if (strcmp(groupType, "leakage_power") == 0) {
            // Read existing leakagePower
            LeakagePower existing;
            // Read value
            si2drAttrIdT valAttr =
                si2drGroupFindAttrByName(oneGroup, const_cast<char *>("value"), err);
            if (!si2drObjectIsNull(valAttr, err)) {
                existing.value = si2drSimpleAttrGetFloat64Value(valAttr, err);
            }
            // when
            si2drAttrIdT whAttr =
                si2drGroupFindAttrByName(oneGroup, const_cast<char *>("when"), err);
            if (!si2drObjectIsNull(whAttr, err)) {
                si2drStringT w = si2drSimpleAttrGetStringValue(whAttr, err);
                if (w)
                    existing.when = w;
            }
            // related_pg_pin
            si2drAttrIdT rpgAttr =
                si2drGroupFindAttrByName(oneGroup, const_cast<char *>("related_pg_pin"), err);
            if (!si2drObjectIsNull(rpgAttr, err)) {
                si2drStringT rpg = si2drSimpleAttrGetStringValue(rpgAttr, err);
                if (rpg)
                    existing.relatedPGpin = rpg;
            }

            // Find match in jsonLeakages
            auto it =
                std::find_if(jsonLeakages.begin(), jsonLeakages.end(),
                             [&](const LeakagePower &lp) { return leakageEquals(lp, existing); });
            if (it != jsonLeakages.end()) {
                // Update if found
                updateLeakagePower(oneGroup, *it, err);
            }
        }
    }
    si2drIterQuit(subGrps, err);
}

/**
 * @brief Update cells/pins within the given top-level group (library) according to JSON data
 */
static void updateLibertyFile(si2drGroupIdT libraryGroup, std::vector<CellInfo> &cells,
                              const PVT &pvt, si2drErrorT *err) {
    // Traverse cells
    si2drGroupsIdT groups = si2drGroupGetGroups(libraryGroup, err);
    si2drGroupIdT cellGroup;

    while (!si2drObjectIsNull((cellGroup = si2drIterNextGroup(groups, err)), err)) {
        si2drStringT groupType = si2drGroupGetGroupType(cellGroup, err);
        if (strcmp(groupType, "cell") == 0) {
            // Get cell name
            si2drNamesIdT names = si2drGroupGetNames(cellGroup, err);
            si2drStringT cName = si2drIterNextName(names, err);
            si2drIterQuit(names, err);

            if (!cName)
                continue;
            std::string cellNameStr = cName;

            // Match in JSON cells
            auto cellIt = std::find_if(cells.begin(), cells.end(), [&](const CellInfo &c) {
                return (c.cellName == cellNameStr);
            });
            if (cellIt == cells.end()) {
                // Not found in JSON, skip
                continue;
            }

            CellInfo &jsonCell = *cellIt;
            updateLeakages(cellIt->leakages, cellGroup, err);
            // Traverse pins
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
                    si2drNamesIdT pnames = si2drGroupGetNames(pinGroup, err);
                    si2drStringT pName = si2drIterNextName(pnames, err);
                    si2drIterQuit(pnames, err);
                    if (!pName)
                        continue;

                    std::string pinNameStr = pName;

                    if (dirVal && std::string(dirVal) == "input") {
                        // Find in jsonCell.inputPins
                        auto pinIt = std::find_if(
                            jsonCell.inputPins.begin(), jsonCell.inputPins.end(),
                            [&](const inputPinInfo &pin) { return (pin.pinName == pinNameStr); });
                        if (pinIt != jsonCell.inputPins.end()) {
                            // Update capacitance
                            updateInputCapacitance(*pinIt, pinGroup, err);
                            // Update timing
                            updateTimingArcs(pinIt->timingArcs, pinGroup, err);
                            // Update power
                            updatePowerArcs(pinIt->powerArcs, pinGroup, err);
                        }
                    } else if (dirVal && std::string(dirVal) == "output") {
                        // Find in jsonCell.outputPins
                        auto pinIt = std::find_if(
                            jsonCell.outputPins.begin(), jsonCell.outputPins.end(),
                            [&](const outputPinInfo &pin) { return (pin.pinName == pinNameStr); });
                        if (pinIt != jsonCell.outputPins.end()) {
                            // Update timing
                            updateTimingArcs(pinIt->timingArcs, pinGroup, err);
                            // Update power
                            updatePowerArcs(pinIt->powerArcs, pinGroup, err);
                        }
                    }
                }
            }
            si2drIterQuit(cellSubgroups, err);
        }
    }
    si2drIterQuit(groups, err);
}

/**
 * @brief Load data from JSON file into vector<CellInfo> and PVT
 */
static bool loadJsonToCells(const std::string &fileName, std::vector<CellInfo> &cells, PVT &pvt) {
    std::ifstream fin(fileName);
    if (!fin.is_open()) {
        std::cerr << "Cannot open JSON file: " << fileName << std::endl;
        return false;
    }

    json j;
    try {
        fin >> j;
    } catch (const json::parse_error &e) {
        std::cerr << "JSON parse error: " << e.what() << std::endl;
        return false;
    }

    // Parse pvt
    if (j.contains("voltage")) {
        pvt.voltage = j["voltage"].get<double>();
    }
    if (j.contains("temperature")) {
        pvt.temperature = j["temperature"].get<long>();
    }
    if (j.contains("process")) {
        pvt.process = j["process"].get<std::vector<int>>();
    }

    // Parse cells
    if (j.contains("cells")) {
        for (auto &cellJson : j["cells"]) {
            CellInfo cell;
            cell.cellName = cellJson.value("cell_name", "");

            // output_pins
            if (cellJson.contains("output_pins")) {
                for (auto &pinJson : cellJson["output_pins"]) {
                    outputPinInfo pin;
                    pin.pinName = pinJson.value("pin_name", "");
                    pin.function = pinJson.value("function", "");

                    // timing_arcs
                    if (pinJson.contains("timing_arcs")) {
                        for (auto &arcJson : pinJson["timing_arcs"]) {
                            TimingArc arc;
                            arc.when = arcJson.value("when", "");
                            arc.relatedPin = arcJson.value("related_pin", "");
                            arc.timingType = arcJson.value("timing_type", "");
                            arc.timingSense = arcJson.value("timing_sense", "");

                            if (arcJson.contains("cell_rise")) {
                                auto &cr = arcJson["cell_rise"];
                                if (cr.contains("index1")) {
                                    arc.cellRise.index1 = cr["index1"].get<std::vector<double>>();
                                }
                                if (cr.contains("index2")) {
                                    arc.cellRise.index2 = cr["index2"].get<std::vector<double>>();
                                }
                                if (cr.contains("values")) {
                                    arc.cellRise.values =
                                        cr["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("rise_transition")) {
                                auto &rt = arcJson["rise_transition"];
                                if (rt.contains("index1")) {
                                    arc.riseTransition.index1 =
                                        rt["index1"].get<std::vector<double>>();
                                }
                                if (rt.contains("index2")) {
                                    arc.riseTransition.index2 =
                                        rt["index2"].get<std::vector<double>>();
                                }
                                if (rt.contains("values")) {
                                    arc.riseTransition.values =
                                        rt["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("cell_fall")) {
                                auto &cf = arcJson["cell_fall"];
                                if (cf.contains("index1")) {
                                    arc.cellFall.index1 = cf["index1"].get<std::vector<double>>();
                                }
                                if (cf.contains("index2")) {
                                    arc.cellFall.index2 = cf["index2"].get<std::vector<double>>();
                                }
                                if (cf.contains("values")) {
                                    arc.cellFall.values =
                                        cf["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("fall_transition")) {
                                auto &ft = arcJson["fall_transition"];
                                if (ft.contains("index1")) {
                                    arc.fallTransition.index1 =
                                        ft["index1"].get<std::vector<double>>();
                                }
                                if (ft.contains("index2")) {
                                    arc.fallTransition.index2 =
                                        ft["index2"].get<std::vector<double>>();
                                }
                                if (ft.contains("values")) {
                                    arc.fallTransition.values =
                                        ft["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("rise_constraint")) {
                                auto &rc = arcJson["rise_constraint"];
                                if (rc.contains("index1")) {
                                    arc.riseConstrain.index1 =
                                        rc["index1"].get<std::vector<double>>();
                                }
                                if (rc.contains("index2")) {
                                    arc.riseConstrain.index2 =
                                        rc["index2"].get<std::vector<double>>();
                                }
                                if (rc.contains("values")) {
                                    arc.riseConstrain.values =
                                        rc["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("fall_constraint")) {
                                auto &fc = arcJson["fall_constraint"];
                                if (fc.contains("index1")) {
                                    arc.fallConstrain.index1 =
                                        fc["index1"].get<std::vector<double>>();
                                }
                                if (fc.contains("index2")) {
                                    arc.fallConstrain.index2 =
                                        fc["index2"].get<std::vector<double>>();
                                }
                                if (fc.contains("values")) {
                                    arc.fallConstrain.values =
                                        fc["values"].get<std::vector<std::vector<double>>>();
                                }
                            }

                            pin.timingArcs.push_back(arc);
                        }
                    }

                    // power_arcs
                    if (pinJson.contains("power_arcs")) {
                        for (auto &arcJson : pinJson["power_arcs"]) {
                            PowerArc arc;
                            arc.when = arcJson.value("when", "");
                            arc.relatedPin = arcJson.value("related_pin", "");
                            arc.relatedPGpin = arcJson.value("related_pg_pin", "");

                            if (arcJson.contains("cell_rise")) {
                                auto &cr = arcJson["cell_rise"];
                                if (cr.contains("index1")) {
                                    arc.cellRise.index1 = cr["index1"].get<std::vector<double>>();
                                }
                                if (cr.contains("index2")) {
                                    arc.cellRise.index2 = cr["index2"].get<std::vector<double>>();
                                }
                                if (cr.contains("values")) {
                                    arc.cellRise.values =
                                        cr["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("cell_fall")) {
                                auto &cf = arcJson["cell_fall"];
                                if (cf.contains("index1")) {
                                    arc.cellFall.index1 = cf["index1"].get<std::vector<double>>();
                                }
                                if (cf.contains("index2")) {
                                    arc.cellFall.index2 = cf["index2"].get<std::vector<double>>();
                                }
                                if (cf.contains("values")) {
                                    arc.cellFall.values =
                                        cf["values"].get<std::vector<std::vector<double>>>();
                                }
                            }

                            pin.powerArcs.push_back(arc);
                        }
                    }

                    cell.outputPins.push_back(pin);
                }
            }

            // input_pins
            if (cellJson.contains("input_pins")) {
                for (auto &pinJson : cellJson["input_pins"]) {
                    inputPinInfo pin;
                    pin.pinName = pinJson.value("pin_name", "");

                    if (pinJson.contains("capacitance")) {
                        pin.capacitance = pinJson["capacitance"].get<double>();
                    }
                    if (pinJson.contains("rise_capacitance")) {
                        pin.rise_capacitance = pinJson["rise_capacitance"].get<double>();
                    }
                    if (pinJson.contains("fall_capacitance")) {
                        pin.fall_capacitance = pinJson["fall_capacitance"].get<double>();
                    }

                    if (pinJson.contains("rise_capacitance_range")) {
                        auto arr = pinJson["rise_capacitance_range"];
                        if (arr.is_array() && arr.size() == 2) {
                            pin.rise_capacitance_range = {arr[0].get<double>(),
                                                          arr[1].get<double>()};
                        }
                    }
                    if (pinJson.contains("fall_capacitance_range")) {
                        auto arr = pinJson["fall_capacitance_range"];
                        if (arr.is_array() && arr.size() == 2) {
                            pin.fall_capacitance_range = {arr[0].get<double>(),
                                                          arr[1].get<double>()};
                        }
                    }

                    // timing_arcs
                    if (pinJson.contains("timing_arcs")) {
                        for (auto &arcJson : pinJson["timing_arcs"]) {
                            TimingArc arc;
                            arc.when = arcJson.value("when", "");
                            arc.relatedPin = arcJson.value("related_pin", "");
                            arc.timingType = arcJson.value("timing_type", "");
                            arc.timingSense = arcJson.value("timing_sense", "");

                            // cell_rise
                            if (arcJson.contains("cell_rise")) {
                                auto &cr = arcJson["cell_rise"];
                                if (cr.contains("index1")) {
                                    arc.cellRise.index1 = cr["index1"].get<std::vector<double>>();
                                }
                                if (cr.contains("index2")) {
                                    arc.cellRise.index2 = cr["index2"].get<std::vector<double>>();
                                }
                                if (cr.contains("values")) {
                                    arc.cellRise.values =
                                        cr["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            // rise_transition
                            if (arcJson.contains("rise_transition")) {
                                auto &rt = arcJson["rise_transition"];
                                if (rt.contains("index1")) {
                                    arc.riseTransition.index1 =
                                        rt["index1"].get<std::vector<double>>();
                                }
                                if (rt.contains("index2")) {
                                    arc.riseTransition.index2 =
                                        rt["index2"].get<std::vector<double>>();
                                }
                                if (rt.contains("values")) {
                                    arc.riseTransition.values =
                                        rt["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            // cell_fall
                            if (arcJson.contains("cell_fall")) {
                                auto &cf = arcJson["cell_fall"];
                                if (cf.contains("index1")) {
                                    arc.cellFall.index1 = cf["index1"].get<std::vector<double>>();
                                }
                                if (cf.contains("index2")) {
                                    arc.cellFall.index2 = cf["index2"].get<std::vector<double>>();
                                }
                                if (cf.contains("values")) {
                                    arc.cellFall.values =
                                        cf["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            // fall_transition
                            if (arcJson.contains("fall_transition")) {
                                auto &ft = arcJson["fall_transition"];
                                if (ft.contains("index1")) {
                                    arc.fallTransition.index1 =
                                        ft["index1"].get<std::vector<double>>();
                                }
                                if (ft.contains("index2")) {
                                    arc.fallTransition.index2 =
                                        ft["index2"].get<std::vector<double>>();
                                }
                                if (ft.contains("values")) {
                                    arc.fallTransition.values =
                                        ft["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            // rise_constraint
                            if (arcJson.contains("rise_constraint")) {
                                auto &rc = arcJson["rise_constraint"];
                                if (rc.contains("index1")) {
                                    arc.riseConstrain.index1 =
                                        rc["index1"].get<std::vector<double>>();
                                }
                                if (rc.contains("index2")) {
                                    arc.riseConstrain.index2 =
                                        rc["index2"].get<std::vector<double>>();
                                }
                                if (rc.contains("values")) {
                                    arc.riseConstrain.values =
                                        rc["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            // fall_constraint
                            if (arcJson.contains("fall_constraint")) {
                                auto &fc = arcJson["fall_constraint"];
                                if (fc.contains("index1")) {
                                    arc.fallConstrain.index1 =
                                        fc["index1"].get<std::vector<double>>();
                                }
                                if (fc.contains("index2")) {
                                    arc.fallConstrain.index2 =
                                        fc["index2"].get<std::vector<double>>();
                                }
                                if (fc.contains("values")) {
                                    arc.fallConstrain.values =
                                        fc["values"].get<std::vector<std::vector<double>>>();
                                }
                            }

                            pin.timingArcs.push_back(arc);
                        }
                    }

                    // power_arcs
                    if (pinJson.contains("power_arcs")) {
                        for (auto &arcJson : pinJson["power_arcs"]) {
                            PowerArc arc;
                            arc.when = arcJson.value("when", "");
                            arc.relatedPin = arcJson.value("related_pin", "");
                            arc.relatedPGpin = arcJson.value("related_pg_pin", "");

                            if (arcJson.contains("cell_rise")) {
                                auto &cr = arcJson["cell_rise"];
                                if (cr.contains("index1")) {
                                    arc.cellRise.index1 = cr["index1"].get<std::vector<double>>();
                                }
                                if (cr.contains("index2")) {
                                    arc.cellRise.index2 = cr["index2"].get<std::vector<double>>();
                                }
                                if (cr.contains("values")) {
                                    arc.cellRise.values =
                                        cr["values"].get<std::vector<std::vector<double>>>();
                                }
                            }
                            if (arcJson.contains("cell_fall")) {
                                auto &cf = arcJson["cell_fall"];
                                if (cf.contains("index1")) {
                                    arc.cellFall.index1 = cf["index1"].get<std::vector<double>>();
                                }
                                if (cf.contains("index2")) {
                                    arc.cellFall.index2 = cf["index2"].get<std::vector<double>>();
                                }
                                if (cf.contains("values")) {
                                    arc.cellFall.values =
                                        cf["values"].get<std::vector<std::vector<double>>>();
                                }
                            }

                            pin.powerArcs.push_back(arc);
                        }
                    }

                    cell.inputPins.push_back(pin);
                }
            }
            // leakage
            if (cellJson.contains("leakage_power")) {
                for (auto &lkJson : cellJson["leakage_power"]) {
                    LeakagePower lp;
                    lp.value = lkJson.value("value", 0.0);
                    lp.when = lkJson.value("when", "");
                    lp.relatedPGpin = lkJson.value("related_pg_pin", "");
                    cell.leakages.push_back(lp);
                }
            }
            cells.push_back(cell);
        }
    }

    return true;
}

bool modifyLibertyFile(const std::string &originalLibFile, const std::string &jsonFile,
                       const std::string &outputLibFile) {
    // 1) Load cells + pvt from JSON
    std::vector<CellInfo> cells;
    PVT pvt;
    if (!loadJsonToCells(jsonFile, cells, pvt)) {
        return false;
    }

    // 2) Read original Liberty file
    si2drErrorT err;
    si2drPIInit(&err);

    si2drReadLibertyFile(const_cast<char *>(originalLibFile.c_str()), &err);
    if (err != SI2DR_NO_ERROR) {
        std::cerr << "Error reading Liberty file: " << originalLibFile << std::endl;
        si2drPIQuit(&err);
        return false;
    }

    // 3) Traverse top-level group and update
    si2drGroupsIdT topGroups = si2drPIGetGroups(&err);
    si2drGroupIdT group;
    while (!si2drObjectIsNull((group = si2drIterNextGroup(topGroups, &err)), &err)) {
        updateLibertyFile(group, cells, pvt, &err);
    }
    si2drIterQuit(topGroups, &err);

    // 4) Write out
    //   If there are multiple top-level groups, you need to traverse and write multiple times; here only the first group is written
    topGroups = si2drPIGetGroups(&err);
    group = si2drIterNextGroup(topGroups, &err);
    if (!si2drObjectIsNull(group, &err)) {
        si2drWriteLibertyFile(const_cast<char *>(outputLibFile.c_str()), group, nullptr, &err);
    }
    si2drIterQuit(topGroups, &err);

    si2drPIQuit(&err);

    if (err != SI2DR_NO_ERROR) {
        std::cerr << "Error writing new Liberty file: " << outputLibFile << std::endl;
        return false;
    }

    return true;
}
