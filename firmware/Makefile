# WireDAQ firmware codec — build & conformance test.
#
#   make test     regenerate golden_vectors.h from vectors.json, build, run
#   make clean    remove build artifacts
#
# The golden header is generated from protocol/golden/vectors.json so the C codec
# is held to the exact same vectors as the Python codec — the cross-language proof.

CC      ?= cc
CFLAGS  ?= -std=c11 -Wall -Wextra -Werror -O2
PYTHON  ?= python3

CODEC_DIR := codec
TEST_DIR  := test
BUILD_DIR := build

GEN       := $(TEST_DIR)/gen_golden_header.py
GEN_HDR   := $(TEST_DIR)/golden_vectors.h
TEST_BIN  := $(BUILD_DIR)/test_golden_vectors

.PHONY: test clean

test: $(TEST_BIN)
	@echo "--- running firmware conformance test ---"
	@$(TEST_BIN)

$(GEN_HDR): $(GEN) ../protocol/golden/vectors.json
	$(PYTHON) $(GEN)

$(TEST_BIN): $(TEST_DIR)/test_golden_vectors.c $(CODEC_DIR)/wiredaq_codec.c \
             $(CODEC_DIR)/wiredaq_codec.h $(GEN_HDR)
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -I$(CODEC_DIR) -I$(TEST_DIR) \
		$(TEST_DIR)/test_golden_vectors.c $(CODEC_DIR)/wiredaq_codec.c \
		-o $(TEST_BIN)

clean:
	rm -rf $(BUILD_DIR) $(GEN_HDR)
