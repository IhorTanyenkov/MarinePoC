#include "nbot_lite/TariffEngine.hpp"

#include <exception>
#include <string>
#include <vector>

namespace nbot_lite {

Json TariffEngine::calculate(const Json& rule_pack, const Json& facts) const {
    Json results = Json::array();
    Json skipped = Json::array();
    double total = 0.0;

    for (const auto& rule : rule_pack.value("rules", Json::array())) {
        try {
            std::vector<std::string> skipped_conditions;
            if (!matcher_.matches(rule, facts, skipped_conditions)) {
                skipped.push_back({
                    {"rule_id", rule.value("id", "")},
                    {"charge_name", rule.value("charge_name", "")},
                    {"reason", skipped_conditions.empty() ? "not_applicable" : skipped_conditions.front()}
                });
                continue;
            }

            const double raw = formulas_.evaluate(rule.at("formula"), facts);
            const double amount = round_currency(raw);
            const Json notes = rule.contains("notes") && rule.at("notes").is_string() ? rule.at("notes") : Json("");
            total += amount;
            results.push_back({
                {"rule_id", rule.value("id", "")},
                {"charge_name", rule.value("charge_name", "")},
                {"category", rule.value("category", "")},
                {"amount", amount},
                {"currency", rule_pack.value("document", Json::object()).value("currency", "UNKNOWN")},
                {"confidence", rule.value("confidence", 0.0)},
                {"formula", rule.value("formula", Json::object())},
                {"evidence", rule.value("evidence", Json::array())},
                {"notes", notes}
            });
        } catch (const std::exception& ex) {
            results.push_back({
                {"rule_id", rule.value("id", "")},
                {"charge_name", rule.value("charge_name", "")},
                {"error", ex.what()},
                {"confidence", 0.0}
            });
        }
    }

    return {
        {"schema_version", "port_tariff.calculation_result.v1"},
        {"document", rule_pack.value("document", Json::object())},
        {"total", round_currency(total)},
        {"results", results},
        {"skipped_rules", skipped},
        {"graph", graph_.build(rule_pack)}
    };
}

}
