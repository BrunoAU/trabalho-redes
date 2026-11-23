# Checkpoint 3 — Erros, perdas e recuperação

Esta pasta conclui a aplicação cliente-servidor dos checkpoints 2026.2. O CP1 e o CP2 permanecem preservados nas próprias pastas. O CP3 acrescenta falhas determinísticas no cliente, recuperação Go-Back-N e Repetição Seletiva e uma cifra simétrica manual.

## Funcionalidades

- Handshake do CP1: modo de operação, limite do texto (mínimo 30) e janela escolhida pelo servidor (1 a 5; ENTER seleciona 5);
- Fragmentação em payloads de até quatro caracteres Unicode;
- CRC-16/CCITT-FALSE manual, sem biblioteca de checksum;
- Cifra de César manual sobre bytes UTF-8, sem biblioteca de criptografia;
- Simulação determinística de corrupção e perda de pacotes selecionados no cliente;
- Recuperação GBN por janela e recuperação SR por pacote, com ACK, NACK, temporizador e retransmissões;
- Buffer de recepção fora de ordem em SR, com descarte lógico de duplicatas;
- Impressão de metadados e resumo das falhas, confirmações e retransmissões.

## Executar

Requisito: Python 3. Não há dependências externas.

No primeiro terminal:

```bash
cd TrabalhoRedes-Checkpoint3
python server.py
```

No segundo terminal, na mesma pasta:

```bash
python cliente.py
```

O cliente escolhe o modo, informa o limite e digita uma mensagem não vazia dentro desse limite. Depois, pode configurar sequências a corromper e a perder. Para testar computadores diferentes, ajuste `SERVER_HOST` no cliente para o IPv4 do servidor; a porta padrão é `8080`.

## Formato do protocolo

Todas as mensagens da aplicação terminam em NUL (`\0`) e são transportadas como frames TCP delimitados. O campo `DATA` contém o hexadecimal do ciphertext. O payload original continua limitado a quatro caracteres.

| Direção | Mensagem | Uso |
|---|---|---|
| Cliente → servidor | `BEGIN|<caracteres>|<pacotes>` | Declara o tamanho da mensagem e a quantidade de fragmentos |
| Cliente → servidor | `SEQ:<n>|DATA:<hex_cifrado>|CHK:<crc16>` | Envia payload cifrado, sequência e CRC |
| Cliente → servidor | `WINDOW_END|<base>|<último>` | Delimita um lote GBN |
| Servidor → cliente | `ACK|GBN|<último_seq>` | Confirma cumulativamente uma janela GBN |
| Servidor → cliente | `ACK|SR|<seq>` | Confirma um pacote SR individual |
| Servidor → cliente | `NACK|<seq>|<motivo>` | Rejeita um pacote ou uma janela |
| Servidor → cliente | `COMPLETE|<caracteres>|<pacotes>` | Confirma a remontagem integral |

O CRC cobre a representação ASCII `SEQ:<n>|DATA:<hex_cifrado>`, sem incluir `CHK`. O servidor valida o CRC antes de decifrar o payload.

## Algoritmos manuais

### Integridade

`checksum.py` implementa CRC-16/CCITT-FALSE bit a bit: polinômio `0x1021`, valor inicial `0xFFFF`, sem reflexão e XOR final `0x0000`. O vetor ASCII `123456789` produz `0x29B1`.

### Criptografia simétrica

`cipher.py` aplica uma rotação de César módulo 256 a cada byte UTF-8: `c = (p + k) mod 256`; a operação inversa é `p = (c - k) mod 256`. Cliente e servidor compartilham o deslocamento didático configurado no módulo. A cifra preserva bytes de acentos e emojis após a decifragem. Ela demonstra uma cifra simétrica manual e não se destina a proteger informação real.

## Simulador

- **Corrupção:** altera um dígito hexadecimal do `DATA` cifrado depois do cálculo do CRC. O servidor recalcula o CRC e responde NACK.
- **Perda:** omite o `DATA` selecionado na primeira transmissão. A injeção não se repete na retransmissão, para que a recuperação termine.
- Uma sequência não pode ser configurada simultaneamente para corrupção e perda na mesma sessão.
- O emissor permite até cinco retransmissões por janela GBN ou por sequência SR. O temporizador do emissor é de cinco segundos.

## Regras de recuperação

- **Go-Back-N:** o servidor só incorpora e confirma uma janela completa e válida. Ao encontrar corrupção, sequência ausente ou lote incompleto, responde com NACK na base. O cliente reenvia a janela pendente inteira; nenhum payload de um lote rejeitado entra na mensagem final.
- **Repetição Seletiva:** o servidor valida e confirma cada pacote individualmente. Pacotes válidos dentro da janela são armazenados por sequência, mesmo fora de ordem. O servidor remonta apenas quando as lacunas anteriores chegam. NACK ou timeout causa a retransmissão somente da sequência afetada.
- Duplicatas SR recebem novo ACK e não são anexadas duas vezes.

## Validação

Execute toda a validação automatizada sem dependências adicionais (seis testes unitários e uma matriz de 20 sessões com cliente e servidor em processos separados):

```bash
python -m unittest discover -v -p "test*.py"
```

Para rodar somente os testes unitários ou somente a matriz de integração, use `python -m unittest -v test_checkpoint3.py` ou `python -m unittest -v test_integration_checkpoint3.py`. O roteiro manual de integração está em [`EXEMPLO_TESTE.md`](EXEMPLO_TESTE.md). A especificação incremental, o processo de construção e o registro dos prompts principais estão na seção 8.5 do [`RELATORIO_CHECKPOINT_3.md`](RELATORIO_CHECKPOINT_3.md).

O relatório-fonte está em Markdown, e o PDF validado está em [`output/pdf/RELATORIO_CHECKPOINT_3.pdf`](output/pdf/RELATORIO_CHECKPOINT_3.pdf).

## Relação com a implementação de referência

O projeto de Luis Melo foi usado como base para a configuração determinística de sequências com falha, a organização dos fluxos de retransmissão e os contadores de sessão. O CP3 adapta essas ideias ao framing TCP, ao CRC manual e ao protocolo registrados no CP2 do grupo. A dependência Fernet da referência não é necessária para esta entrega.
