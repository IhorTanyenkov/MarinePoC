#pragma once

#include <nlohmann/json.hpp>

#include <string>

namespace nbot_lite {

using Json = nlohmann::json;

/**
 * Shared JSON helpers for the nbot_lite core boundary.
 */
Json read_json_file(const std::string& path);
std::string read_text_file(const std::string& path);
double json_to_number(const Json& value);
double round_currency(double value);
std::string lower_copy(std::string value);
const Json* find_path(const Json& root, const std::string& dotted_path);

}
