# Exemplos de teste — Checkpoint 2

Este roteiro cobre a transferência no caminho sem perda ou corrupção previsto para o CP2. Para cada cenário, inicie o servidor e o cliente em dois terminais, conforme o [README](README.md). O servidor solicita o tamanho da janela a cada conexão.

## Cenários de transferência

### 1. Go-Back-N com janela 5

- Escolha `1` no cliente, informe limite `30` e janela `5` no servidor.
- Envie `123456789012345678901234567890`.
- Esperado: oito fragmentos; ACK cumulativo até SEQ 5 na primeira janela e até SEQ 8 na segunda; `COMPLETE` no cliente e mensagem integral no servidor.

### 2. Repetição Seletiva com janela 5 e UTF-8

- Escolha `2`, informe limite `30` e janela `5`.
- Envie `áéíóXYZ🙂`.
- Esperado: ACK individual para cada fragmento e texto reconstruído sem perda de acentos ou emoji.

### 3. Janela 1

- Execute os cenários anteriores com janela `1`.
- Esperado: confirmação de um pacote por vez; GBN continua usando ACK cumulativo e SR continua usando ACK individual.

### 4. Mensagem menor que o limite e fragmento final curto

- Informe limite `30` e envie `abcdefghijklmnopqrstuvwxyza`.
- Esperado: os 27 caracteres são aceitos; o último fragmento tem três caracteres e a mensagem reconstruída mantém a ordem original.

### 5. Validação do limite

- Informe limite `30` e tente enviar uma sequência de 31 caracteres.
- Esperado: o cliente informa que o texto excede o limite e solicita outra entrada. Uma mensagem de até 30 caracteres é então transmitida.

## Verificação do CRC

Na pasta do projeto, execute:

```bash
python -c "from checksum import crc16_ibm_3740; print(format(crc16_ibm_3740(bytes.fromhex('313233343536373839')), '04X'))"
```

Resultado esperado: `29B1`.

## Resultados observados nesta revisão local — 20/10/2026

| Cenário | Resultado |
|---|---|
| GBN, janela 5, mensagem de 30 caracteres | ACK cumulativo, `COMPLETE` e remontagem correta |
| SR, janela 5, texto com acentos e emoji | ACKs individuais e UTF-8 preservado |
| GBN, janela 1, entrada de 31 caracteres seguida de mensagem válida | Entrada excedente recusada e transmissão seguinte concluída |
| SR, janela 1, fragmento final curto | Pacotes confirmados individualmente e texto reconstruído |
| Vetor CRC ASCII `123456789` | `0x29B1` |
| CRC alterado em GBN e SR | `NACK|1|CHECKSUM` nos dois modos |
| Ausência de DATA após `BEGIN` | `NACK|1|TIMEOUT` após 5 segundos |
| Parser com rótulo inválido, CRC divergente, SEQ não canônico ou UTF-8 inválido | Quadros rejeitados pelo motivo correspondente |

Os testes de comunicação foram feitos em `127.0.0.1`. O simulador de perdas/corrupção e a recuperação por retransmissão são escopo do CP3.
