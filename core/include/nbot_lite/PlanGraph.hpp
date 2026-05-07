#pragma once

#include "nbot_lite/JsonUtil.hpp"

namespace nbot_lite {

/**
 * Builds the graph trace shape consumed by FastAPI and React.
 */
class PlanGraph {
public:
    Json build(const Json& rule_pack) const;
};

}
