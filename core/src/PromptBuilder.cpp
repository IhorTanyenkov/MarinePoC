#include "nbot_lite/PromptBuilder.hpp"

#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace nbot_lite {

namespace {

std::string mode_of(const Json& params) {
    if (!params.contains("mode") || !params["mode"].is_string()) {
        throw std::runtime_error("PromptBuilder: missing mode");
    }
    return params["mode"].get<std::string>();
}

std::string load_template(const Json& params) {
    if (!params.contains("template_path") || !params["template_path"].is_string()) {
        throw std::runtime_error("PromptBuilder: missing template_path");
    }
    return read_text_file(params["template_path"].get<std::string>());
}

std::string json_dump(const Json& value) {
    return value.dump();
}

std::string format_pages_excerpt(const Json& pages) {
    if (!pages.is_array() || pages.empty()) {
        return "(none provided)";
    }
    std::ostringstream out;
    std::size_t emitted = 0;
    for (const auto& page : pages) {
        if (emitted >= 8) break;
        const auto page_no = page.value("page", 0);
        std::string text = page.value("text", std::string{});
        if (text.size() > 2400) text.resize(2400);
        if (emitted) out << "\n\n";
        out << "--- PAGE " << page_no << " ---\n" << text;
        ++emitted;
    }
    return out.str();
}

Json build_extract_text(const std::string& tmpl, const Json& params) {
    const std::string filename = params.value("filename", "upload");
    const Json& candidates = params.contains("candidates") ? params["candidates"] : Json::array();
    const std::string page_text = params.value("page_text", std::string{});

    std::ostringstream out;
    out << tmpl
        << "\n\nReturn JSON only. Do not wrap in markdown. The JSON must match port_tariff.rule_pack.v1.\n\n"
        << "UPLOAD_FILENAME: " << filename << "\n"
        << "CANDIDATE_TERMS: " << json_dump(candidates) << "\n\n"
        << "EXTRACTED_PAGE_TEXT:\n" << page_text;
    return Json{{"prompt_text", out.str()}, {"mode", "extract_text"}};
}

Json build_extract_pdf(const std::string& tmpl, const Json& params) {
    const std::string filename = params.value("filename", "upload");
    const Json& candidates = params.contains("candidates") ? params["candidates"] : Json::array();

    std::ostringstream out;
    out << tmpl
        << "\n\nThe attached document is a port tariff PDF. Read every page, including the rate tables.\n"
        << "Return JSON only. Do not wrap in markdown. The JSON must match port_tariff.rule_pack.v1.\n"
        << "Every numeric constant in a `formula` MUST appear verbatim in the document and be cited in `evidence` with a page number and short quote.\n"
        << "If a charge applies only to specific ports, vessel types, services, or cargo, encode that as `applicability` conditions on `operational_data.*` or `technical_specs.*` paths.\n"
        << "Do not invent rates. If a rate is missing or ambiguous, surface it in `open_questions` rather than guessing.\n\n"
        << "UPLOAD_FILENAME: " << filename << "\n"
        << "CANDIDATE_TERMS: " << json_dump(candidates);
    return Json{{"prompt_text", out.str()}, {"mode", "extract_pdf"}};
}

Json build_refine(const std::string& tmpl, const Json& params) {
    if (!params.contains("original_pack")) {
        throw std::runtime_error("PromptBuilder.refine: missing original_pack");
    }
    if (!params.contains("diffs")) {
        throw std::runtime_error("PromptBuilder.refine: missing diffs");
    }
    std::ostringstream out;
    out << tmpl
        << "\n\nREFINEMENT TASK\n"
        << "===============\n"
        << "You produced this rule pack from the attached tariff document, but its self_tests\n"
        << "do not match expected totals. Identify the missing or wrong rules, fix them, and\n"
        << "return the COMPLETE corrected port_tariff.rule_pack.v1 JSON. Do not return diffs.\n"
        << "Do not skip rules that were correct - keep them as-is. Add missing rules (especially\n"
        << "derived discounts like efficiency caps written as `multiply(const -1, max(const 0, subtract(cargo_subtotal, cap_amount)))`).\n"
        << "Make sure slugs (service_type, vessel_type_*, cargo_type_*) used in vessel rules,\n"
        << "cargo rules, and self_tests are IDENTICAL strings.\n"
        << "Return JSON only. Do not wrap in markdown.\n\n"
        << "FAILING SELF-TESTS WITH DIFFS:\n" << params["diffs"].dump(2) << "\n\n"
        << "ORIGINAL RULE PACK:\n" << params["original_pack"].dump(2);
    return Json{{"prompt_text", out.str()}, {"mode", "refine"}};
}

Json build_research(const std::string& tmpl, const Json& params) {
    const std::string query = params.value("query", std::string{});
    const Json vessel = params.contains("vessel") ? params["vessel"] : Json::object();
    const Json hints = params.contains("rule_pack_hints") ? params["rule_pack_hints"] : Json::object();
    const Json pages = params.contains("pages") ? params["pages"] : Json::array();

    std::ostringstream out;
    out << tmpl
        << "\n\nReturn JSON only. Do not wrap in markdown. The JSON must match port_tariff.research_result.v1.\n"
        << "If the answer can be found in the document pages provided below, prefer cite-from-document over external claims and set `source_type: \"document\"` with the page number.\n"
        << "Be concise. Findings should be at most 5 entries.\n\n"
        << "QUESTION: " << query << "\n\n"
        << "VESSEL_CONTEXT: " << json_dump(vessel) << "\n\n"
        << "RULE_PACK_HINTS: " << json_dump(hints) << "\n\n"
        << "DOCUMENT_PAGES:\n" << format_pages_excerpt(pages);
    return Json{{"prompt_text", out.str()}, {"mode", "research"}};
}

}

Json PromptBuilder::build(const Json& params) const {
    const std::string mode = mode_of(params);
    const std::string tmpl = load_template(params);
    if (mode == "extract_text") return build_extract_text(tmpl, params);
    if (mode == "extract_pdf") return build_extract_pdf(tmpl, params);
    if (mode == "refine") return build_refine(tmpl, params);
    if (mode == "research") return build_research(tmpl, params);
    throw std::runtime_error("PromptBuilder: unknown mode " + mode);
}

}
