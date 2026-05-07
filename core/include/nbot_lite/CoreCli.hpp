#pragma once

namespace nbot_lite {

/**
 * CLI boundary used by the FastAPI wrapper to invoke nbot_lite deterministically.
 */
int run_cli(int argc, char** argv);

}
