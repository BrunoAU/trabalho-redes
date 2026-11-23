import socket
import sys
import threading

from checksum import calcular_checksum_pacote
from cipher import decifrar


SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
MAX_PAYLOAD_CHARS = 4
ACK_TIMEOUT_SECONDS = 5.0
SERVER_WAIT_SECONDS = ACK_TIMEOUT_SECONDS + 2.0
MAX_RETRIES = 5

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


def receber_com_timeout(conn, contexto, timeout=SERVER_WAIT_SECONDS):
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
        raise ProtocolError("BEGIN deve conter contagens inteiras em ASCII.")

    total_caracteres = int(partes[1])
    total_pacotes = int(partes[2])
    if not 1 <= total_caracteres <= tamanho_maximo:
        raise ProtocolError("O tamanho real excede o limite negociado.")
    pacotes_esperados = (
        total_caracteres + MAX_PAYLOAD_CHARS - 1
    ) // MAX_PAYLOAD_CHARS
    if total_pacotes != pacotes_esperados:
        raise ProtocolError("A contagem de pacotes em BEGIN não corresponde ao texto.")
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
    if (
        not numero_ascii(numero)
        or str(int(numero or "0")) != numero
        or int(numero) < 1
    ):
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
        payload = decifrar(bytes.fromhex(payload_hex))
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


def registrar_nack(conn, stats, seq, motivo):
    enviar(conn, f"NACK|{seq}|{motivo}")
    stats["nacks_enviados"] += 1
    print(f"[SERVIDOR] NACK enviado | SEQ={seq} | motivo={motivo}.")


def receber_go_back_n(conn, addr, tamanho_janela, total_pacotes, stats):
    payloads_confirmados = []
    base = 1

    while base <= total_pacotes:
        quantidade_esperada = min(tamanho_janela, total_pacotes - base + 1)
        ultimo_esperado = base + quantidade_esperada - 1
        tentativas_rejeitadas = 0

        while True:
            recebidos = []
            erros_frame = []
            marcador = None
            quantidade_recebida = 0
            print(
                f"[{addr}][SERVIDOR] Aguardando janela GBN SEQ {base}–{ultimo_esperado}."
            )

            while marcador is None:
                try:
                    raw = receber_com_timeout(
                        conn,
                        f"janela GBN iniciada em SEQ {base}",
                    )
                except TimeoutError:
                    stats["timeouts_receptor"] += 1
                    registrar_nack(conn, stats, base, "TIMEOUT")
                    if tentativas_rejeitadas >= MAX_RETRIES:
                        raise ProtocolError("Limite de retransmissões GBN atingido.")
                    tentativas_rejeitadas += 1
                    stats["retransmissoes_gbn"] += 1
                    marcador = "TIMEOUT"
                    break

                if raw.startswith("WINDOW_END|"):
                    try:
                        marcador = parsear_fim_janela(raw)
                    except ProtocolError:
                        erros_frame.append("WINDOW_BOUNDARY")
                        marcador = (-1, -1)
                    break

                quantidade_recebida += 1
                try:
                    seq, payload, checksum = parsear_pacote(raw)
                except FrameError as erro:
                    erros_frame.append(erro.reason)
                    stats["quadros_invalidos"] += 1
                    if erro.reason == "CHECKSUM":
                        stats["erros_crc"] += 1
                    print(
                        f"[{addr}][SERVIDOR] DATA rejeitado | "
                        f"SEQ={erro.seq or '?'} | motivo={erro.reason}."
                    )
                    continue

                print(
                    f"[{addr}][SERVIDOR] DATA validado | SEQ={seq} "
                    f"| texto={payload!r} | CHK={checksum} | CRC=OK | cifra=OK"
                )
                recebidos.append((seq, payload))

            if marcador == "TIMEOUT":
                continue

            motivo = None
            if marcador != (base, ultimo_esperado):
                motivo = "WINDOW_BOUNDARY"
            elif erros_frame:
                motivo = erros_frame[0]
            elif quantidade_recebida != quantidade_esperada:
                motivo = "SEQUENCE"
            elif [seq for seq, _ in recebidos] != list(
                range(base, ultimo_esperado + 1)
            ):
                motivo = "SEQUENCE"

            if motivo:
                registrar_nack(conn, stats, base, motivo)
                if tentativas_rejeitadas >= MAX_RETRIES:
                    raise ProtocolError(
                        f"Limite de retransmissões GBN atingido na base {base}."
                    )
                tentativas_rejeitadas += 1
                stats["retransmissoes_gbn"] += 1
                print(
                    f"[{addr}][SERVIDOR] Lote descartado por completo; "
                    f"aguardando reenvio desde SEQ={base}."
                )
                continue

            # Só incorpora a janela após validar todos os pacotes, evitando duplicatas.
            payloads_confirmados.extend(payload for _, payload in recebidos)
            enviar(conn, f"ACK|GBN|{ultimo_esperado}")
            stats["acks_enviados"] += 1
            stats["pacotes_aceitos"] += len(recebidos)
            print(
                f"[{addr}][SERVIDOR] ACK cumulativo enviado até SEQ="
                f"{ultimo_esperado}."
            )
            base = ultimo_esperado + 1
            break

    return "".join(payloads_confirmados)


