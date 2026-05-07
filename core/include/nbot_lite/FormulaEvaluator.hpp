#pragma once

#include "nbot_lite/JsonUtil.hpp"

namespace nbot_lite {

/**
 * Deterministic evaluator for the portable tariff formula DSL.
 */
class FormulaEvaluator {
public:
    double evaluate(const Json& expression, const Json& facts) const;

private:
    double evaluate_arg(const Json& args, std::size_t index, const Json& facts) const;
};

}
