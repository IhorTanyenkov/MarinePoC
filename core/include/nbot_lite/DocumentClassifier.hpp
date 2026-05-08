#pragma once

#include "JsonUtil.hpp"

namespace nbot_lite {

/**
 * Lightweight deterministic classifier for uploaded tariff documents.
 *
 * Scores the page text against term lists for port-authority schedules,
 * forwarder/agent local-charges sheets, regulatory/legislative text, and
 * cargo-only contracts. Returns the most likely document_type, raw signal
 * counts, and a confidence score so the agent layer can decide whether to
 * run extraction at all and the UI can warn the user about misuse.
 *
 * Runs entirely in C++: no model calls, no network, no language detection
 * beyond English keywords. Suitable for a fast pre-flight check before any
 * paid LLM round trip.
 */
class DocumentClassifier {
public:
    /**
     * Classify the document represented by an array of {page, text} entries.
     *
     * Returns:
     *   {
     *     "document_type": "port_authority_tariff" | "forwarder_or_agent_fees"
     *                    | "regulatory_text" | "cargo_contract" | "unknown",
     *     "confidence": 0.0..1.0,
     *     "signals": {
     *       "port_authority": int, "forwarder": int,
     *       "regulatory": int, "cargo_contract": int
     *     },
     *     "reason": "short human readable explanation"
     *   }
     */
    Json classify(const Json& pages) const;
};

}
