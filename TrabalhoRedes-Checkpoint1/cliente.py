import socket, os

BLUE = "\033[34m"
RESET = "\033[0m"

# Para uso local, mantenha "127.0.0.1". Para outra máquina, troque pelo IPv4
# do computador que está executando server.py.
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080

#Buffer por conexao, usado por receber() para remontar mensagens que cheguem
#fragmentadas ou coladas em um mesmo recv() (TCP e um fluxo de bytes, nao
#preserva fronteiras de mensagem). Cada mensagem enviada por enviar() termina
#com um byte nulo (\0); receber() só devolve o texto quando encontra esse
#delimitador no buffer acumulado.
_buffers = {}

def receber(client):
    buf = _buffers.get(client, b"")
    while b"\0" not in buf:
        dados = client.recv(1024)
        if not dados:
            raise ConnectionError("Conexão encerrada pelo servidor.")
        buf += dados
    mensagem, resto = buf.split(b"\0", 1)
    _buffers[client] = resto
    return mensagem.decode()

def enviar(mensagem, client):
    client.sendall(mensagem.encode() + b"\0")

def limparTerminal():
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

def start_client():
    limparTerminal()
    cabecalho()
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client.connect((SERVER_HOST, SERVER_PORT))

        operacao_escolhida = None
        while True:
            operacao = receber(client)
            print(operacao, end="")

            operacao_escolhida = input("-> ")
            enviar(operacao_escolhida, client)

            validacao = receber(client)
            if validacao == "True":
                break
            else:
                print(validacao, end="")
                continue

        tamanho_str = receber(client)
        print(tamanho_str, end="")

        #Valida se o tamanho informado pelo usuario atende o minimo exigido
        while True:
            tamanho_mensagem_raw = input("-> ").strip()
            try:
                tamanho_mensagem_int = int(tamanho_mensagem_raw)
                if tamanho_mensagem_int >= 30:
                    break
                print("[CLIENTE]Valor inválido! O tamanho mínimo é 30 caracteres. Tente novamente.")
            except ValueError:
                print("[CLIENTE]Entrada inválida! Digite um número inteiro.")

        tamanho_mensagem = tamanho_mensagem_raw
        print(f"Informando tamanho ({tamanho_mensagem}) ao servidor...")
        enviar(tamanho_mensagem, client)

        aviso_janela = receber(client)
        print(aviso_janela, end="")

        tamanho_janela = int(receber(client))

        resposta = receber(client)
        print(resposta, end="")

        if "Tamanho aceito" in resposta:

            #Checkpoint 1 termina aqui: handshake concluído (modo, tamanho e
            #janela negociados). O envio efetivo da mensagem fragmentada em
            #pacotes fica para os Checkpoints 2 e 3.
            print("\n" + "="*55)
            print("[CLIENTE] HANDSHAKE CONCLUÍDO")
            print("="*55)
            nome_modo = (
                "envio em lote / Go-Back-N"
                if operacao_escolhida == "1"
                else "envio individual / Repetição Seletiva"
            )
            print(f"  Modo de operação  : {nome_modo}")
            print(f"  Tamanho máximo    : {tamanho_mensagem_int} caracteres")
            print(f"  Tamanho da janela : {tamanho_janela}")
            print("="*55 + "\n")
        else:
            print("[CLIENTE] Conexão encerrada pelo servidor (tamanho recusado).")

    except Exception as e:
        print(f"Erro: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    start_client()
