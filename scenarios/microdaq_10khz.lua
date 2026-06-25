-- MicroDAQ raw-streaming scenario sketch for the future Rust/Lua runner.
--
-- This file is intentionally data-shaped Lua: easy to edit, easy to validate,
-- and close to the questions the MicroDAQ DMA work needs to answer.

return {
  name = "microdaq_10khz",
  duration_s = 10,

  transport = {
    kind = "udp",
    loss_rate = 0.0,
    duplicate_rate = 0.0,
    reorder_rate = 0.0,
    jitter_us = 250,
  },

  nodes = {
    {
      id = 1,
      name = "microdaq_adc_bank_a",
      sample_rate_hz = 10000,
      samples_per_packet = 4,

      channels = {
        { id = 0, name = "strain_0", kind = "raw_adc_i16" },
        { id = 1, name = "strain_1", kind = "raw_adc_i16" },
        { id = 2, name = "pressure_0", kind = "raw_adc_i16" },
        { id = 3, name = "pressure_1", kind = "raw_adc_i16" },
      },
    },
  },

  assertions = {
    max_packet_bytes = 256,
    require_crc = true,
    require_monotonic_sequence = true,
    receiver_side_processing = true,
  },
}
