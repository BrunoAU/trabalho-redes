import os
import socket
import sys
import time

from checksum import calcular_checksum_pacote


BLUE = "\033[34m"
RESET = "\033[0m"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
MAX_PAYLOAD_CHARS = 4
ACK_TIMEOUT_SECONDS = 5.0

# TCP é um fluxo de bytes. O buffer mantém mensagens completas e fragmentos
# recebidos junto com outra mensagem, enquanto o byte nulo delimita cada frame.
_buffers = {}


class ProtocolError(Exception):
    """Indica que uma mensagem recebida não segue o protocolo da aplicação."""


def receber(client):
    buffer = _buffers.get(client, b"")
    while b"\0" not in buffer:
        try:
            dados = client.recv(1024)
        except Exception:
            # Preserva bytes parciais caso a leitura expire antes do delimitador.
            _buffers[client] = buffer
            raise
        if not dados:
            _buffers[client] = buffer
            raise ConnectionError("Conexão encerrada pelo servidor.")
        buffer += dados

    mensagem, restante = buffer.split(b"\0", 1)
    _buffers[client] = restante
    try:
        return mensagem.decode("utf-8")
    except UnicodeDecodeError as erro:
        raise ProtocolError("Frame recebido não está em UTF-8 válido.") from erro


def enviar(mensagem, client):
    if "\0" in mensagem:
        raise ValueError("O delimitador NUL não pode aparecer fora do payload codificado.")
    client.sendall(mensagem.encode("utf-8") + b"\0")


def receber_com_timeout(client, contexto, timeout=ACK_TIMEOUT_SECONDS):
    client.settimeout(timeout)
    try:
        return receber(client)
    except socket.timeout as erro:
        raise TimeoutError(f"Timeout aguardando {contexto} ({timeout:g} s).") from erro
    finally:
        client.settimeout(None)


def montar_pacote(seq, payload):
    payload_hex = payload.encode("utf-8").hex()
    checksum = calcular_checksum_pacote(seq, payload_hex)
    return f"SEQ:{seq}|DATA:{payload_hex}|CHK:{checksum}"


def dividir_mensagem(mensagem):
    return [
        mensagem[inicio:inicio + MAX_PAYLOAD_CHARS]
        for inicio in range(0, len(mensagem), MAX_PAYLOAD_CHARS)
    ]


def validar_begin_ack(message, modo, sequencia_esperada):
    if message.startswith("NACK|"):
        raise ProtocolError(f"Servidor rejeitou a transmissão: {message}")

    partes = message.split("|")
    if len(partes) != 3 or partes[0] != "ACK" or partes[1] != modo:
        raise ProtocolError(f"ACK inesperado: {message}")
    if not partes[2].isascii() or not partes[2].isdigit():
        raise ProtocolError(f"Número de sequência inválido no ACK: {message}")
    if int(partes[2]) != sequencia_esperada:
        raise ProtocolError(
            f"ACK confirmou SEQ {partes[2]}, mas era esperado {sequencia_esperada}."
        )


def enviar_go_back_n(client, pacotes, tamanho_janela):
    inicio = 0
    while inicio < len(pacotes):
        base = inicio + 1
        fim_indice = min(inicio + tamanho_janela, len(pacotes))
        ultimo = fim_indice

        print(f"\n[CLIENTE] Enviando janela Go-Back-N: SEQ {base} a {ultimo}.")
        for indice in range(inicio, fim_indice):
            seq = indice + 1
            pacote = montar_pacote(seq, pacotes[indice])
            enviar(pacote, client)
            print(f"[CLIENTE] DATA enviado | SEQ={seq} | payload={pacotes[indice]!r}")

        # O marcador delimita cada lote. O servidor consegue drenar a janela
        # inteira antes de confirmar ou rejeitar sua base.
        enviar(f"WINDOW_END|{base}|{ultimo}", client)
        ack = receber_com_timeout(client, f"ACK cumulativo até SEQ {ultimo}")
        validar_begin_ack(ack, "GBN", ultimo)
        print(f"[CLIENTE] ACK cumulativo recebido | até SEQ={ultimo}")
        inicio = fim_indice


def enviar_repeticao_seletiva(client, pacotes, tamanho_janela):
    total = len(pacotes)
    proxima_sequencia = 1
    base = 1
    pendentes = {}

    while base <= total:
        # Preenche a janela e mantém no máximo W pacotes sem ACK.
        while (
            proxima_sequencia <= total
            and proxima_sequencia < base + tamanho_janela
        ):
            seq = proxima_sequencia
            pacote = montar_pacote(seq, pacotes[seq - 1])
            enviar(pacote, client)
            pendentes[seq] = time.monotonic()
            print(
                f"[CLIENTE] DATA enviado | SEQ={seq} "
                f"| payload={pacotes[seq - 1]!r}"
            )
            proxima_sequencia += 1

        seq_temporizador = min(pendentes, key=pendentes.get)
        restante = (
            pendentes[seq_temporizador]
            + ACK_TIMEOUT_SECONDS
            - time.monotonic()
        )
        if restante <= 0:
            raise TimeoutError(
                f"Timeout aguardando ACK individual de SEQ {seq_temporizador}."
            )

        ack = receber_com_timeout(
            client,
            f"ACK individual de um pacote pendente (mais antigo: SEQ {seq_temporizador})",
            restante,
        )
        if ack.startswith("NACK|"):
            raise ProtocolError(f"Servidor rejeitou a transmissão: {ack}")

        partes = ack.split("|")
        if len(partes) != 3 or partes[0] != "ACK" or partes[1] != "SR":
            raise ProtocolError(f"ACK inesperado na Repetição Seletiva: {ack}")
        if not partes[2].isascii() or not partes[2].isdigit():
            raise ProtocolError(f"Número de sequência inválido no ACK: {ack}")

        seq_confirmada = int(partes[2])
        if seq_confirmada not in pendentes:
            raise ProtocolError(
                f"ACK de SEQ {seq_confirmada} não corresponde a pacote pendente."
            )

        del pendentes[seq_confirmada]
        print(f"[CLIENTE] ACK individual recebido | SEQ={seq_confirmada}")
        base = min(pendentes) if pendentes else proxima_sequencia


