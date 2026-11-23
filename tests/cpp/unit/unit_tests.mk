# Makefile fragment: GoogleTest based unit tests for OpenUxAS C++.
#
# Included by the top level Makefile (after CXX, CXX_FLAGS and OBJECT_DIR are
# defined). Provides the 'test' target which builds all tests/cpp/unit/test_*.cpp
# into a single binary ($(OBJECT_DIR)/unit_tests) and runs it.
#
# GoogleTest acquisition (see tests/cpp/unit/README.md):
#   1. system packages (libgtest-dev: libgtest.a / libgtest_main.a), if the
#      compiler can link against them;
#   2. otherwise, build GoogleTest from source found in GTEST_SRC_DIR
#      (default: /usr/src/googletest/googletest, shipped by libgtest-dev
#      or googletest packages).

UNIT_TEST_SRC_DIR:=tests/cpp/unit
UNIT_TEST_DIR:=$(OBJECT_DIR)/unit
UNIT_TEST_BIN:=$(OBJECT_DIR)/unit_tests
UNIT_TEST_SOURCES:=$(wildcard $(UNIT_TEST_SRC_DIR)/test_*.cpp)
UNIT_TEST_OBJECTS:=$(patsubst $(UNIT_TEST_SRC_DIR)/%.cpp,$(UNIT_TEST_DIR)/%.o,$(UNIT_TEST_SOURCES))

# Extra arguments passed to the unit test binary (e.g. --gtest_filter=Foo.*)
UNIT_TEST_ARGS?=

# Fallback location of the GoogleTest sources
GTEST_SRC_DIR?=$(firstword $(wildcard /usr/src/googletest/googletest /usr/src/gtest))

# Flags for unit tests: same standard as the main build, plus the LMCP headers
# (found through the anod environment or the system include path).
UNIT_TEST_CXX_FLAGS:=$(CXX_FLAGS) $(UNIT_TEST_EXTRA_CXX_FLAGS)
UNIT_TEST_LIBS:=-llmcp -lpthread

# Detect whether a system libgtest is usable (evaluated lazily, only for 'test')
GTEST_SYSTEM_OK=$(shell echo 'int main(){return 0;}' | $(CXX) -x c++ - -lgtest -lpthread -o /dev/null >/dev/null 2>&1 && echo yes)

test: $(UNIT_TEST_BIN)
	@echo "[Run unit tests]"
	@$(UNIT_TEST_BIN) $(UNIT_TEST_ARGS)
	@$(MAKE) --no-print-directory test-diff

# Smoke differential run (Ada reference vs C++). Skipped when neither a golden
# file nor a uxas_ada binary is available, or when the uxas binary is missing.
test-diff:
	@if [ ! -x "$(OBJECT_DIR)/uxas" ]; then \
	    echo "[Skip smoke differential run: $(OBJECT_DIR)/uxas not built]"; \
	elif [ -z "$$(ls tests/cpp/pylmcp/diff/golden 2>/dev/null)" ] && ! command -v uxas_ada >/dev/null 2>&1; then \
	    echo "[Skip smoke differential run: no golden file and no uxas_ada]"; \
	else \
	    echo "[Run smoke differential test]"; \
	    PATH="$(abspath $(OBJECT_DIR)):$$PATH" python3 tests/cpp/run-diff run smoke_heartbeat; \
	fi

unit_tests: $(UNIT_TEST_BIN)

$(UNIT_TEST_DIR)/%.o: $(UNIT_TEST_SRC_DIR)/%.cpp
	@mkdir -p $(dir $@)
	@echo "[Compiling $<]"
	@$(CXX) -c $< $(UNIT_TEST_CXX_FLAGS) -MMD -MP -o $@

$(UNIT_TEST_DIR)/gtest-all.o:
	@test -n "$(GTEST_SRC_DIR)" || { echo "GoogleTest not found: install libgtest-dev or set GTEST_SRC_DIR" >&2; exit 1; }
	@mkdir -p $(dir $@)
	@echo "[Compiling GoogleTest from $(GTEST_SRC_DIR)]"
	@$(CXX) -c $(GTEST_SRC_DIR)/src/gtest-all.cc -I$(GTEST_SRC_DIR) -I$(GTEST_SRC_DIR)/include $(CXX_FLAGS) -o $@

$(UNIT_TEST_DIR)/gtest_main.o:
	@test -n "$(GTEST_SRC_DIR)" || { echo "GoogleTest not found: install libgtest-dev or set GTEST_SRC_DIR" >&2; exit 1; }
	@mkdir -p $(dir $@)
	@$(CXX) -c $(GTEST_SRC_DIR)/src/gtest_main.cc -I$(GTEST_SRC_DIR) -I$(GTEST_SRC_DIR)/include $(CXX_FLAGS) -o $@

# Test runner link: system libgtest when available, from-source otherwise.
$(UNIT_TEST_BIN): $(UNIT_TEST_OBJECTS)
	@echo "[Link unit tests]"
ifeq ($(GTEST_SYSTEM_OK),yes)
	@$(CXX) -o $@ $(UNIT_TEST_OBJECTS) -lgtest -lgtest_main $(UNIT_TEST_LIBS) $(UNIT_TEST_CXX_FLAGS)
else
	@$(MAKE) --no-print-directory $(UNIT_TEST_DIR)/gtest-all.o $(UNIT_TEST_DIR)/gtest_main.o
	@$(CXX) -o $@ $(UNIT_TEST_OBJECTS) $(UNIT_TEST_DIR)/gtest-all.o $(UNIT_TEST_DIR)/gtest_main.o $(UNIT_TEST_LIBS) $(UNIT_TEST_CXX_FLAGS)
endif

clean_unit_tests:
	@echo "[Remove unit tests]"
	rm -rf $(UNIT_TEST_DIR) $(UNIT_TEST_BIN)

-include $(wildcard $(UNIT_TEST_DIR)/*.d)

.PHONY: test test-diff unit_tests clean_unit_tests
