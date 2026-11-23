# Roteiro de testes — Checkpoint 3

Inicie `server.py` e `cliente.py` em dois terminais na pasta CP3. Para cada sessão, o servidor solicita a janela (1 a 5; ENTER = 5). No cliente, informe um limite mínimo de 30, a mensagem e a configuração de falhas.

Para injetar falhas, responda `s`, informe as sequências a corromper (ou ENTER) e depois as sequências a perder (ou ENTER). Informe múltiplas sequências separadas por vírgula. Cada falha selecionada acontece somente na tentativa inicial.

## Matriz de integração

| Cenário | Modo | Janela | Falha no cliente | Resultado esperado |
|---|---|---:|---|---|
| Transferência sem falhas | GBN | 5 | nenhuma | ACK cumulativo por janela; mensagem final íntegra |
| Transferência sem falhas | SR | 5 | nenhuma | ACK individual por sequência; mensagem final íntegra |
| Janela unitária | GBN e SR | 1 | nenhuma | Um pacote pendente por vez; conclusão correta |
| Corrupção com janela unitária | GBN e SR | 1 | corromper SEQ 2 | NACK e retransmissão da única sequência pendente |
| Perda com janela unitária | GBN e SR | 1 | perder SEQ 2 | Recuperação do pacote sem avançar a base incorretamente |
| Corrupção no meio da janela | GBN | 5 | corromper SEQ 2 | CRC inválido, NACK na base 1 e reenvio de toda a janela |
| Perda no meio da janela | GBN | 5 | perder SEQ 2 | Janela incompleta, NACK na base 1 e reenvio de toda a janela |
| Corrupção seletiva | SR | 5 | corromper SEQ 2 | NACK de SEQ 2; reenvio somente de SEQ 2; buffer das posteriores |
| Perda seletiva | SR | 5 | perder SEQ 2 | ACKs das demais; timeout de SEQ 2 e reenvio somente desse pacote |
| Corrupção e perda na mesma sessão | GBN e SR | 5 | corromper SEQ 2 e perder SEQ 4 | Ambas recuperadas; GBN reenvia a janela, SR recupera cada sequência afetada |
| Mensagem com mais de uma janela | GBN e SR | 5 | nenhuma | Segunda janela inicia na sequência correta e a mensagem é remontada |
| Falha em janela posterior | GBN: corromper SEQ 6; SR: perder SEQ 6 | 5 | falha na segunda janela | Recuperação na base/SEQ 6 sem repetir a janela anterior |
| Texto UTF-8 e fragmento curto | GBN e SR | 5 | nenhuma | Acentos e emoji preservados; payload final menor que 4 caracteres |

Para corrupção, preencha a sequência somente no campo de corrupção. Para perda, preencha somente o campo de perda. Exemplos:

- GBN com corrupção: modo `1`, janela `5`, resposta `s`, corrupção `2`, perda vazia;
- SR com perda: modo `2`, janela `5`, resposta `s`, corrupção vazia, perda `2`;
- Falha combinada: modo `1` ou `2`, janela `5`, resposta `s`, corrupção `2`, perda `4`;
- fluxo sem falhas: responda `n`.

Mensagem recomendada para as janelas de cinco pacotes: `abcdefghijklmnopqrst` (20 caracteres). Para UTF-8 e fragmento final curto, use `áéíóXYZ🙂a`.

Para exercitar mais de uma janela com W=5, use `abcdefghijklmnopqrstuvwxYz` (26 caracteres), que gera sete pacotes.

## Verificações locais

Na pasta do projeto:

```bash
python -m unittest -v test_checkpoint3.py
python -c "from checksum import crc16_ibm_3740; print(format(crc16_ibm_3740(b'123456789'), '04X'))"
```

O segundo comando deve imprimir `29B1`. Em todos os cenários de integração, confirme que o servidor imprime os metadados dos pacotes, que os resumos mostram as falhas e retransmissões esperadas, e que o texto remontado é idêntico ao enviado.

## Limite da simulação

As perdas e corrupções são injetadas na camada de aplicação no cliente, de modo determinístico. O teste não altera o comportamento do TCP nem simula perda física de rede.
