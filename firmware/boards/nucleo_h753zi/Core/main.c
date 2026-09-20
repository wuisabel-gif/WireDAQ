/*
 * WireDAQ NUCLEO-H753ZI protocol emission (issue #15).
 *
 * Poll ADC1 on PA3, encode each reading with the existing C codec, and send
 * a SAMPLE_BLOCK frame on USART3. Timer-triggered ADC and DMA belong later.
 */
#include "stm32h753xx.h"
#include "h753_protocol.h"

#include <stddef.h>
#include <stdint.h>

#define LED_PORT GPIOB
#define LED_PIN  0u                 /* NUCLEO-H753ZI LD1, PB0 */
#define UART_PORT GPIOD
#define UART_TX_PIN 8u              /* USART3 TX / ST-LINK VCP, PD8 */
#define UART_BAUD 115200u
#define ADC_PORT GPIOA
#define ADC_PIN 3u                  /* Arduino A0, ADC12_INP15 */
#define ADC_CHANNEL 15u

static volatile uint32_t ticks_ms;

void SysTick_Handler(void)
{
    ticks_ms++;
}

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

static void uart_write(const uint8_t *data, size_t length)
{
    size_t i;
    for (i = 0u; i < length; ++i) {
        while ((USART3->ISR & USART_ISR_TXE_TXFNF) == 0u) {
        }
        USART3->TDR = data[i];
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

int main(void)
{
    uint32_t seq = 0u;
    uint32_t last_ms;
    uint8_t frame[WD_MAX_PACKET_BYTES];

    gpio_init();
    uart_init();
    adc_init();
    (void)SysTick_Config(SystemCoreClock / 1000u);

    uart_puts("WireDAQ NUCLEO-H753ZI\n");
    uart_puts("firmware=h2-protocol version=0.3.0\n");
    uart_puts("node_id=1 sample_rate_hz=10 channels=1 mapping=raw-32768\n");

    last_ms = ticks_ms;
    for (;;) {
        uint32_t now = ticks_ms;
        size_t length = 0u;
        uint16_t raw;
        uint64_t t_node_us;

        if ((now - last_ms) < H753_PERIOD_MS) {
            continue;
        }
        last_ms = now;

        raw = adc_read();
        t_node_us = (uint64_t)now * 1000u;
        if (h753_encode_adc_sample(raw, seq, t_node_us, frame, sizeof frame, &length) == WD_OK) {
            uart_write(frame, length);
            seq++;
            LED_PORT->ODR ^= (1u << LED_PIN);
        }
    }
}
