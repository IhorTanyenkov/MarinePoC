#include "nbot_lite/DocumentClassifier.hpp"

#include <algorithm>
#include <array>
#include <string>
#include <utility>
#include <vector>

namespace nbot_lite {

namespace {

struct CategoryTerms {
    const char* name;
    std::vector<const char*> terms;
};

/**
 * Term lists per document category. Each term is matched case-insensitively
 * against every page's text; counts accumulate across pages.
 *
 * IMPORTANT: these lists are deterministic classification heuristics. They are
 * NEVER sent to the LLM, never injected into prompts, never used to bias rule
 * extraction — they are only matched against the uploaded document's own text
 * to decide whether the document is a port-authority tariff, a forwarder fee
 * sheet, regulatory text, or a charter contract. The lists span multiple
 * regions on purpose so the classifier doesn't favour any one port's
 * vocabulary.
 */
const std::array<CategoryTerms, 4> CATEGORIES{
    CategoryTerms{
        "port_authority", {
            // Authority self-identification (multi-region)
            "port authority", "harbour authority", "harbor authority",
            "ports authority", "port master", "harbourmaster",
            "marine department", "maritime and port authority",
            // Document type identifiers
            "schedule of port dues", "schedule of charges", "schedule of tariffs",
            "tariff book", "port tariff", "scale of charges", "rate schedule",
            "port dues regulation",
            // Vessel-charge vocabulary across regions
            "port dues", "tonnage dues", "harbour dues", "harbor dues",
            "light dues", "buoy dues", "dolphin dues", "quay dues",
            "wharfage", "dockage", "anchorage dues", "berth dues",
            "channel fees", "navigation dues", "pilotage", "towage",
            "vessel traffic services", "vts", "lock fees",
            // Cargo-charge vocabulary
            "cargo dues", "wharfage charge", "tonnage cargo",
            // Discount and incentive vocabulary
            "esi", "environmental ship index", "green award certificate",
            "sustainability component", "scheduled service", "deepsea service",
            "shortsea", "feeder service", "shore power", "cold ironing",
            // Vessel attribute vocabulary
            "gross tonnage", "gt tariff", "net tonnage", "loa",
            "scale of dues", "per gt", "per nt",
            // Schedule structure markers
            "table 1", "table 2", "table 3", "annex 1", "annex 2", "appendix",
            "category 1", "category 2", "category 3",
            "price category",
        }
    },
    CategoryTerms{
        "forwarder", {
            "freight forwarder", "shipping agent", "agency fee", "agent fee",
            "bill of lading fee", "issuing bill of lading", "delivery order fee",
            "courier fee", "express release fee", "telex release",
            "manifest fee", "documentation fee", "local charges",
            "import / export related", "haulage", "trucking surcharge",
            "deconsolidation", "cfs charge", "carrier", "bunker adjustment factor",
            "currency adjustment factor", "isps surcharge", "war risk surcharge",
            "ams", "ens", "afr", "aci",
        }
    },
    CategoryTerms{
        "regulatory", {
            "act of parliament", "statutory instrument", "directive",
            "european commission", "eu regulation", "imo resolution",
            "marpol", "solas", "maritime law", "section ", "article ",
            "subsection", "whereas", "shall be deemed", "promulgated",
            "competent authority", "ministry of transport",
        }
    },
    CategoryTerms{
        "cargo_contract", {
            "charter party", "voyage charter", "time charter", "fixture",
            "demurrage", "laytime", "shex", "shinc",
            "notice of readiness", "hire rate", "off-hire",
            "redelivery", "charterers",
        }
    },
};

std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return s;
}

int count_substring(const std::string& haystack, const std::string& needle) {
    if (needle.empty()) return 0;
    int n = 0;
    std::size_t pos = 0;
    while ((pos = haystack.find(needle, pos)) != std::string::npos) {
        ++n;
        pos += needle.size();
    }
    return n;
}

}

Json DocumentClassifier::classify(const Json& pages) const {
    Json signals = Json::object();
    for (const auto& cat : CATEGORIES) signals[cat.name] = 0;

    if (!pages.is_array() || pages.empty()) {
        return Json{
            {"document_type", "unknown"},
            {"confidence", 0.0},
            {"signals", signals},
            {"reason", "No pages were provided to classify."},
        };
    }

    int total_chars = 0;
    for (const auto& page : pages) {
        const std::string text = lower(page.value("text", std::string{}));
        total_chars += static_cast<int>(text.size());
        for (const auto& cat : CATEGORIES) {
            int count = 0;
            for (const auto* term : cat.terms) {
                count += count_substring(text, term);
            }
            signals[cat.name] = signals[cat.name].get<int>() + count;
        }
    }

    int total_signals = 0;
    int max_count = 0;
    std::string winner = "unknown";
    for (const auto& cat : CATEGORIES) {
        int v = signals[cat.name].get<int>();
        total_signals += v;
        if (v > max_count) {
            max_count = v;
            winner = cat.name;
        }
    }

    double confidence = 0.0;
    std::string document_type = "unknown";
    std::string reason;

    if (total_signals == 0) {
        reason = "No vocabulary from any known document family was found. The PoC cannot tell what kind of document this is.";
    } else {
        confidence = static_cast<double>(max_count) / static_cast<double>(total_signals);
        if (winner == "port_authority") {
            document_type = "port_authority_tariff";
            reason = "Vocabulary matches a port authority tariff schedule. Extraction will produce port dues / cargo dues / sustainability rules.";
        } else if (winner == "forwarder") {
            document_type = "forwarder_or_agent_fees";
            reason = "Vocabulary matches a freight forwarder or shipping agent's local charges sheet. The PoC was designed for port authority tariffs; extracted rules will be forwarder fees, not vessel dues.";
        } else if (winner == "regulatory") {
            document_type = "regulatory_text";
            reason = "Vocabulary matches statutory or regulatory text rather than a tariff schedule. Few or no chargeable rules will be extracted.";
        } else if (winner == "cargo_contract") {
            document_type = "cargo_contract";
            reason = "Vocabulary matches a charter party / cargo contract rather than a port schedule.";
        }
    }

    if (total_chars < 800) {
        confidence = std::min(confidence, 0.35);
        reason += " Document is unusually short, so the classification is low-confidence.";
    }

    return Json{
        {"document_type", document_type},
        {"confidence", confidence},
        {"signals", signals},
        {"total_signals", total_signals},
        {"reason", reason},
    };
}

}
