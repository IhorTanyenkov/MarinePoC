#include "nbot_lite/JsonUtil.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace nbot_lite {

Json read_json_file(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("Cannot open JSON file: " + path);
    }
    return Json::parse(in, nullptr, true, true);
}

double json_to_number(const Json& value) {
    if (value.is_number()) {
        return value.get<double>();
    }
    if (value.is_string()) {
        return std::stod(value.get<std::string>());
    }
    throw std::runtime_error("Expected numeric value, got " + value.dump());
}

double round_currency(double value) {
    return std::round(value * 100.0) / 100.0;
}

std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

const Json* find_path(const Json& root, const std::string& dotted_path) {
    const Json* cur = &root;
    std::stringstream ss(dotted_path);
    std::string part;
    while (std::getline(ss, part, '.')) {
        if (!cur->is_object() || !cur->contains(part)) {
            return nullptr;
        }
        cur = &(*cur)[part];
    }
    return cur;
}

}
