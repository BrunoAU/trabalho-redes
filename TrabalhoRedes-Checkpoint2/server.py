import os
import socket
import sys
import threading

from checksum import calcular_checksum_pacote


YELLOW = "\033[33m"
RESET = "\033[0m"
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
MAX_PAYLOAD_CHARS = 4
ACK_TIMEOUT_SECONDS = 5.0

# Cada cliente possui seu próprio buffer. O lock também evita prompts de
# tamanho de janela concorrentes no terminal do servidor.
_buffers = {}
_window_input_lock = threading.Lock()


class ProtocolError(Exception):
    """Indica que uma mensagem recebida não segue o protocolo da aplicação."""


class FrameError(ProtocolError):
    def __init__(self, reason, seq=None):
        super().__init__(reason)
        self.reason = reason
        self.seq = seq


def enviar(conn, mensagem):
    if "\0" in mensagem:
        raise ValueError("O delimitador NUL não pode aparecer fora do payload codificado.")
    conn.sendall(mensagem.encode("utf-8") + b"\0")


def receber(conn):
    buffer = _buffers.get(conn, b"")
    while b"\0" not in buffer:
        try:
            dados = conn.recv(1024)
        except Exception:
            _buffers[conn] = buffer
            raise
        if not dados:
            _buffers[conn] = buffer
            raise ConnectionError("Conexão encerrada pelo cliente.")
        buffer += dados

    mensagem, restante = buffer.split(b"\0", 1)
    _buffers[conn] = restante
    try:
        return mensagem.decode("utf-8")
    except UnicodeDecodeError as erro:
        raise ProtocolError("Frame recebido não está em UTF-8 válido.") from erro


def receber_com_timeout(conn, contexto, timeout=ACK_TIMEOUT_SECONDS):
    conn.settimeout(timeout)
    try:
        return receber(conn)
    except socket.timeout as erro:
        raise TimeoutError(f"Timeout aguardando {contexto} ({timeout:g} s).") from erro
    finally:
        conn.settimeout(None)


def numero_ascii(valor):
    return valor.isascii() and valor.isdigit()


def parsear_begin(raw, tamanho_maximo):
    partes = raw.split("|")
    if len(partes) != 3 or partes[0] != "BEGIN":
        raise ProtocolError(f"Esperado BEGIN; recebido: {raw}")
    if not numero_ascii(partes[1]) or not numero_ascii(partes[2]):
        raise ProtocolError("BEGIN deve conter contagem de caracteres e de pacotes inteiras.")

    total_caracteres = int(partes[1])
    total_pacotes = int(partes[2])
    if not 1 <= total_caracteres <= tamanho_maximo:
        raise ProtocolError("O tamanho real da mensagem excede o limite negociado.")

    pacotes_esperados = (total_caracteres + MAX_PAYLOAD_CHARS - 1) // MAX_PAYLOAD_CHARS
    if total_pacotes != pacotes_esperados:
        raise ProtocolError("A quantidade de pacotes em BEGIN não corresponde ao tamanho informado.")
    return total_caracteres, total_pacotes


def parsear_pacote(raw):
    partes = raw.split("|")
    if len(partes) != 3:
        raise FrameError("MALFORMED")

    seq_texto, data_texto, checksum_texto = partes
    if not seq_texto.startswith("SEQ:") or not data_texto.startswith("DATA:"):
        raise FrameError("MALFORMED")
    if not checksum_texto.startswith("CHK:"):
        raise FrameError("MALFORMED")

    numero = seq_texto[4:]
    payload_hex = data_texto[5:]
    checksum_recebido = checksum_texto[4:]
    if not numero_ascii(numero) or str(int(numero or "0")) != numero or int(numero) < 1:
        raise FrameError("MALFORMED")
    seq = int(numero)

    if (
        not payload_hex
        or len(payload_hex) % 2 != 0
        or any(caractere not in "0123456789abcdef" for caractere in payload_hex)
    ):
        raise FrameError("MALFORMED", seq)

    if (
        len(checksum_recebido) != 4
        or any(caractere not in "0123456789ABCDEF" for caractere in checksum_recebido)
    ):
        raise FrameError("MALFORMED", seq)

    checksum_calculado = calcular_checksum_pacote(seq, payload_hex)
    if checksum_calculado != checksum_recebido:
        raise FrameError("CHECKSUM", seq)

    try:
        payload = bytes.fromhex(payload_hex).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as erro:
        raise FrameError("PAYLOAD_ENCODING", seq) from erro

    if not 1 <= len(payload) <= MAX_PAYLOAD_CHARS:
        raise FrameError("PAYLOAD_SIZE", seq)
    return seq, payload, checksum_recebido


def parsear_fim_janela(raw):
    partes = raw.split("|")
    if (
        len(partes) != 3
        or partes[0] != "WINDOW_END"
        or not numero_ascii(partes[1])
        or not numero_ascii(partes[2])
    ):
        raise ProtocolError(f"Marcador de fim de janela inválido: {raw}")
    return int(partes[1]), int(partes[2])