def receber_repeticao_seletiva(
    conn, addr, tamanho_janela, total_pacotes, stats
):
    # O buffer mantém pacotes íntegros fora de ordem até preencher a lacuna.
    recebidos = {}
    base = 1
    tentativas_timeout = {}

    while base <= total_pacotes:
        try:
            raw = receber_com_timeout(
                conn,
                f"DATA da janela SR iniciada em SEQ {base}",
            )
        except TimeoutError:
            stats["timeouts_receptor"] += 1
            tentativas_timeout[base] = tentativas_timeout.get(base, 0) + 1
            registrar_nack(conn, stats, base, "TIMEOUT")
            if tentativas_timeout[base] > MAX_RETRIES:
                raise ProtocolError(f"Limite de timeout SR atingido na SEQ {base}.")
            continue

        try:
            seq, payload, checksum = parsear_pacote(raw)
        except FrameError as erro:
            stats["quadros_invalidos"] += 1
            if erro.reason == "CHECKSUM":
                stats["erros_crc"] += 1
            registrar_nack(conn, stats, erro.seq or base, erro.reason)
            continue

        if seq > total_pacotes:
            registrar_nack(conn, stats, seq, "WINDOW")
            continue

        if seq < base or seq in recebidos:
            stats["duplicatas"] += 1
            enviar(conn, f"ACK|SR|{seq}")
            stats["acks_enviados"] += 1
            print(f"[{addr}][SERVIDOR] DATA duplicado; re-ACK | SEQ={seq}.")
            continue

        if seq >= base + tamanho_janela:
            registrar_nack(conn, stats, seq, "WINDOW")
            continue

        if seq > base:
            stats["pacotes_fora_de_ordem"] += 1
            print(
                f"[{addr}][SERVIDOR] DATA fora de ordem | SEQ={seq}; "
                f"base ainda pendente={base}. Mantido no buffer."
            )

        recebidos[seq] = payload
        stats["pacotes_aceitos"] += 1
        print(
            f"[{addr}][SERVIDOR] DATA validado | SEQ={seq} "
            f"| texto={payload!r} | CHK={checksum} | CRC=OK | cifra=OK"
        )
        enviar(conn, f"ACK|SR|{seq}")
        stats["acks_enviados"] += 1
        print(f"[{addr}][SERVIDOR] ACK individual enviado para SEQ={seq}.")

        while base in recebidos:
            base += 1

    return "".join(recebidos[seq] for seq in range(1, total_pacotes + 1))


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


def receber_transferencia(conn, addr, operacao, tamanho_maximo, tamanho_janela, stats):
    inicio = receber_com_timeout(conn, "BEGIN da mensagem")
    try:
        total_caracteres, total_pacotes = parsear_begin(inicio, tamanho_maximo)
    except ProtocolError:
        enviar(conn, "ERROR|BEGIN")
        raise

    print(
        f"[{addr}][SERVIDOR] Transferência iniciada | caracteres={total_caracteres} "
        f"| pacotes={total_pacotes} | janela={tamanho_janela}."
    )
    if operacao == 1:
        texto = receber_go_back_n(
            conn, addr, tamanho_janela, total_pacotes, stats
        )
    else:
        texto = receber_repeticao_seletiva(
            conn, addr, tamanho_janela, total_pacotes, stats
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


def imprimir_resumo(addr, stats):
    print("\n" + "=" * 55)
    print(f"[SERVIDOR][{addr}] RESUMO DA SESSÃO")
    print("=" * 55)
    print(f"  Pacotes aceitos                : {stats['pacotes_aceitos']}")
    print(f"  CRCs inválidos                 : {stats['erros_crc']}")
    print(f"  Quadros inválidos              : {stats['quadros_invalidos']}")
    print(f"  Pacotes fora de ordem          : {stats['pacotes_fora_de_ordem']}")
    print(f"  Duplicatas recebidas           : {stats['duplicatas']}")
    print(f"  ACKs enviados                  : {stats['acks_enviados']}")
    print(f"  NACKs enviados                 : {stats['nacks_enviados']}")
    print(f"  Timeouts de recepção           : {stats['timeouts_receptor']}")
    print(f"  Repetições de janela GBN       : {stats['retransmissoes_gbn']}")
    print("=" * 55)


def handle_client(conn, addr):
    stats = {
        "pacotes_aceitos": 0,
        "erros_crc": 0,
        "quadros_invalidos": 0,
        "pacotes_fora_de_ordem": 0,
        "duplicatas": 0,
        "acks_enviados": 0,
        "nacks_enviados": 0,
        "timeouts_receptor": 0,
        "retransmissoes_gbn": 0,
    }
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
            conn, addr, operacao, tamanho_maximo, tamanho_janela, stats
        )

    except (ConnectionError, OSError, ProtocolError, TimeoutError, ValueError) as erro:
        print(f"\n[SERVIDOR][{addr}] Sessão encerrada: {erro}")
    finally:
        imprimir_resumo(addr, stats)
        _buffers.pop(conn, None)
        conn.close()
        print(f"[SERVIDOR] Conexão com {addr} encerrada.")


def start_server():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8", errors="replace", line_buffering=True
        )
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((SERVER_HOST, SERVER_PORT))
    server.listen(5)
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
