-- Static-fire fault-injection scenario sketch.

return {
  name = "static_fire_faults",
  duration_s = 30,

  transport = {
    kind = "udp",
    loss_rate = 0.01,
    duplicate_rate = 0.002,
    reorder_rate = 0.002,
    jitter_us = 500,
  },

  nodes = {
    {
      id = 7,
      name = "fin_root_daq",
      sample_rate_hz = 5000,
      samples_per_packet = 8,

      channels = {
        { id = 0, name = "strain_root_a", kind = "raw_adc_i16" },
        { id = 1, name = "strain_root_b", kind = "raw_adc_i16" },
        { id = 2, name = "pressure_root", kind = "raw_adc_i16" },
      },
    },
  },

  faults = {
    { at_s = 12.5, kind = "packet_loss_burst", duration_s = 0.25, loss_rate = 0.15 },
    { at_s = 18.0, kind = "sensor_stuck", node_id = 7, channel_id = 1 },
  },
}
