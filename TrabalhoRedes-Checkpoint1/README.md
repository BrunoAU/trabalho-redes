# Checkpoint 1 — Handshake & Sockets

Projeto desenvolvido para a cadeira de **Infraestrutura de Comunicação** (2026.2). Esta entrega corresponde exclusivamente ao **Checkpoint 1**: conexão cliente-servidor via socket TCP e handshake inicial para negociação dos parâmetros da sessão.

> Este projeto reutiliza uma base de código já existente, desenvolvida anteriormente e com funcionalidades além deste checkpoint. A versão aqui entregue foi **reduzida deliberadamente** para conter apenas o que o Checkpoint 1 exige. Veja [Relatório](https://docs.google.com/document/d/1EukpXQcnZxK4Vk5nCOrnK_voOs9IQoYS2vKXrBV6i88/edit?usp=sharing) para o processo completo.

## Objetivo do checkpoint

Demonstrar que cliente e servidor conseguem:

1. Estabelecer uma conexão via socket TCP;
2. Executar um handshake inicial que negocia:
   - o **modo de operação** que será usado para o envio de mensagens em checkpoints futuros;
   - o **tamanho máximo do texto inicial** que o cliente poderá enviar;
   - o **tamanho da janela** de recepção, definido pelo servidor;
3. Confirmar o sucesso do handshake e encerrar a sessão de forma limpa.

Este checkpoint **não troca a mensagem em si** — apenas negocia os parâmetros que serão usados para isso depois.

## Arquitetura cliente-servidor

- **Servidor** (`server.py`): abre um socket TCP, faz `bind`/`listen`/`accept` e conduz o handshake com cada cliente em uma thread separada (`threading`, como no código original), permitindo múltiplos clientes conectados ao mesmo tempo. Depois de concluir (ou recusar) o handshake de um cliente, encerra a conexão daquele cliente; o servidor continua aceitando outras conexões.
- **Cliente** (`cliente.py`): abre um socket TCP, conecta ao servidor e segue o roteiro do handshake, respondendo às solicitações do servidor.

A comunicação usa **socket TCP** (`AF_INET` + `SOCK_STREAM`).

## Endereço e porta

- Servidor: `SERVER_HOST = "0.0.0.0"` e `SERVER_PORT = 8080` em `server.py`;
- Cliente: `SERVER_HOST = "127.0.0.1"` e `SERVER_PORT = 8080` em `cliente.py`.

O servidor usa `0.0.0.0` para escutar tanto conexões locais quanto conexões recebidas pelos IPv4s da máquina. A configuração é hardcoded, como permitido pela especificação.

Para executar na mesma máquina, mantenha `SERVER_HOST = "127.0.0.1"` no `cliente.py` e rode os dois programas conforme a seção seguinte. Para conectar máquinas diferentes, descubra o IPv4 do computador que executa `server.py` e substitua somente `SERVER_HOST` no `cliente.py` por esse endereço, por exemplo `SERVER_HOST = "192.168.1.50"`. Mantenha a porta igual nos dois arquivos e libere a porta `8080` no firewall do computador servidor, se necessário. Não há descoberta automática de IP.

## Como executar

### 1. Servidor

```bash
python server.py
```

O servidor ficará aguardando conexões na porta `8080`, pelo loopback e pelos IPv4s da máquina. Para cada cliente conectado, o operador do servidor será solicitado a informar o tamanho da janela diretamente no terminal.

### 2. Cliente

Em outro terminal:

```bash
python cliente.py
```

Siga as instruções exibidas: escolha o modo de operação e informe o tamanho máximo do texto inicial.

Nenhuma dependência externa é necessária — apenas a biblioteca padrão do Python (`socket`).

## Funcionamento do handshake

O handshake é o mesmo já existente na implementação anterior do grupo, apenas com o envio efetivo da mensagem removido. Segue esta sequência:

```
CLIENTE                                        SERVIDOR
   |                                               |
   |----------------- connect() ----------------->|  (accept())
   |<---- "Escolha o método da operação..." ------|
   |----------------- "1" ou "2" ----------------->|  valida modo (senão repete)
   |<---- "True" -----------------------------------|
   |                                               |
   |<---- "Qual o tamanho máximo...(mín. 30)" -----|
   |----------------- "<n>" ----------------------->|
   |<---- "Janela atual: <n> pacotes." -------------|  (definida pelo servidor)
   |<---- "<n>" (tamanho da janela) ----------------|
   |<---- "Tamanho aceito! Handshake concluído." ---|  ou "NEGADO: ..." se < 30
   |                                               |
   |----------------- encerra conexão ------------->|  encerra conexão
```

O fluxo preserva a ordem do código original (`modo_operacao`, `"Qual o tamanho máximo..."`, `"Janela atual: ..."`), mas a confirmação final foi ajustada para `"Tamanho aceito! Handshake concluído."`, pois esta entrega encerra após negociar os parâmetros. Fragmentação e envio da mensagem pertencem aos Checkpoints 2 e 3.

### Fragilidade encontrada e corrigida: delimitação das mensagens

O código original usava `enviar()`/`receber()` chamando `send()`/`recv(1024)` diretamente, sem nenhum delimitador — supondo implicitamente que cada `send()` chegaria como exatamente um `recv()`. Isso é uma suposição incorreta sobre TCP: TCP entrega um **fluxo de bytes**, não mensagens, e não garante essa correspondência 1:1.

**Correção aplicada (mínima):** cada mensagem passou a ser enviada com `sendall()` e a terminar com um **byte nulo (`\0`)**. Do lado de quem recebe, `receber()` acumula os bytes que chegam em um buffer (um dicionário `_buffers`, indexado pela própria conexão) e só devolve o texto ao chamador quando encontra o `\0` no buffer, não importa quantas chamadas de `recv()` isso exija.

**Por que `\0` em vez de `\n`?** Porque várias mensagens do protocolo contêm quebras de linha internas — por exemplo, o menu de modo possui uma linha para cada opção, mas é uma única mensagem de aplicação. Se usássemos `\n` como delimitador de mensagem, esse menu seria cortado na primeira quebra de linha e o restante apareceria fora de ordem. O `\0` (byte nulo) não aparece em nenhum texto normal da aplicação, então delimita as mensagens sem alterar seu conteúdo exibido ao usuário.

Essa foi a única mudança estrutural feita no código de troca de mensagens. Uma segunda mudança pontual: a confirmação final do tamanho, que no original chamava `conn.send()` diretamente, passou a usar `enviar()` para também receber o delimitador `\0` e poder ser lida corretamente pelo cliente. Nesta versão, seu texto confirma o término do handshake, sem solicitar o envio da string.

### Janela inicial = 5 por padrão

O código original pedia ao operador do servidor um número de 1 a 5 sem nenhum valor padrão — era preciso digitar algo sempre. Isso não impunha o "valor inicial de 5" exigido pela especificação: se o operador digitasse `3`, a sessão simplesmente começava com janela 3. Ajuste aplicado: pressionar ENTER sem digitar nada agora assume `5` (`[SERVIDOR][...]Escolha o tamanho da janela (1 a 5) [ENTER = 5]:`); digitar um valor de 1 a 5 continua funcionando normalmente para testar outros tamanhos.

## Parâmetros negociados e seus significados

| Parâmetro | Quem escolhe | Faixa válida | Significado |
|---|---|---|---|
| **Modo de operação** | Cliente (servidor valida) | `1` = envio em lote / Go-Back-N; `2` = envio individual / Repetição Seletiva | Define a estratégia de confirmação de pacotes dos **próximos** checkpoints: no Go-Back-N a janela/lote é reenviado quando necessário; na Repetição Seletiva, somente o pacote afetado é reenviado. Neste checkpoint, o modo é apenas negociado — nada é transmitido de fato. |
| **Tamanho máximo do texto inicial** | Cliente (servidor valida) | inteiro ≥ 30 (mínimo/default = 30) | Tamanho máximo, em caracteres, do texto que o cliente poderá enviar como mensagem completa em checkpoints futuros. |
| **Tamanho da janela** | Servidor | inteiro de 1 a 5 (valor inicial = 5) | Quantidade de pacotes que poderão ser enviados/confirmados por vez quando a transmissão real for implementada. A especificação determina que a janela é escolhida pelo servidor e começa com valor 5, podendo variar entre 1 e 5. |

## Limitações desta versão

Esta entrega **termina após o handshake**. Propositalmente, **não estão implementados nesta versão**:

- envio ou fragmentação da mensagem de texto em pacotes;
- checksum ou qualquer verificação de integridade;
- criptografia;
- números de sequência, ACK ou NACK;
- retransmissões ou timeouts de recuperação de perdas;
- simulação de corrupção ou perda de pacotes;
- execução efetiva de Go-Back-N ou Repetição Seletiva (apenas o modo é negociado e guardado — a lógica de envio/confirmação em si ainda não roda);
- estatísticas de transmissão.

Essas funcionalidades pertencem aos **Checkpoint 2** (troca de mensagens sem erros, protocolo completo) e **Checkpoint 3** (inserção efetiva de erros e perdas), e serão adicionadas nas próximas entregas.

## Estrutura

```
TrabalhoRedes-Checkpoint1/
├── cliente.py
├── server.py
├── README.md
├── EXEMPLO_TESTE.md
└── RELATORIO_CHECKPOINT_1.md
```

## Relatório de processo e IA

Ver [Relatório](https://docs.google.com/document/d/1EukpXQcnZxK4Vk5nCOrnK_voOs9IQoYS2vKXrBV6i88/edit?usp=sharing), seção "Processo de construção e uso de IA".
