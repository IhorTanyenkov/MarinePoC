#include "nbot_lite/CoreCli.hpp"

#include "nbot_lite/JsonUtil.hpp"
#include "nbot_lite/PlanGraph.hpp"
#include "nbot_lite/TariffEngine.hpp"

#include <exception>
#include <filesystem>
#include <iostream>
#include <string>

namespace nbot_lite {
namespace {

struct AppState {
    Json rule_pack;
    Json fixture;
    Json providers;
    std::string rule_path;
    std::string fixture_path;
    std::string provider_path;
};

std::string arg_value(int argc, char** argv, const std::string& key, const std::string& fallback) {
    for (int i = 1; i + 1 < argc; ++i) {
        if (argv[i] == key) {
            return argv[i + 1];
        }
    }
    return fallback;
}

std::string default_path(char** argv, const std::string& relative) {
    namespace fs = std::filesystem;
    const fs::path cwd_path = fs::current_path() / relative;
    if (fs::exists(cwd_path)) {
        return cwd_path.string();
    }
    const fs::path exe_path = fs::absolute(argv[0]).parent_path();
    const fs::path repo_path = exe_path.parent_path() / relative;
    return repo_path.string();
}

Json validate_rule_pack(const Json& pack) {
    const bool ok = pack.value("schema_version", "") == "port_tariff.rule_pack.v1" &&
                    pack.contains("rules") && pack.at("rules").is_array() &&
                    !pack.at("rules").empty();
    return {
        {"ok", ok},
        {"rule_count", pack.contains("rules") && pack.at("rules").is_array() ? pack.at("rules").size() : 0},
        {"message", ok ? "Rule pack can be evaluated by the C++ core."
                        : "Expected port_tariff.rule_pack.v1 with a non-empty rules array."}
    };
}

}

int run_cli(int argc, char** argv) {
    try {
        AppState state;
        state.rule_path = arg_value(argc, argv, "--rules", default_path(argv, "poc/port_tariff_agent/data/empty_rule_pack.template.json"));
        state.fixture_path = arg_value(argc, argv, "--fixture", default_path(argv, "poc/port_tariff_agent/data/empty_vessel.template.json"));
        state.provider_path = arg_value(argc, argv, "--providers", default_path(argv, "poc/port_tariff_agent/data/model_providers.example.json"));
        const std::string mode = arg_value(argc, argv, "--mode", "calculate");
        const std::string input_path = arg_value(argc, argv, "--input", "");

        state.rule_pack = read_json_file(state.rule_path);
        state.fixture = read_json_file(state.fixture_path);
        state.providers = read_json_file(state.provider_path);

        if (mode == "health") {
            std::cout << Json{
                {"ok", true},
                {"service", "nbot_lite_port_tariff_core"},
                {"architecture", "standalone modular nbot_lite core"},
                {"rule_pack", state.rule_path},
                {"fixture", state.fixture_path},
                {"provider_config", state.provider_path}
            }.dump(2) << "\n";
            return 0;
        }

        if (mode == "rules") {
            std::cout << state.rule_pack.dump(2) << "\n";
            return 0;
        }

        if (mode == "models") {
            std::cout << state.providers.dump(2) << "\n";
            return 0;
        }

        if (mode == "plan") {
            std::cout << PlanGraph{}.build(state.rule_pack).dump(2) << "\n";
            return 0;
        }

        if (mode == "validate-rule-pack") {
            Json pack = input_path.empty() ? state.rule_pack : read_json_file(input_path);
            const Json result = validate_rule_pack(pack);
            std::cout << result.dump(2) << "\n";
            return result.value("ok", false) ? 0 : 2;
        }

        Json facts = state.fixture.value("vessel", Json::object());
        Json rules = state.rule_pack;
        if (!input_path.empty()) {
            const Json input = read_json_file(input_path);
            if (input.contains("vessel")) {
                facts = input.at("vessel");
            }
            if (input.contains("rule_pack")) {
                rules = input.at("rule_pack");
            }
        }

        std::cout << TariffEngine{}.calculate(rules, facts).dump(2) << "\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "port_tariff_core failed: " << ex.what() << "\n";
        return 1;
    }
}

}
