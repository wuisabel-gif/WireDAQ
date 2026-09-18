/* Minimal H753 system definition for the H0 bring-up image.
 *
 * The MCU uses its reset-selected HSI clock for this first image. Later
 * milestones can replace SystemInit with an explicit clock tree setup after
 * the board heartbeat/UART path is proven.
 */
#include "stm32h753xx.h"

uint32_t SystemCoreClock = 64000000u;

/* Required by the current ST startup template; reset already selects run mode. */
void ExitRun0Mode(void)
{
}

void SystemInit(void)
{
    /* Keep reset clock configuration for deterministic board bring-up. */
}

void SystemCoreClockUpdate(void)
{
    SystemCoreClock = 64000000u;
}
