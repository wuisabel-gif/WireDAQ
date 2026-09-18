# Self-contained H0 bring-up image for STM32H753ZI.
# Requires arm-none-eabi-gcc/binutils and git submodules initialized.

TARGET := wiredaq_h753_bringup
BUILD := build
CC := arm-none-eabi-gcc
OBJCOPY := arm-none-eabi-objcopy
SIZE := arm-none-eabi-size

CMSIS_DEVICE := third_party/cmsis_device_h7
CMSIS_CORE := third_party/CMSIS_5/CMSIS/Core/Include
CFLAGS := -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard \
          -DSTM32H753xx -DUSE_FULL_LL_DRIVER \
          -ffunction-sections -fdata-sections -fno-common \
          -Wall -Wextra -Werror -O2 -g3
ASFLAGS := $(CFLAGS) -x assembler-with-cpp
LDFLAGS := $(CFLAGS) -T Linker/stm32h753zi.ld -Wl,--gc-sections \
           -Wl,-Map=$(BUILD)/$(TARGET).map --specs=nosys.specs --specs=nano.specs
INCLUDES := -IInc -I$(CMSIS_DEVICE)/Include -I$(CMSIS_CORE)

C_SOURCES := Core/main.c Core/system.c
STARTUP := $(CMSIS_DEVICE)/Source/Templates/gcc/startup_stm32h753xx.s
OBJECTS := $(patsubst %.c,$(BUILD)/%.o,$(C_SOURCES)) $(BUILD)/startup_stm32h753xx.o

.PHONY: all clean info

all: $(BUILD)/$(TARGET).elf $(BUILD)/$(TARGET).bin $(BUILD)/$(TARGET).hex info

$(BUILD)/$(TARGET).elf: $(OBJECTS) Linker/stm32h753zi.ld
	@mkdir -p $(dir $@)
	$(CC) $(LDFLAGS) $(OBJECTS) -o $@

$(BUILD)/$(TARGET).bin: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD)/$(TARGET).hex: $(BUILD)/$(TARGET).elf
	$(OBJCOPY) -O ihex $< $@

$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(INCLUDES) -c $< -o $@

$(BUILD)/startup_stm32h753xx.o: $(STARTUP)
	@mkdir -p $(dir $@)
	$(CC) $(ASFLAGS) $(INCLUDES) -c $< -o $@

info: $(BUILD)/$(TARGET).elf
	$(SIZE) $<

clean:
	rm -rf $(BUILD)
