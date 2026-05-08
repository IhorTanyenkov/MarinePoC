#pragma once

#include "JsonUtil.hpp"

#include <string>

namespace nbot_lite {

/**
 * Assembles the user-facing prompt text for the LLM extraction / refinement /
 * research agents from a system-prompt template plus run-time parameters.
 *
 * Python is a transport: it loads PDF bytes, talks to the provider HTTPs,
 * and parses JSON. The wording of every prompt that goes to a model is
 * owned here so the canonical prompt source is the deterministic core.
 */
class PromptBuilder {
public:
    /**
     * Build the prompt text for one of the supported template modes.
     *
     * Required params keys:
     *   mode: one of "extract_text", "extract_pdf", "refine", "research"
     *   template_path: filesystem path to the system prompt .md
     *
     * Mode-specific params:
     *   extract_text:  filename, candidates (array), page_text (string)
     *   extract_pdf:   filename, candidates (array)
     *   refine:        original_pack (object), diffs (array)
     *   research:      query (string), pages (array), vessel (object), rule_pack_hints (object)
     *
     * Returns: { "prompt_text": "...", "mode": "..." }
     */
    Json build(const Json& params) const;
};

}
