#include "nbot_lite/RuleMatcher.hpp"

#include <stdexcept>

namespace nbot_lite {

bool RuleMatcher::compare_number(const Json& actual, const std::string& op, double expected) const {
    const double lhs = json_to_number(actual);
    if (op == ">") return lhs > expected;
    if (op == ">=") return lhs >= expected;
    if (op == "<") return lhs < expected;
    if (op == "<=") return lhs <= expected;
    if (op == "==" || op == "eq") return lhs == expected;
    return false;
}

bool RuleMatcher::condition_matches(const Json& condition, const Json& facts) const {
    const std::string field = condition.value("field", "");
    const std::string op = condition.value("op", "");
    const auto* actual = find_path(facts, field);
    if (op == "exists") {
        return actual != nullptr && !actual->is_null();
    }
    if (!actual || actual->is_null()) {
        return false;
    }
    if (op == "eq_ci") {
        return actual->is_string() &&
               lower_copy(actual->get<std::string>()) == lower_copy(condition.at("value").get<std::string>());
    }
    if (op == "in_ci") {
        if (!actual->is_string() || !condition.at("value").is_array()) return false;
        const auto lhs = lower_copy(actual->get<std::string>());
        for (const auto& option : condition.at("value")) {
            if (option.is_string() && lhs == lower_copy(option.get<std::string>())) {
                return true;
            }
        }
        return false;
    }
    if (op == ">" || op == ">=" || op == "<" || op == "<=" || op == "==" || op == "eq") {
        return compare_number(*actual, op, json_to_number(condition.at("value")));
    }
    throw std::runtime_error("Unsupported condition op: " + op);
}

bool RuleMatcher::matches(const Json& rule,
                          const Json& facts,
                          std::vector<std::string>& skipped_conditions) const {
    if (!rule.contains("applicability")) {
        return true;
    }
    for (const auto& condition : rule.at("applicability")) {
        if (!condition_matches(condition, facts)) {
            skipped_conditions.push_back(condition.dump());
            return false;
        }
    }
    return true;
}

}
