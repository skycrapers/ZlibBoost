#pragma once

#include <string>

/**
 * @brief Apply updates from JSON file to original Liberty file and output to new file
 * 
 * @param originalLibFile Path to original .lib file
 * @param jsonFile Path to JSON file containing updates
 * @param outputLibFile Path for generated .lib file
 * @return true if successful, false on error
 */
bool modifyLibertyFile(const std::string &originalLibFile,
                       const std::string &jsonFile,
                       const std::string &outputLibFile);
