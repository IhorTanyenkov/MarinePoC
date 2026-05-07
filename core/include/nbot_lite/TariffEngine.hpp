#pragma once

#include "nbot_lite/FormulaEvaluator.hpp"
#include "nbot_lite/PlanGraph.hpp"
#include "nbot_lite/RuleMatcher.hpp"

namespace nbot_lite {

/**
 * Coordinates rule matching, deterministic formula evaluation, and trace output.
 */
class TariffEngine {
public:
    Json calculate(const Json& rule_pack, const Json& facts) const;

private:
    FormulaEvaluator formulas_;
    RuleMatcher matcher_;
    PlanGraph graph_;
};

}
