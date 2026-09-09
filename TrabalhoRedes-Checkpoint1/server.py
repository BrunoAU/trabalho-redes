import socket, os, threading

YELLOW = "\033[33m"
RESET = "\033[0m"

# "0.0.0.0" aceita conexões pelo loopback e pelos IPv4s da máquina.
# O cliente deve usar 127.0.0.1 localmente ou o IPv4 desta máquina pela rede.
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080

#Buffer por conexao, usado por receber() para remontar mensagens que cheguem
#fragmentadas ou coladas em um mesmo recv() (TCP e um fluxo de bytes, nao
#preserva fronteiras de mensagem). Cada mensagem enviada por enviar() termina
#com um byte nulo (\0); receber() só devolve o texto quando encontra esse
#delimitador no buffer acumulado.
_buffers = {}

def enviar(mensagem, conn):
    conn.sendall(mensagem.encode() + b"\0")

def receber(conn):
    buf = _buffers.get(conn, b"")
    while b"\0" not in buf:
        dados = conn.recv(1024)
        if not dados:
            raise ConnectionError("Conexão encerrada pelo cliente.")
        buf += dados
    mensagem, resto = buf.split(b"\0", 1)
    _buffers[conn] = resto
    return mensagem.decode()

def limpar_tela():
    os.system("cls" if os.name == "nt" else "clear")

def cabecalho():
    servidor = r"""
███████╗███████╗██████╗ ██╗   ██╗██╗██████╗  ██████╗ ██████╗ 
██╔════╝██╔════╝██╔══██╗██║   ██║██║██╔══██╗██╔═══██╗██╔══██╗
███████╗█████╗  ██████╔╝██║   ██║██║██║  ██║██║   ██║██████╔╝
╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██║██║  ██║██║   ██║██╔══██╗
███████║███████╗██║  ██║ ╚████╔╝ ██║██████╔╝╚██████╔╝██║  ██║
╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝
"""
    print(YELLOW + servidor + RESET)

def print_asc():
    limpar_tela()
    cabecalho()

#Lida com a conexão de um cliente em uma thread separada
def handle_client(conn, addr):
    print(f"\n[SERVIDOR] Nova conexão de {addr}")
    

    try:
        while True:
            modo_operacao = (
                "[SERVIDOR]Escolha o modo de operação\n"
                "[1] Envio em lote / Go-Back-N\n"
                "[2] Envio individual / Repetição Seletiva\n"
            )
            enviar(modo_operacao, conn)
            operacao_escolhida = receber(conn)
            if operacao_escolhida == "1":
                operacao = 1
                enviar("True", conn)
                print(f"[{addr}][CLIENTE]Modo escolhido: envio em lote / Go-Back-N\n")
                break
            elif operacao_escolhida == "2":
                operacao = 2
                enviar("True", conn)
                print(f"[{addr}][CLIENTE]Modo escolhido: envio individual / Repetição Seletiva\n")
                break
            else:
                enviar("[SERVIDOR]Erro! Opção inválida! Repetindo operação...\n", conn)
                print(f"[{addr}][SERVIDOR]Opção inválida. Aguardando nova resposta...")
                continue

        enviar("[SERVIDOR]Qual o tamanho máximo de string que você deseja enviar? (Mínimo é 30.)\n", conn)
        tamanho_mensagem = int(receber(conn))

        print(f"[{addr}][SERVIDOR]Cliente quer enviar uma string de tamanho {tamanho_mensagem}.\n")

        while True:
            bruto_janela = input(f"[SERVIDOR][{addr}]Escolha o tamanho da janela (1 a 5) [ENTER = 5]: ").strip()
            if bruto_janela == "":
                tamanho_janela_inicial = 5
                break
            try:
                tamanho_janela_inicial = int(bruto_janela)
                if 1 <= tamanho_janela_inicial <= 5:
                    break
                print("[SERVIDOR]Valor inválido! Digite um número entre 1 e 5.")
            except ValueError:
                print("[SERVIDOR]Entrada inválida! Digite um número inteiro.")

        enviar(f"[SERVIDOR]Janela atual: {tamanho_janela_inicial} pacotes.\n", conn)
        enviar(str(tamanho_janela_inicial), conn)

        if tamanho_mensagem < 30:
            enviar(f"[SERVIDOR]NEGADO: Tamanho {tamanho_mensagem} é menor que o mínimo de 30.", conn)
            print(f"[{addr}][SERVIDOR]Conexão recusada por tamanho insuficiente.")
        else:
            enviar("[SERVIDOR]Tamanho aceito! Handshake concluído.\n", conn)
            print(f"[{addr}][SERVIDOR]Tamanho validado. Handshake concluído.\n")
            nome_op = "Go-Back-N" if operacao == 1 else "Repetição Seletiva"
            print(f"[{addr}][SERVIDOR]Modo negociado: {nome_op} | Tamanho: {tamanho_mensagem} | Janela: {tamanho_janela_inicial}\n")
            #Checkpoint 1 termina aqui: modo, tamanho e janela negociados.
            #O recebimento efetivo dos pacotes da mensagem fragmentada fica
            #para os Checkpoints 2 e 3.

    except Exception as e:
        print(f"\n[SERVIDOR][{addr}] Erro ou conexão encerrada: {e}")
    finally:
        conn.close()
        print(f"[SERVIDOR] Conexão com {addr} encerrada.")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((SERVER_HOST, SERVER_PORT))
    server.listen(5)
    print_asc()
    print(
        f"[SERVIDOR] Aguardando conexões em {SERVER_HOST}:{SERVER_PORT} "
        "(Ctrl+C para encerrar)...\n"
    )

    #Loop principal: aceita clientes continuamente, cada um em uma thread separada
    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[SERVIDOR] Encerrado pelo usuário.")
    finally:
        server.close()

if __name__ == "__main__":
    start_server()
