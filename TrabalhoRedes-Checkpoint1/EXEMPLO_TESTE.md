# Exemplos de Teste — Checkpoint 1 (Handshake & Sockets)

Estes testes cobrem apenas o handshake, que é o escopo desta entrega. Não há testes de envio de mensagem, checksum, criptografia ou simulação de erros — essas funcionalidades ainda não existem nesta versão.

## Como rodar

Em um terminal:

```bash
python server.py
```

Em outro terminal:

```bash
python cliente.py
```

## Cenários de teste

### Teste 1: Conexão cliente-servidor
**Passos:**
1. Inicie o servidor com `python server.py`.
2. Inicie o cliente com `python cliente.py` em outro terminal.

**Resultado esperado:** o servidor imprime `[SERVIDOR] Nova conexão de (...)` e o cliente exibe o menu `[SERVIDOR]Escolha o método da operação`. A conexão TCP foi estabelecida com sucesso.

**Testado e confirmado.**

---

### Teste 2: Seleção de modo Individual / Repetição Seletiva
**Passos:**
1. Realize o Teste 1.
2. No cliente, digite `2` quando solicitado o modo.

**Resultado esperado:** o menu identifica a opção `2` como `envio individual / Repetição Seletiva`; o handshake prossegue normalmente até `HANDSHAKE CONCLUÍDO` com esse modo exibido no resumo.

**Testado e confirmado.**

---

### Teste 3: Seleção de modo Lote / Go-Back-N
**Passos:**
1. Realize o Teste 1.
2. No cliente, digite `1` quando solicitado o modo.

**Resultado esperado:** o menu identifica a opção `1` como `envio em lote / Go-Back-N`; o handshake prossegue normalmente até `HANDSHAKE CONCLUÍDO` com esse modo exibido no resumo.

**Testado e confirmado.**

---

### Teste 4: Modo inválido
**Passos:**
1. Realize o Teste 1.
2. No cliente, digite um valor diferente de `1` ou `2` (ex.: `9`).

**Resultado esperado:** servidor responde `[SERVIDOR]Erro! Opção inválida! Repetindo operação...` e volta a enviar o menu; cliente exibe essa mensagem e pede o modo de novo. A conexão **não** é encerrada — o cliente pode tentar novamente.

**Testado e confirmado:** enviando `9` seguido de `2`, o servidor rejeitou o `9`, repetiu o menu e aceitou o `2` na tentativa seguinte, completando o handshake normalmente.

---

### Teste 5: Tamanho mínimo válido = 30
**Passos:**
1. Escolha um modo válido.
2. Quando solicitado o tamanho, digite `30`.

**Resultado esperado:** servidor aceita e envia `[SERVIDOR]Tamanho aceito! Handshake concluído.`; cliente exibe `Tamanho máximo : 30 caracteres` no resumo final.

---

### Teste 6: Tamanho superior a 30
**Passos:**
1. Escolha um modo válido.
2. Quando solicitado o tamanho, digite `35` (ou `40`).

**Resultado esperado:** servidor aceita e envia `[SERVIDOR]Tamanho aceito! Handshake concluído.`; cliente exibe o tamanho informado no resumo final.

**Testado e confirmado:** handshake completo com tamanho 35 (janela 5) e tamanho 40 (janela 2), ambos aceitos e exibidos corretamente pelo cliente.

---

### Teste 7: Tentativa de tamanho inválido (< 30)

**Validação do lado cliente (padrão do fluxo normal):**
1. Escolha um modo válido.
2. Quando solicitado o tamanho, digite um valor menor que 30 (ex.: `29`).

**Resultado esperado:** o cliente rejeita localmente (`[CLIENTE]Valor inválido! O tamanho mínimo é 30 caracteres. Tente novamente.`) e pede o valor de novo, sem enviar nada ao servidor.

**Testado e confirmado:** com `29` seguido de `40`, o cliente rejeitou `29` e só enviou `40` ao servidor.

**Validação do lado servidor (defesa contra um cliente que não valide):** o servidor também revalida o tamanho recebido, mesmo que o `cliente.py` padrão já valide localmente. Isso foi testado com um cliente mínimo que fala o protocolo diretamente (sem passar pela validação de `cliente.py`), enviando o tamanho `10`.

**Resultado esperado e confirmado:** o servidor respondeu `[SERVIDOR]NEGADO: Tamanho 10 é menor que o mínimo de 30.`, imprimiu `Conexão recusada por tamanho insuficiente.` no seu terminal e encerrou a conexão.

---

### Teste 8: Janela inicial = 5
**Passos:**
1. Complete o handshake normalmente.
2. No servidor, quando solicitado o tamanho da janela, pressione ENTER sem digitar nada (ou digite `5`).

**Resultado esperado:** servidor assume `5` como padrão, envia `[SERVIDOR]Janela atual: 5 pacotes.` e o valor `5`; cliente exibe `Tamanho da janela : 5` no resumo final.

**Testado e confirmado** com ENTER em branco e com `5` digitado explicitamente.

---

### Teste 9: Outro valor de janela (1 a 5)
**Passos:**
1. Complete o handshake normalmente.
2. No servidor, informe um valor diferente de 5, por exemplo `2` ou `3`.

**Resultado esperado:** servidor envia `[SERVIDOR]Janela atual: <n> pacotes.` e o valor correspondente; cliente exibe `Tamanho da janela : <n>` no resumo final.

**Testado e confirmado** com janela `2` e janela `3`.

Valores fora da faixa (`0`, `6`, texto não numérico) são rejeitados pelo servidor, que repete a pergunta no terminal (`[SERVIDOR]Valor inválido! Digite um número entre 1 e 5.` / `[SERVIDOR]Entrada inválida! Digite um número inteiro.`).

---

### Teste 10: Encerramento correto da sessão
**Passos:**
1. Complete o handshake até a mensagem `[SERVIDOR]Tamanho aceito! Handshake concluído.`.

**Resultado esperado:** cliente exibe o bloco `[CLIENTE] HANDSHAKE CONCLUÍDO` com modo, tamanho e janela negociados; servidor exibe `[SERVIDOR] Conexão com (...) encerrada.` e continua apto a aceitar novas conexões (cada cliente roda em sua própria thread).

**Testado e confirmado.**

## Resultado consolidado da validação desta revisão

| Teste | Resultado |
|---|---|
| Modo 1 / envio em lote / Go-Back-N, tamanho 30, janela padrão 5 | ✅ Handshake concluído, sem mensagem contraditória |
| Modo 2 / envio individual / Repetição Seletiva, `abc`, `29`, tamanho 35, janela 3 | ✅ Entradas inválidas rejeitadas no cliente; handshake concluído sem mensagem contraditória |
| Tamanho 10 enviado por cliente mínimo | ✅ Servidor respondeu `NEGADO` e encerrou a conexão |
| Resposta controlada de recusa para o cliente | ✅ Cliente exibiu a mensagem de recusa e não exibiu `HANDSHAKE CONCLUÍDO` |

Os quatro cenários desta tabela foram executados nesta revisão. Os cenários anteriores do documento permanecem como roteiro de teste do Checkpoint 1; seus resultados devem ser atualizados pelo grupo se forem executados novamente em outro ambiente.