def receber_conclusao(client, total_caracteres, total_pacotes):
    conclusao = receber_com_timeout(client, "confirmação de mensagem completa")
    partes = conclusao.split("|")
    if (
        len(partes) != 3
        or partes[0] != "COMPLETE"
        or not partes[1].isascii()
        or not partes[1].isdigit()
        or not partes[2].isascii()
        or not partes[2].isdigit()
    ):
        raise ProtocolError(f"Confirmação final inválida: {conclusao}")
    if (int(partes[1]), int(partes[2])) != (total_caracteres, total_pacotes):
        raise ProtocolError(f"Confirmação final não corresponde à mensagem: {conclusao}")
    print(
        f"[CLIENTE] Mensagem concluída pelo servidor | "
        f"caracteres={total_caracteres} | pacotes={total_pacotes}"
    )


def limpar_terminal():
    os.system("cls" if os.name == "nt" else "clear")


def cabecalho():
    cliente = r"""
 ██████╗██╗     ██╗███████╗███╗   ██╗████████╗███████╗
██╔════╝██║     ██║██╔════╝████╗  ██║╚══██╔══╝██╔════╝
██║     ██║     ██║█████╗  ██╔██╗ ██║   ██║   █████╗
██║     ██║     ██║██╔══╝  ██║╚██╗██║   ██║   ██╔══╝
╚██████╗███████╗██║███████╗██║ ╚████║   ██║   ███████╗
 ╚═════╝╚══════╝╚═╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝
"""
    print(BLUE + cliente + RESET)


def negociar_handshake(client):
    operacao_escolhida = None
    while True:
        operacao = receber(client)
        print(operacao, end="")
        operacao_escolhida = input("-> ").strip()
        enviar(operacao_escolhida, client)

        validacao = receber(client)
        if validacao == "True":
            break
        print(validacao, end="")

    texto_tamanho = receber(client)
    print(texto_tamanho, end="")
    while True:
        bruto = input("-> ").strip()
        try:
            tamanho_maximo = int(bruto)
            if tamanho_maximo >= 30:
                break
            print("[CLIENTE] O limite configurado deve ser de pelo menos 30 caracteres.")
        except ValueError:
            print("[CLIENTE] Digite um número inteiro válido.")

    enviar(str(tamanho_maximo), client)
    print(receber(client), end="")
    tamanho_janela = int(receber(client))
    resposta = receber(client)
    print(resposta, end="")
    if not resposta.startswith("[SERVIDOR]Tamanho aceito"):
        raise ProtocolError("O servidor recusou os parâmetros do handshake.")

    print("\n[CLIENTE] Handshake concluído.")
    print(f"[CLIENTE] Modo={operacao_escolhida} | máximo={tamanho_maximo} | janela={tamanho_janela}")
    return operacao_escolhida, tamanho_maximo, tamanho_janela


def iniciar_cliente():
    # Evita falha ao imprimir o cabeçalho e payloads UTF-8 no Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Entradas redirecionadas (por exemplo, testes por pipe) usam UTF-8.
    if not sys.stdin.isatty() and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    limpar_terminal()
    cabecalho()
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client.connect((SERVER_HOST, SERVER_PORT))
        modo, tamanho_maximo, tamanho_janela = negociar_handshake(client)

        while True:
            mensagem = input(
                f"\nInforme o texto a enviar (1 a {tamanho_maximo} caracteres):\n-> "
            )
            tamanho_real = len(mensagem)
            if tamanho_real == 0:
                print("[CLIENTE] A mensagem não pode ser vazia.")
            elif tamanho_real > tamanho_maximo:
                print(
                    f"[CLIENTE] Texto com {tamanho_real} caracteres; "
                    f"o limite negociado é {tamanho_maximo}."
                )
            else:
                break

        pacotes = dividir_mensagem(mensagem)
        total_pacotes = len(pacotes)
        enviar(f"BEGIN|{tamanho_real}|{total_pacotes}", client)
        print(
            f"\n[CLIENTE] Iniciando transferência: {tamanho_real} caracteres, "
            f"{total_pacotes} pacotes de até {MAX_PAYLOAD_CHARS} caracteres."
        )

        if modo == "1":
            enviar_go_back_n(client, pacotes, tamanho_janela)
        else:
            enviar_repeticao_seletiva(client, pacotes, tamanho_janela)

        receber_conclusao(client, tamanho_real, total_pacotes)

    except (ConnectionError, OSError, ProtocolError, TimeoutError, ValueError) as erro:
        print(f"\n[CLIENTE] Sessão encerrada: {erro}")
    finally:
        _buffers.pop(client, None)
        client.close()


if __name__ == "__main__":
    iniciar_cliente()
