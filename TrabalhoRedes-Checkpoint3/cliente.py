import os
import socket
import sys
import time

from checksum import calcular_checksum_pacote
from cipher import cifrar


BLUE = "\033[34m"
RESET = "\033[0m"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
MAX_PAYLOAD_CHARS = 4
ACK_TIMEOUT_SECONDS = 5.0
MAX_RETRIES = 5

# TCP é um fluxo de bytes. O buffer mantém frames completos e parciais por socket.
_buffers = {}


class ProtocolError(Exception):
    """Indica que uma mensagem recebida não segue o protocolo da aplicação."""


def receber(client):
    buffer = _buffers.get(client, b"")
    while b"\0" not in buffer:
        try:
            dados = client.recv(1024)
        except Exception:
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
    payload_hex = cifrar(payload).hex()
    checksum = calcular_checksum_pacote(seq, payload_hex)
    return f"SEQ:{seq}|DATA:{payload_hex}|CHK:{checksum}"


def corromper_pacote(pacote):
    """Altera um dígito hexadecimal de DATA depois do cálculo do CRC."""
    partes = pacote.split("|")
    dados_hex = partes[1][5:]
    if not dados_hex:
        raise ProtocolError("Não é possível corromper um DATA vazio.")
    alfabeto = "0123456789abcdef"
    indice = alfabeto.index(dados_hex[0])
    dados_corrompidos = alfabeto[(indice + 1) % len(alfabeto)] + dados_hex[1:]
    partes[1] = f"DATA:{dados_corrompidos}"
    return "|".join(partes)


def dividir_mensagem(mensagem):
    return [
        mensagem[inicio:inicio + MAX_PAYLOAD_CHARS]
        for inicio in range(0, len(mensagem), MAX_PAYLOAD_CHARS)
    ]


def ler_sequencias_falha(rotulo, total_pacotes):
    bruto = input(
        f"SEQ a {rotulo} (separe vários números por vírgula; ENTER = nenhuma): "
    ).strip()
    if not bruto:
        return set()
    try:
        sequencias = {int(item.strip()) for item in bruto.split(",")}
    except ValueError as erro:
        raise ValueError("Informe apenas números de sequência separados por vírgula.") from erro
    if any(seq < 1 or seq > total_pacotes for seq in sequencias):
        raise ValueError(f"As sequências devem estar entre 1 e {total_pacotes}.")
    return sequencias


def configurar_falhas(total_pacotes):
    while True:
        resposta = input("Simular corrupção ou perda de DATA? [s/N]: ").strip().lower()
        if resposta in ("", "n", "nao", "não"):
            return {"corromper": set(), "perder": set(), "injetadas": set()}
        if resposta not in ("s", "sim"):
            print("[CLIENTE] Responda s ou n.")
            continue
        try:
            corromper = ler_sequencias_falha("corromper", total_pacotes)
            perder = ler_sequencias_falha("perder", total_pacotes)
        except ValueError as erro:
            print(f"[CLIENTE] {erro}")
            continue
        conflito = corromper & perder
        if conflito:
            print(
                "[CLIENTE] Uma sequência não pode receber corrupção e perda "
                f"na mesma execução: {sorted(conflito)}."
            )
            continue
        return {"corromper": corromper, "perder": perder, "injetadas": set()}


def enviar_pacote(client, seq, payload, falhas, stats):
    pacote = montar_pacote(seq, payload)
    if seq in falhas["perder"] and seq not in falhas["injetadas"]:
        falhas["injetadas"].add(seq)
        stats["perdidos_simulados"] += 1
        print(f"[simulação][CLIENTE] DATA SEQ={seq} perdido; não enviado nesta tentativa.")
        return time.monotonic()

    if seq in falhas["corromper"] and seq not in falhas["injetadas"]:
        falhas["injetadas"].add(seq)
        stats["corrompidos_simulados"] += 1
        pacote = corromper_pacote(pacote)
        print(
            f"[simulação][CLIENTE] DATA SEQ={seq} corrompido após o CRC; "
            "o servidor deve rejeitá-lo."
        )
    else:
        print(f"[CLIENTE] DATA preparado | SEQ={seq} | payload={payload!r} cifrado.")

    enviar(pacote, client)
    stats["pacotes_transmitidos"] += 1
    return time.monotonic()


def parsear_nack(mensagem):
    partes = mensagem.split("|")
    if (
        len(partes) != 3
        or partes[0] != "NACK"
        or not partes[1].isascii()
        or not partes[1].isdigit()
        or not partes[2]
    ):
        raise ProtocolError(f"NACK inválido: {mensagem}")
    return int(partes[1]), partes[2]


def validar_ack_gbn(mensagem, ultimo_esperado):
    partes = mensagem.split("|")
    if (
        len(partes) != 3
        or partes[0] != "ACK"
        or partes[1] != "GBN"
        or not partes[2].isascii()
        or not partes[2].isdigit()
    ):
        raise ProtocolError(f"ACK Go-Back-N inválido: {mensagem}")
    if int(partes[2]) != ultimo_esperado:
        raise ProtocolError(
            f"ACK cumulativo até {partes[2]}; esperado {ultimo_esperado}."
        )


