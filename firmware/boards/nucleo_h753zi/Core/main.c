/*
 * WireDAQ NUCLEO-H753ZI H0/H1 bring-up.
 *
 * H0: LED heartbeat and ST-LINK virtual COM startup output.
 * H1: one ADC1 polling conversion on PA3 / ADC12_INP15.
 *
 * This is intentionally polling only. Timer triggering, DMA, and WireDAQ
 * packet transmission belong to later milestones.
 */
#include "stm32h753xx.h"
#include <stdint.h>

#define LED_PORT GPIOB
#define LED_PIN  0u                 /* NUCLEO-H753ZI LD1, PB0 */
#define UART_PORT GPIOD
#define UART_TX_PIN 8u              /* USART3 TX / ST-LINK VCP, PD8 */
#define UART_BAUD 115200u
#define ADC_PORT GPIOA
#define ADC_PIN 3u                  /* Arduino A0, ADC12_INP15 */
#define ADC_CHANNEL 15u
#define ADC_REFERENCE_MV 3300u      /* documented board-supply assumption */
#define ADC_MAX_COUNT 65535u       /* 16-bit ADC resolution */

static void delay(volatile uint32_t iterations)
{
    while (iterations-- != 0u) {
        __NOP();
    }
}

static void gpio_init(void)
{
    RCC->AHB4ENR |= RCC_AHB4ENR_GPIOAEN |
                    RCC_AHB4ENR_GPIOBEN |
                    RCC_AHB4ENR_GPIODEN;
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

    /* PA3 in analog mode, no pull. */
    ADC_PORT->MODER |= (3u << (ADC_PIN * 2u));
    ADC_PORT->PUPDR &= ~(3u << (ADC_PIN * 2u));
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

static void uart_put_u32(uint32_t value)
{
    char digits[10];
    uint32_t count = 0u;

    if (value == 0u) {
        uart_putc('0');
        return;
    }
    while (value != 0u) {
        digits[count++] = (char)('0' + (value % 10u));
        value /= 10u;
    }
    while (count != 0u) {
        uart_putc(digits[--count]);
    }
}

static void adc_init(void)
{
    RCC->AHB1ENR |= RCC_AHB1ENR_ADC12EN;
    (void)RCC->AHB1ENR;

    /* Use the synchronous AHB clock divided by four for the ADC kernel. */
    ADC12_COMMON->CCR &= ~(ADC_CCR_CKMODE | ADC_CCR_PRESC);
    ADC12_COMMON->CCR |= ADC_CCR_CKMODE_0 | ADC_CCR_CKMODE_1;

    ADC1->CR &= ~ADC_CR_DEEPPWD;
    ADC1->CR |= ADC_CR_ADVREGEN;
    delay(SystemCoreClock / 100000u); /* regulator startup: at least 10 us */

    ADC1->DIFSEL &= ~(1u << ADC_CHANNEL); /* single-ended */
    ADC1->PCSEL = (1u << ADC_CHANNEL);
    ADC1->SMPR2 &= ~(ADC_SMPR2_SMP15_Msk);
    ADC1->SMPR2 |= (7u << ADC_SMPR2_SMP15_Pos); /* longest sample time */
    ADC1->SQR1 = (ADC_CHANNEL << ADC_SQR1_SQ1_Pos); /* one regular rank */
    ADC1->CFGR &= ~(ADC_CFGR_RES | ADC_CFGR_CONT | ADC_CFGR_EXTEN);

    ADC1->CR |= ADC_CR_ADCAL;
    while ((ADC1->CR & ADC_CR_ADCAL) != 0u) {
    }

    ADC1->ISR = ADC_ISR_ADRDY;
    ADC1->CR |= ADC_CR_ADEN;
    while ((ADC1->ISR & ADC_ISR_ADRDY) == 0u) {
    }
}

static uint16_t adc_read(void)
{
    ADC1->ISR = ADC_ISR_EOC | ADC_ISR_EOS;
    ADC1->CR |= ADC_CR_ADSTART;
    while ((ADC1->ISR & ADC_ISR_EOC) == 0u) {
    }
    return (uint16_t)ADC1->DR;
}

static uint32_t adc_to_millivolts(uint16_t raw)
{
    return ((uint32_t)raw * ADC_REFERENCE_MV) / ADC_MAX_COUNT;
}

int main(void)
{
    gpio_init();
    uart_init();
    adc_init();

    uart_puts("WireDAQ NUCLEO-H753ZI bring-up\n");
    uart_puts("firmware=h1-adc-polling version=0.2.0\n");
    uart_puts("adc=ADC1_INP15 pin=PA3 resolution=16 reference_mv=3300\n");

    for (;;) {
        uint16_t raw = adc_read();

        LED_PORT->ODR ^= (1u << LED_PIN);
        uart_puts("adc_raw=");
        uart_put_u32(raw);
        uart_puts(" adc_mv=");
        uart_put_u32(adc_to_millivolts(raw));
        uart_puts("\n");
        delay(SystemCoreClock / 8u);
    }
}
