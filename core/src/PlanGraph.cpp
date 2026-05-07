#include "nbot_lite/PlanGraph.hpp"

namespace nbot_lite {

Json PlanGraph::build(const Json& rule_pack) const {
    Json nodes = Json::array({
        {{"id", "upload"}, {"label", "Upload tariff document or rule pack"}, {"kind", "input"}, {"certain", true}},
        {{"id", "extract"}, {"label", "Extract tariff sections and candidate rules"}, {"kind", "tool"}, {"certain", false}},
        {{"id", "research"}, {"label", "Research unclear terms or missing context"}, {"kind", "research"}, {"certain", false}},
        {{"id", "normalize"}, {"label", "Normalize rules into portable formula DSL"}, {"kind", "agent"}, {"certain", true}},
        {{"id", "match"}, {"label", "Match vessel facts against applicability conditions"}, {"kind", "core"}, {"certain", true}},
        {{"id", "evaluate"}, {"label", "Evaluate formulas in nbot_lite C++ core"}, {"kind", "core"}, {"certain", true}},
        {{"id", "explain"}, {"label", "Return totals with evidence and confidence"}, {"kind", "output"}, {"certain", true}}
    });

    Json edges = Json::array({
        {{"from", "upload"}, {"to", "extract"}},
        {{"from", "extract"}, {"to", "research"}},
        {{"from", "extract"}, {"to", "normalize"}},
        {{"from", "research"}, {"to", "normalize"}},
        {{"from", "normalize"}, {"to", "match"}},
        {{"from", "match"}, {"to", "evaluate"}},
        {{"from", "evaluate"}, {"to", "explain"}}
    });

    Json rule_nodes = Json::array();
    for (const auto& rule : rule_pack.value("rules", Json::array())) {
        rule_nodes.push_back({
            {"id", rule.value("id", "unknown")},
            {"label", rule.value("charge_name", "Unnamed charge")},
            {"confidence", rule.value("confidence", 0.0)},
            {"category", rule.value("category", "unknown")}
        });
    }

    return {
        {"nodes", nodes},
        {"edges", edges},
        {"rules", rule_nodes}
    };
}

}