def registrar_retransmissao(tentativas, contexto):
    if tentativas >= MAX_RETRIES:
        raise ProtocolError(f"Limite de {MAX_RETRIES} retransmissões atingido ({contexto}).")
    return tentativas + 1


def enviar_go_back_n(client, pacotes, tamanho_janela, falhas, stats):
    inicio = 0
    while inicio < len(pacotes):
        base = inicio + 1
        fim_indice = min(inicio + tamanho_janela, len(pacotes))
        ultimo = fim_indice
        tentativas = 0

        while True:
            if tentativas:
                print(
                    f"[CLIENTE] Reenviando a janela completa SEQ {base} a {ultimo} "
                    f"(tentativa {tentativas})."
                )
            else:
                print(f"\n[CLIENTE] Enviando janela Go-Back-N: SEQ {base} a {ultimo}.")

            for indice in range(inicio, fim_indice):
                seq = indice + 1
                enviar_pacote(client, seq, pacotes[indice], falhas, stats)
            enviar(f"WINDOW_END|{base}|{ultimo}", client)

            try:
                resposta = receber_com_timeout(
                    client, f"ACK cumulativo até SEQ {ultimo}"
                )
            except TimeoutError:
                stats["timeouts"] += 1
                stats["retransmissoes_timeout"] += 1
                print(f"[CLIENTE] Timeout da janela iniciada em SEQ={base}.")
                tentativas = registrar_retransmissao(
                    tentativas, f"janela iniciada em SEQ {base}"
                )
                continue

            if resposta.startswith("NACK|"):
                seq, motivo = parsear_nack(resposta)
                if seq != base:
                    raise ProtocolError(
                        f"NACK de GBN para SEQ {seq}; a base pendente é {base}."
                    )
                stats["nacks"] += 1
                stats["retransmissoes_nack"] += 1
                print(f"[CLIENTE] NACK da janela | base={seq} | motivo={motivo}.")
                tentativas = registrar_retransmissao(
                    tentativas, f"janela iniciada em SEQ {base}"
                )
                continue

            validar_ack_gbn(resposta, ultimo)
            stats["acks"] += 1
            print(f"[CLIENTE] ACK cumulativo recebido | até SEQ={ultimo}.")
            inicio = fim_indice
            break


def enviar_repeticao_seletiva(client, pacotes, tamanho_janela, falhas, stats):
    total = len(pacotes)
    proxima_sequencia = 1
    base = 1
    pendentes = {}
    confirmados = set()
    tentativas = {}

    while base <= total:
        while (
            proxima_sequencia <= total
            and proxima_sequencia < base + tamanho_janela
        ):
            seq = proxima_sequencia
            enviado_em = enviar_pacote(
                client, seq, pacotes[seq - 1], falhas, stats
            )
            pendentes[seq] = enviado_em
            proxima_sequencia += 1

        seq_temporizador = min(pendentes, key=pendentes.get)
        restante = (
            pendentes[seq_temporizador]
            + ACK_TIMEOUT_SECONDS
            - time.monotonic()
        )
        if restante <= 0:
            resposta = None
        else:
            try:
                resposta = receber_com_timeout(
                    client,
                    f"ACK/NACK SR; mais antigo pendente SEQ {seq_temporizador}",
                    restante,
                )
            except TimeoutError:
                resposta = None

        if resposta is None:
            agora = time.monotonic()
            expirados = [
                seq for seq, instante in pendentes.items()
                if agora - instante >= ACK_TIMEOUT_SECONDS
            ]
            if not expirados:
                expirados = [seq_temporizador]
            for seq in expirados:
                tentativas[seq] = registrar_retransmissao(
                    tentativas.get(seq, 0), f"SEQ {seq}"
                )
                stats["timeouts"] += 1
                stats["retransmissoes_timeout"] += 1
                print(f"[CLIENTE] Timeout individual | SEQ={seq}; reenviando só este DATA.")
                pendentes[seq] = enviar_pacote(
                    client, seq, pacotes[seq - 1], falhas, stats
                )
            continue

        if resposta.startswith("NACK|"):
            seq, motivo = parsear_nack(resposta)
            stats["nacks"] += 1
            print(f"[CLIENTE] NACK individual | SEQ={seq} | motivo={motivo}.")
            if seq in confirmados:
                print(f"[CLIENTE] NACK tardio ignorado para SEQ já confirmado={seq}.")
                continue
            if seq not in pendentes:
                raise ProtocolError(f"NACK de SEQ {seq} não corresponde a pacote pendente.")
            tentativas[seq] = registrar_retransmissao(
                tentativas.get(seq, 0), f"SEQ {seq}"
            )
            stats["retransmissoes_nack"] += 1
            pendentes[seq] = enviar_pacote(
                client, seq, pacotes[seq - 1], falhas, stats
            )
            continue

        partes = resposta.split("|")
        if (
            len(partes) != 3
            or partes[0] != "ACK"
            or partes[1] != "SR"
            or not partes[2].isascii()
            or not partes[2].isdigit()
        ):
            raise ProtocolError(f"ACK inesperado na Repetição Seletiva: {resposta}")

        seq_confirmada = int(partes[2])
        if seq_confirmada in confirmados:
            print(f"[CLIENTE] ACK duplicado ignorado | SEQ={seq_confirmada}.")
            continue
        if seq_confirmada not in pendentes:
            raise ProtocolError(
                f"ACK de SEQ {seq_confirmada} não corresponde a pacote pendente."
            )

        del pendentes[seq_confirmada]
        confirmados.add(seq_confirmada)
        stats["acks"] += 1
        print(f"[CLIENTE] ACK individual recebido | SEQ={seq_confirmada}.")
        while base <= total and base in confirmados:
            base += 1


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
        f"caracteres={total_caracteres} | pacotes={total_pacotes}."
    )


