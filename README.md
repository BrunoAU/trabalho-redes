# Trabalho I — Infraestrutura de Comunicação 2026.2

Projeto incremental de cliente-servidor via sockets TCP para os checkpoints da disciplina.

## Entregas

- [Checkpoint 1 — Handshake e Sockets](TrabalhoRedes-Checkpoint1/README.md): conexão TCP e negociação de modo, limite da mensagem e janela.
- [Checkpoint 2 — Protocolo sem erros](TrabalhoRedes-Checkpoint2/README.md): transferência fragmentada, CRC-16 manual, Go-Back-N e Repetição Seletiva.
- [Checkpoint 3 — Erros, perdas e recuperação](TrabalhoRedes-Checkpoint3/README.md): simulador determinístico, recuperação GBN/SR e cifra simétrica manual.

As pastas CP1 e CP2 permanecem preservadas como entregas concluídas. A pasta CP3 reúne o código e os documentos de uso, validação e especificação incremental do protocolo.

## Executar o Checkpoint 3

Requisito: Python 3. Não há dependências externas.

Em um terminal:

```bash
cd TrabalhoRedes-Checkpoint3
python server.py
```

Em outro terminal, na mesma pasta:

```bash
python cliente.py
```

O roteiro de testes e o relatório incremental, incluindo o registro dos prompts principais, estão na pasta do CP3.

O relatório em PDF está disponível em [`TrabalhoRedes-Checkpoint3/output/pdf/RELATORIO_CHECKPOINT_3.pdf`](TrabalhoRedes-Checkpoint3/output/pdf/RELATORIO_CHECKPOINT_3.pdf).

## Executar o Checkpoint 2

Requisito: Python 3. Não há dependências externas.

Em um terminal:

```bash
cd TrabalhoRedes-Checkpoint2
python server.py
```

Em outro terminal, na mesma pasta:

```bash
python cliente.py
```

O cliente escolhe o modo de operação e informa o limite máximo de caracteres. O servidor define a janela entre 1 e 5 pacotes; ENTER seleciona o padrão 5.

## Escopo incremental

O CP2 executa o caminho de transferência sem perdas ou corrupção, verifica os quadros recebidos, confirma pacotes e remonta a mensagem. O relatório CP2 descreve o protocolo completo e identifica a simulação e a recuperação por retransmissão como evolução do CP3.