def receber_go_back_n(conn, addr, tamanho_janela, total_pacotes):
    mensagem = []
    base = 1

    while base <= total_pacotes:
        quantidade_esperada = min(tamanho_janela, total_pacotes - base + 1)
        ultimo_esperado = base + quantidade_esperada - 1
        recebidos = []
        quantidade_recebida = 0
        primeiro_erro = None

        print(
            f"[{addr}][SERVIDOR] Aguardando lote Go-Back-N "
            f"SEQ {base} a {ultimo_esperado}."
        )

        while True:
            try:
                raw = receber_com_timeout(
                    conn,
                    f"pacotes da janela Go-Back-N iniciada em SEQ {base}",
                )
            except TimeoutError:
                enviar(conn, f"NACK|{base}|TIMEOUT")
                raise

            if raw.startswith("WINDOW_END|"):
                try:
                    base_marcada, ultimo_marcado = parsear_fim_janela(raw)
                    if (base_marcada, ultimo_marcado) != (base, ultimo_esperado):
                        primeiro_erro = primeiro_erro or "WINDOW_BOUNDARY"
                except ProtocolError:
                    primeiro_erro = primeiro_erro or "WINDOW_BOUNDARY"
                break

            quantidade_recebida += 1
            seq_esperada = base + quantidade_recebida - 1
            try:
                seq, payload, checksum = parsear_pacote(raw)
            except FrameError as erro:
                primeiro_erro = primeiro_erro or erro.reason
                print(
                    f"[{addr}][SERVIDOR] DATA inválido na janela iniciada em "
                    f"SEQ {base}: {erro.reason}."
                )
                continue

            print(
                f"[{addr}][SERVIDOR] DATA recebido | SEQ={seq} "
                f"| payload={payload!r} | CHK={checksum} | CRC=OK"
            )
            if seq != seq_esperada:
                primeiro_erro = primeiro_erro or "SEQUENCE"
            recebidos.append((seq, payload))

        if quantidade_recebida != quantidade_esperada:
            primeiro_erro = primeiro_erro or "WINDOW_SIZE"
        if len(recebidos) != quantidade_esperada:
            primeiro_erro = primeiro_erro or "INVALID_FRAME"
        if primeiro_erro:
            enviar(conn, f"NACK|{base}|{primeiro_erro}")
            raise ProtocolError(
                f"Lote Go-Back-N rejeitado a partir de SEQ {base}: {primeiro_erro}."
            )

        mensagem.extend(payload for _, payload in recebidos)
        enviar(conn, f"ACK|GBN|{ultimo_esperado}")
        print(f"[{addr}][SERVIDOR] ACK cumulativo enviado até SEQ={ultimo_esperado}.")
        base = ultimo_esperado + 1

    return "".join(mensagem)


def receber_repeticao_seletiva(conn, addr, tamanho_janela, total_pacotes):
    # No caminho CP2, os pacotes chegam em ordem. O emissor já mantém até W
    # pacotes pendentes; o buffer fora de ordem será ativado no tratamento CP3.
    mensagem = []
    for seq_esperada in range(1, total_pacotes + 1):
        try:
            raw = receber_com_timeout(
                conn,
                f"DATA SEQ {seq_esperada} da Repetição Seletiva",
            )
        except TimeoutError:
            enviar(conn, f"NACK|{seq_esperada}|TIMEOUT")
            raise

        try:
            seq, payload, checksum = parsear_pacote(raw)
        except FrameError as erro:
            enviar(conn, f"NACK|{erro.seq or seq_esperada}|{erro.reason}")
            raise ProtocolError(
                f"DATA da Repetição Seletiva rejeitado: {erro.reason}."
            ) from erro

        if seq != seq_esperada:
            enviar(conn, f"NACK|{seq_esperada}|SEQUENCE")
            raise ProtocolError(
                f"Esperado SEQ {seq_esperada}, mas recebido SEQ {seq}."
            )

        print(
            f"[{addr}][SERVIDOR] DATA recebido | SEQ={seq} "
            f"| payload={payload!r} | CHK={checksum} | CRC=OK"
        )
        mensagem.append(payload)
        enviar(conn, f"ACK|SR|{seq}")
        print(f"[{addr}][SERVIDOR] ACK individual enviado para SEQ={seq}.")

    return "".join(mensagem)


def concluir_transferencia(conn, addr, texto, total_caracteres, total_pacotes):
    if len(texto) != total_caracteres:
        enviar(conn, "ERROR|MESSAGE_LENGTH")
        raise ProtocolError(
            f"Mensagem remontada tem {len(texto)} caracteres; "
            f"BEGIN declarou {total_caracteres}."
        )

    print(f"\n[{addr}][SERVIDOR] Mensagem completa recebida:")
    print(texto)
    print(
        f"[{addr}][SERVIDOR] Total: {total_caracteres} caracteres "
        f"em {total_pacotes} pacotes."
    )
    enviar(conn, f"COMPLETE|{total_caracteres}|{total_pacotes}")


