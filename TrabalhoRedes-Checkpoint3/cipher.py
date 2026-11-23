"""Cifra de César manual sobre bytes UTF-8, para demonstração didática."""

DESLOCAMENTO_COMPARTILHADO = 3


def _transformar(dados: bytes, deslocamento: int) -> bytes:
    return bytes((byte + deslocamento) % 256 for byte in dados)


def cifrar(texto: str) -> bytes:
    """Cifra cada byte UTF-8 por uma rotação modular de 0 a 255."""
    return _transformar(texto.encode("utf-8"), DESLOCAMENTO_COMPARTILHADO)


def decifrar(texto_cifrado: bytes) -> str:
    """Desfaz a rotação e decodifica o texto UTF-8 original."""
    dados = _transformar(texto_cifrado, -DESLOCAMENTO_COMPARTILHADO)
    return dados.decode("utf-8")