def negociar_handshake(client):
    while True:
        operacao = receber(client)
        print(operacao, end="")
        operacao_escolhida = input("-> ").strip()
        enviar(operacao_escolhida, client)

        validacao = receber(client)
        if validacao == "True":
            break
        print(validacao, end="")

    print(receber(client), end="")
    while True:
        bruto = input("-> ").strip()
        try:
            tamanho_maximo = int(bruto)
            if tamanho_maximo >= 30:
                break
            print("[CLIENTE] O limite deve ter pelo menos 30 caracteres.")
        except ValueError:
            print("[CLIENTE] Digite um inteiro válido.")

    enviar(str(tamanho_maximo), client)
    print(receber(client), end="")
    tamanho_janela = int(receber(client))
    resposta = receber(client)
    print(resposta, end="")
    if not resposta.startswith("[SERVIDOR]Tamanho aceito"):
        raise ProtocolError("O servidor recusou os parâmetros do handshake.")

    print(
        f"\n[CLIENTE] Handshake concluído | modo={operacao_escolhida} "
        f"| máximo={tamanho_maximo} | janela={tamanho_janela}."
    )
    return operacao_escolhida, tamanho_maximo, tamanho_janela


def imprimir_resumo(stats, total_pacotes):
    print("\n" + "=" * 55)
    print("[CLIENTE] RESUMO DA SESSÃO")
    print("=" * 55)
    print(f"  Pacotes da mensagem            : {total_pacotes}")
    print(f"  DATA transmitidos              : {stats['pacotes_transmitidos']}")
    print(f"  ACKs recebidos                 : {stats['acks']}")
    print(f"  NACKs recebidos                : {stats['nacks']}")
    print(f"  Timeouts do emissor            : {stats['timeouts']}")
    print(f"  Retransmissões após NACK       : {stats['retransmissoes_nack']}")
    print(f"  Retransmissões após timeout    : {stats['retransmissoes_timeout']}")
    print(f"  Corrupções injetadas           : {stats['corrompidos_simulados']}")
    print(f"  Perdas injetadas               : {stats['perdidos_simulados']}")
    print("=" * 55)


def iniciar_cliente():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if not sys.stdin.isatty() and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if sys.stdin.isatty():
        os.system("cls" if os.name == "nt" else "clear")
    print(BLUE + "CLIENTE — Checkpoint 3: erros, perdas e recuperação" + RESET)

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stats = {
        "pacotes_transmitidos": 0,
        "acks": 0,
        "nacks": 0,
        "timeouts": 0,
        "retransmissoes_nack": 0,
        "retransmissoes_timeout": 0,
        "corrompidos_simulados": 0,
        "perdidos_simulados": 0,
    }
    total_pacotes = 0

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
        falhas = configurar_falhas(total_pacotes)
        enviar(f"BEGIN|{tamanho_real}|{total_pacotes}", client)
        print(
            f"\n[CLIENTE] Transferência iniciada | caracteres={tamanho_real} "
            f"| pacotes={total_pacotes} | payload máximo={MAX_PAYLOAD_CHARS}."
        )

        if modo == "1":
            enviar_go_back_n(client, pacotes, tamanho_janela, falhas, stats)
        else:
            enviar_repeticao_seletiva(
                client, pacotes, tamanho_janela, falhas, stats
            )
        receber_conclusao(client, tamanho_real, total_pacotes)

    except (ConnectionError, OSError, ProtocolError, TimeoutError, ValueError, EOFError) as erro:
        print(f"\n[CLIENTE] Sessão encerrada: {erro}")
    finally:
        if total_pacotes:
            imprimir_resumo(stats, total_pacotes)
        _buffers.pop(client, None)
        client.close()


if __name__ == "__main__":
    iniciar_cliente()
