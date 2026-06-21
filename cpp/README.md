# WireDAQ — C / C++ codec library

The wire-format codec as a `find_package`-able CMake library. It is the **same C core**
the firmware uses (`firmware/codec/wiredaq_codec.{h,c}`), exposed as a linkable target with
an idiomatic C++17 wrapper on top. It is held to the **same golden vectors** as the Python
and C codecs (`src/wiredaq/protocol/golden/vectors.json`), so all three stay byte-compatible
— see [`docs/adr/0003-wire-format-specifics.md`](../docs/adr/0003-wire-format-specifics.md).

## Targets & headers

- **`wiredaq::codec`** — the library target (static by default; `-DBUILD_SHARED_LIBS=ON`
  for a shared lib).
- **`<wiredaq_codec.h>`** — the C API (`wd_encode_sample_block`, `wd_decode_frame`,
  `wd_crc16_ccitt_false`, `wd_packet_t`, `wd_status_t`). C++-safe (`extern "C"`).
- **`<wiredaq/wiredaq.hpp>`** — header-only C++17 wrapper: a `wiredaq::Packet` with a
  `std::vector<std::int16_t>` of samples, `encode()` → `std::vector<std::uint8_t>` (throws
  `wiredaq::EncodeError`), and `decode()` → `std::optional<Packet>` (or a `Status`-returning
  overload that distinguishes CRC from framing failures).

## Build, test, install

```bash
cmake -S . -B build                 # configure (from the repo root)
cmake --build build                 # build the library, tests, and example
ctest --test-dir build --output-on-failure   # run the C++ golden-vector conformance test
cmake --install build --prefix /usr/local     # install headers + lib + package config
```

Options: `-DWIREDAQ_BUILD_TESTS=OFF`, `-DWIREDAQ_BUILD_EXAMPLES=OFF`,
`-DBUILD_SHARED_LIBS=ON`. The test step regenerates the golden header from `vectors.json`
(needs `python3`); the library itself has no build-time dependencies.

## Use it from another CMake project

After installing (or via `FetchContent` / `add_subdirectory` of this repo):

```cmake
find_package(WireDAQ CONFIG REQUIRED)
add_executable(my_app main.cpp)
target_link_libraries(my_app PRIVATE wiredaq::codec)
```

```cpp
#include <wiredaq/wiredaq.hpp>

wiredaq::Packet pkt;
pkt.node_id = 7; pkt.seq = 42; pkt.t_node_us = 1234;
pkt.sample_rate_hz = 3200; pkt.channel_count = 3;     // X / Y / Z
pkt.samples = { 10, -20, 16384,  12, -18, 16380 };    // flat, row-major

std::vector<std::uint8_t> frame = wiredaq::encode(pkt);        // throws on bad input
std::optional<wiredaq::Packet> back = wiredaq::decode(frame);  // nullopt on CRC/framing
// *back == pkt
```

See [`examples/encode_decode.cpp`](../examples/encode_decode.cpp) for a runnable version.

## Layout

```text
CMakeLists.txt                 (repo root)   library target, install/export, CTest
include/wiredaq/wiredaq.hpp                   the C++17 wrapper
firmware/codec/wiredaq_codec.{h,c}            the shared C core (also the firmware codec)
cpp/test/test_codec.cpp                       C++ conformance test (golden vectors)
examples/encode_decode.cpp                    minimal usage example
cmake/WireDAQConfig.cmake.in                  package config template for find_package
```
