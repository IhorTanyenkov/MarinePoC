#include "nbot_lite/FormulaEvaluator.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace nbot_lite {

double FormulaEvaluator::evaluate_arg(const Json& args, std::size_t index, const Json& facts) const {
    if (!args.is_array() || index >= args.size()) {
        throw std::runtime_error("Formula argument missing at index " + std::to_string(index));
    }
    return evaluate(args.at(index), facts);
}

double FormulaEvaluator::evaluate(const Json& expression, const Json& facts) const {
    if (expression.is_number()) {
        return expression.get<double>();
    }
    if (!expression.is_object()) {
        throw std::runtime_error("Formula expression must be object or number: " + expression.dump());
    }
    if (expression.contains("const")) {
        return json_to_number(expression.at("const"));
    }
    if (expression.contains("var")) {
        const auto* value = find_path(facts, expression.at("var").get<std::string>());
        if (!value || value->is_null()) {
            throw std::runtime_error("Missing formula variable: " + expression.at("var").get<std::string>());
        }
        return json_to_number(*value);
    }

    const std::string op = expression.value("op", "");
    const Json& args = expression.contains("args") ? expression.at("args") : Json::array();

    if (op == "add") {
        double total = 0.0;
        for (const auto& arg : args) {
            total += evaluate(arg, facts);
        }
        return total;
    }
    if (op == "subtract") {
        return evaluate_arg(args, 0, facts) - evaluate_arg(args, 1, facts);
    }
    if (op == "multiply") {
        double total = 1.0;
        for (const auto& arg : args) {
            total *= evaluate(arg, facts);
        }
        return total;
    }
    if (op == "divide") {
        const double denom = evaluate_arg(args, 1, facts);
        if (denom == 0.0) {
            throw std::runtime_error("Division by zero");
        }
        return evaluate_arg(args, 0, facts) / denom;
    }
    if (op == "ceil_div") {
        const double denom = evaluate_arg(args, 1, facts);
        if (denom == 0.0) {
            throw std::runtime_error("ceil_div denominator is zero");
        }
        return std::ceil(evaluate_arg(args, 0, facts) / denom);
    }
    if (op == "max") {
        if (!args.is_array() || args.empty()) {
            throw std::runtime_error("max requires at least one argument");
        }
        double best = evaluate(args.at(0), facts);
        for (std::size_t i = 1; i < args.size(); ++i) {
            best = std::max(best, evaluate(args.at(i), facts));
        }
        return best;
    }
    if (op == "min") {
        if (!args.is_array() || args.empty()) {
            throw std::runtime_error("min requires at least one argument");
        }
        double best = evaluate(args.at(0), facts);
        for (std::size_t i = 1; i < args.size(); ++i) {
            best = std::min(best, evaluate(args.at(i), facts));
        }
        return best;
    }
    if (op == "coalesce") {
        for (const auto& arg : args) {
            try {
                return evaluate(arg, facts);
            } catch (const std::exception&) {
                continue;
            }
        }
        throw std::runtime_error("coalesce found no usable argument");
    }

    throw std::runtime_error("Unsupported formula op: " + op);
}

}
