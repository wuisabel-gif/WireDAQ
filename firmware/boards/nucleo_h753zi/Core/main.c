/*
 * WireDAQ NUCLEO-H753ZI H0 bring-up.
 *
 * Scope: clock/reset sanity, LD1 heartbeat, and ST-LINK virtual COM startup
 * output. ADC, DMA, timers, and WireDAQ packet transmission intentionally do
 * not belong in this first board bring-up.
 */
#include "stm32h753xx.h"
#include <stdint.h>

#define LED_PORT GPIOB
#define LED_PIN  0u                 /* NUCLEO-H753ZI LD1, PB0 */
#define UART_PORT GPIOD
#define UART_TX_PIN 8u              /* USART3 TX / ST-LINK VCP, PD8 */
#define UART_BAUD 115200u

static void delay(volatile uint32_t iterations)
{
    while (iterations-- != 0u) {
        __NOP();
    }
}

static void gpio_init(void)
{
    RCC->AHB4ENR |= RCC_AHB4ENR_GPIOBEN | RCC_AHB4ENR_GPIODEN;
    (void)RCC->AHB4ENR;

    /* PB0 as push-pull output, low speed, no pull. */
    LED_PORT->MODER &= ~(3u << (LED_PIN * 2u));
    LED_PORT->MODER |=  (1u << (LED_PIN * 2u));
    LED_PORT->OTYPER &= ~(1u << LED_PIN);
    LED_PORT->OSPEEDR &= ~(3u << (LED_PIN * 2u));
    LED_PORT->PUPDR &= ~(3u << (LED_PIN * 2u));

    /* PD8 alternate function 7 = USART3_TX. */
    UART_PORT->MODER &= ~(3u << (UART_TX_PIN * 2u));
    UART_PORT->MODER |=  (2u << (UART_TX_PIN * 2u));
    UART_PORT->OTYPER &= ~(1u << UART_TX_PIN);
    UART_PORT->OSPEEDR &= ~(3u << (UART_TX_PIN * 2u));
    UART_PORT->OSPEEDR |=  (2u << (UART_TX_PIN * 2u));
    UART_PORT->PUPDR &= ~(3u << (UART_TX_PIN * 2u));
    UART_PORT->AFR[1] &= ~(0xfu << ((UART_TX_PIN - 8u) * 4u));
    UART_PORT->AFR[1] |=  (7u << ((UART_TX_PIN - 8u) * 4u));
}

static void uart_init(void)
{
    RCC->APB1LENR |= RCC_APB1LENR_USART3EN;
    (void)RCC->APB1LENR;

    USART3->CR1 = 0u;
    USART3->BRR = SystemCoreClock / UART_BAUD;
    USART3->CR1 = USART_CR1_TE | USART_CR1_UE;
}

static void uart_putc(char value)
{
    while ((USART3->ISR & USART_ISR_TXE_TXFNF) == 0u) {
    }
    USART3->TDR = (uint8_t)value;
}

static void uart_puts(const char *text)
{
    while (*text != '\0') {
        if (*text == '\n') {
            uart_putc('\r');
        }
        uart_putc(*text++);
    }
}

int main(void)
{
    gpio_init();
    uart_init();

    uart_puts("WireDAQ NUCLEO-H753ZI bring-up\n");
    uart_puts("firmware=h0-board-bringup version=0.1.0\n");
    uart_puts("led=PB0 uart=USART3_TX/PD8 baud=115200\n");

    for (;;) {
        LED_PORT->ODR ^= (1u << LED_PIN);
        uart_puts("heartbeat\n");
        delay(SystemCoreClock / 8u);
    }
}