def receber_transferencia(conn, addr, operacao, tamanho_maximo, tamanho_janela):
    inicio = receber_com_timeout(conn, "BEGIN da mensagem")
    try:
        total_caracteres, total_pacotes = parsear_begin(inicio, tamanho_maximo)
    except ProtocolError as erro:
        enviar(conn, "ERROR|BEGIN")
        raise

    print(
        f"[{addr}][SERVIDOR] Transferência iniciada | "
        f"caracteres={total_caracteres} | pacotes={total_pacotes} "
        f"| janela={tamanho_janela}."
    )

    if operacao == 1:
        texto = receber_go_back_n(conn, addr, tamanho_janela, total_pacotes)
    else:
        texto = receber_repeticao_seletiva(
            conn, addr, tamanho_janela, total_pacotes
        )
    concluir_transferencia(conn, addr, texto, total_caracteres, total_pacotes)


def solicitar_tamanho_janela(addr):
    with _window_input_lock:
        while True:
            bruto = input(
                f"[SERVIDOR][{addr}] Tamanho da janela (1 a 5) [ENTER = 5]: "
            ).strip()
            if bruto == "":
                return 5
            if bruto.isascii() and bruto.isdigit() and 1 <= int(bruto) <= 5:
                return int(bruto)
            print("[SERVIDOR] Digite um inteiro entre 1 e 5.")


def handle_client(conn, addr):
    print(f"\n[SERVIDOR] Nova conexão de {addr}.")
    try:
        while True:
            menu = (
                "[SERVIDOR] Escolha o modo de operação\n"
                "[1] Envio em lote / Go-Back-N\n"
                "[2] Envio individual / Repetição Seletiva\n"
            )
            enviar(conn, menu)
            operacao_escolhida = receber(conn).strip()
            if operacao_escolhida in ("1", "2"):
                operacao = int(operacao_escolhida)
                enviar(conn, "True")
                nome = "Go-Back-N" if operacao == 1 else "Repetição Seletiva"
                print(f"[{addr}][CLIENTE] Modo escolhido: {nome}.")
                break
            enviar(conn, "[SERVIDOR] Opção inválida. Escolha 1 ou 2 e tente novamente.\n")

        enviar(
            conn,
            "[SERVIDOR] Qual o tamanho máximo do texto? (Mínimo: 30 caracteres.)\n",
        )
        bruto_tamanho = receber(conn).strip()
        if not bruto_tamanho.isascii() or not bruto_tamanho.isdigit():
            enviar(conn, "[SERVIDOR]NEGADO: tamanho inválido.")
            return
        tamanho_maximo = int(bruto_tamanho)

        tamanho_janela = solicitar_tamanho_janela(addr)
        enviar(conn, f"[SERVIDOR] Janela atual: {tamanho_janela} pacotes.\n")
        enviar(conn, str(tamanho_janela))

        if tamanho_maximo < 30:
            enviar(
                conn,
                f"[SERVIDOR]NEGADO: tamanho {tamanho_maximo} é menor que o mínimo de 30.",
            )
            print(f"[{addr}][SERVIDOR] Handshake recusado: limite menor que 30.")
            return

        enviar(conn, "[SERVIDOR]Tamanho aceito! Handshake concluído.\n")
        nome = "Go-Back-N" if operacao == 1 else "Repetição Seletiva"
        print(
            f"[{addr}][SERVIDOR] Handshake concluído | modo={nome} "
            f"| máximo={tamanho_maximo} | janela={tamanho_janela}."
        )

        receber_transferencia(
            conn, addr, operacao, tamanho_maximo, tamanho_janela
        )

    except (ConnectionError, OSError, ProtocolError, TimeoutError, ValueError) as erro:
        print(f"\n[SERVIDOR][{addr}] Sessão encerrada: {erro}")
    finally:
        _buffers.pop(conn, None)
        conn.close()
        print(f"[SERVIDOR] Conexão com {addr} encerrada.")


def cabecalho():
    servidor = r"""
███████╗███████╗██████╗ ██╗   ██╗██╗██████╗  ██████╗ ██████╗
██╔════╝██╔════╝██╔══██╗██║   ██║██║██╔══██╗██╔═══██╗██╔══██╗
███████╗█████╗  ██████╔╝██║   ██║██║██║  ██║██║   ██║██████╔╝
╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██║██║  ██║██║   ██║██╔══██╗
███████║███████╗██║  ██║ ╚████╔╝ ██║██████╔╝╚██████╔╝██║  ██║
╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚═════╝  ╚═════╝  ╚═╝
"""
    print(YELLOW + servidor + RESET)


def start_server():
    # Evita falha ao imprimir o cabeçalho e payloads UTF-8 no Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8", errors="replace", line_buffering=True
        )
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((SERVER_HOST, SERVER_PORT))
    server.listen(5)
    cabecalho()
    print(
        f"[SERVIDOR] Aguardando conexões em {SERVER_HOST}:{SERVER_PORT} "
        "(Ctrl+C para encerrar).\n"
    )

    try:
        while True:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        print("\n[SERVIDOR] Encerrado pelo usuário.")
    finally:
        server.close()


if __name__ == "__main__":
    start_server()
