# Checkpoint 2 — Protocolo sem erros

Esta pasta contém a evolução do projeto para o Checkpoint 2. A entrega de Checkpoint 1 está preservada em [`../TrabalhoRedes-Checkpoint1/`](../TrabalhoRedes-Checkpoint1/). A aplicação continua o handshake já negociado e transfere uma mensagem textual por conexão TCP.

## Escopo implementado

- Handshake que negocia o modo, o limite máximo da mensagem e a janela definida pelo servidor;
- Mensagem não vazia, limitada ao tamanho negociado, com configuração mínima de 30 caracteres;
- Fragmentos de até quatro pontos de código Unicode, codificados em UTF-8;
- CRC-16/IBM-3740 manual em cada pacote DATA, calculado sobre sequência e campo DATA;
- Go-Back-N com lotes e ACK cumulativo;
- Repetição Seletiva com janela deslizante e ACK individual;
- Remontagem e impressão da mensagem completa no servidor.

O caminho de transferência executado no CP2 não simula perdas ou corrupção. O receptor detecta quadros inválidos e pode responder NACK, mas a sessão termina sem retransmissão. As regras completas do protocolo, incluindo recuperação, estão definidas no [relatório](RELATORIO_CHECKPOINT_2.md); o simulador e a recuperação funcional ficam para CP3.

## Execução

Requisito: Python 3. Não há dependências externas. Abra dois terminais nesta pasta.

No primeiro:

```bash
python server.py
```

No segundo:

```bash
python cliente.py
```

No cliente, escolha Go-Back-N ou Repetição Seletiva e informe o limite máximo da mensagem. No terminal do servidor, pressione ENTER para aceitar a janela padrão 5 ou digite um valor de 1 a 5. Depois, envie uma mensagem não vazia dentro do limite negociado.

Para conectar a outra máquina, ajuste `SERVER_HOST` em `cliente.py` para o IPv4 do servidor e permita conexões TCP na porta 8080.

## Formato das mensagens

As mensagens de aplicação terminam em NUL (`\0`). O protocolo usa `sendall()` e buffers por conexão para delimitar quadros sobre o fluxo TCP.

| Mensagem | Formato | Uso |
|---|---|---|
| Início | `BEGIN|<caracteres>|<pacotes>` | Declara o tamanho da mensagem e a quantidade de fragmentos |
| DATA | `SEQ:<n>|DATA:<hex_utf8>|CHK:<crc16>` | Envia até quatro caracteres codificados em UTF-8 e seu CRC |
| Fim de lote GBN | `WINDOW_END|<base>|<último>` | Delimita o lote antes do ACK cumulativo |
| ACK GBN | `ACK|GBN|<último_seq>` | Confirma cumulativamente o lote recebido |
| ACK SR | `ACK|SR|<seq>` | Confirma um pacote específico |
| NACK | `NACK|<seq>|<motivo>` | Informa sequência e motivo da rejeição |
| Conclusão | `COMPLETE|<caracteres>|<pacotes>` | Confirma a remontagem da mensagem |

O CRC é calculado sobre os bytes ASCII de `SEQ:<n>|DATA:<hex_utf8>`, sem incluir `CHK`. O hexadecimal de DATA é minúsculo; o CRC é transmitido com quatro dígitos maiúsculos.

## CRC manual

`checksum.py` implementa CRC-16/IBM-3740 (CRC-16/CCITT-FALSE) bit a bit, sem biblioteca externa de checksum. Os parâmetros são largura 16 bits, polinômio `0x1021`, valor inicial `0xFFFF`, sem reflexão e XOR final `0x0000`. Para o vetor ASCII `123456789`, o resultado é `0x29B1`. O CRC detecta alterações acidentais; não é cifra nem autenticação criptográfica.

## Arquivos

- `cliente.py`: handshake, validação do texto, fragmentação, envio GBN/SR e exibição das confirmações;
- `server.py`: handshake, validação dos pacotes e do CRC, ACK/NACK e remontagem;
- `checksum.py`: algoritmo CRC-16 manual compartilhado;
- `EXEMPLO_TESTE.md`: cenários de execução e resultados observados;
- `RELATORIO_CHECKPOINT_2.md`: especificação do protocolo, manual, validação e processo de construção.
