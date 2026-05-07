#pragma once

#include "nbot_lite/JsonUtil.hpp"

#include <string>
#include <vector>

namespace nbot_lite {

/**
 * Applies rule-pack applicability conditions to vessel and operation facts.
 */
class RuleMatcher {
public:
    bool matches(const Json& rule, const Json& facts, std::vector<std::string>& skipped_conditions) const;

private:
    bool condition_matches(const Json& condition, const Json& facts) const;
    bool compare_number(const Json& actual, const std::string& op, double expected) const;
};

}
