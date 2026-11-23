"""Implementação manual de CRC-16/IBM-3740 (CRC-16/CCITT-FALSE)."""

CRC16_POLYNOMIAL = 0x1021
CRC16_INITIAL_VALUE = 0xFFFF
CRC16_MASK = 0xFFFF


def crc16_ibm_3740(dados: bytes) -> int:
    """Calcula CRC-16/IBM-3740 bit a bit, sem biblioteca de checksum."""
    crc = CRC16_INITIAL_VALUE

    for byte in dados:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC16_POLYNOMIAL) & CRC16_MASK
            else:
                crc = (crc << 1) & CRC16_MASK

    return crc


def calcular_checksum_pacote(seq: int, payload_hex: str) -> str:
    """Protege a sequência e o campo DATA hexadecimal do pacote."""
    prefixo = f"SEQ:{seq}|DATA:{payload_hex}".encode("ascii")
    return f"{crc16_ibm_3740(prefixo):04X}"
