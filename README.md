# ELLOMAX · Controle de contratos e operação

Sistema web para acompanhar editais vencidos (itens, empenhos, gastos, recebimentos), o estoque de banheiros químicos
e contêineres alocados nos contratos e as **ordens de serviço com checklist e assinatura do cliente**.

## Como rodar

Requisito: Python 3.10 ou superior.

**Windows:** dê dois cliques em `iniciar.bat`.

**Linux / macOS:**
```bash
pip install -r requirements.txt
python app.py
```

Abra http://localhost:5000 e entre com **admin@local / admin123**. O sistema pede a troca da senha no primeiro acesso.
Outras pessoas da rede podem acessar pelo IP do computador (ex.: http://192.168.0.10:5000).

Os dados ficam no arquivo `licitacoes.db` (SQLite) e os anexos na pasta `uploads/`. Quem já usava a versão anterior não perde nada: o banco é atualizado automaticamente.

## O que tem

- **Pedidos de compra:** cada pedido/empenho/OF do órgão com itens, quantidades e valores (não deixa pedir acima do
  saldo), prazo e data de entrega com situação automática (no prazo, entregue com X dias de atraso, atrasado há X dias),
  solicitante, local, distância em km e custo do frete (km × R$/km, padrão R$ 3,00 configurável em *Alertas e frete*).
  Tela própria com filtros, % de entregas no prazo, frete total e exportação Excel.
- **Ordens de serviço (OS):** numeração automática por ano (0001/2026), tipo (instalação/entrega, manutenção e limpeza,
  recolhimento, troca, vistoria), vínculo com o contrato e o empenho/OF, agenda, equipe e veículo, equipamentos com nº de
  patrimônio (pode trazer os ativos já alocados no contrato), **checklist** conforme / não conforme / não se aplica com
  observação por item, ocorrências, fotos tiradas pelo celular, e **assinatura do cliente e do técnico na tela** (dedo,
  caneta ou mouse). Ao assinar, a OS é concluída e travada; só um administrador pode reabrir.
- **PDF da OS para entregar ao cliente:** cabeçalho da empresa, dados do contratante, equipamentos, checklist marcado,
  ocorrências, termo de recebimento com as assinaturas (ou linhas em branco para assinar no papel), fotos e código de
  verificação no rodapé.
- **Relatório de OS:** filtros por contrato, período, tipo e situação; PDF consolidado (resumo por tipo + lista, com
  campos de assinatura do responsável e do fiscal do contrato, útil para medição) e Excel.
- **Modelos de checklist:** já vem com instalação de banheiro químico, manutenção e limpeza, recolhimento e entrega de
  contêiner; edite ou crie outros em *Modelos de checklist* (uma linha por item, `# Grupo` para separar seções).

- **Editais:** empresa participante, órgão, CNPJ, UASG, nº do edital e do processo, modalidade, objeto, datas de
  abertura e homologação, nº do contrato/ata, vigência, prazo e local de entrega, contato, responsável, link e observações.
- **Itens vencidos:** lote, item, descrição, marca, unidade, quantidade, valor unitário, custo unitário estimado,
  quantidade empenhada, entregue, saldos e margem por item.
- **Empenhos e ordens de fornecimento:** número, tipo, emissão, prazo e data de entrega, quantidades por item
  (não deixa empenhar acima do saldo). Ao registrar a entrega, as quantidades entram no "entregue" dos itens.
- **Recebimentos:** parcela, empenho/OF, nota fiscal, data e valor previstos, data e valor recebidos, retenções na
  fonte (IR, INSS, ISS...), diferença e situação (Recebido, Parcial, A receber, Atrasado). Botão de baixa rápida.
- **Gastos:** data, categoria, descrição, fornecedor, documento e valor, com total por categoria.
- **Impostos:** alíquota média por empresa (ou por edital) para estimar os impostos e o lucro projetado.
- **Termos aditivos:** prorrogação (atualiza a vigência do edital), acréscimo/supressão de valor e reajuste
  (opcionalmente aplicado aos valores unitários dos itens).
- **Garantias contratuais:** modalidade, valor, apólice, seguradora, vigência e devolução.
- **Estoque de ativos:** cadastro de equipamentos próprios (ex.: banheiros químicos) com quantidade total e em
  manutenção; alocação em cada contrato com local e retorno previsto; devolução total ou parcial. O sistema mostra
  quanto está em cada contrato e quanto sobra disponível, e não deixa alocar mais do que existe.
- **Anexos:** edital, contrato, notas, comprovantes etc. (até 25 MB por envio), guardados na pasta `uploads/`.
- **Painel:** totais e listas de recebimentos atrasados, a receber em 30 dias, entregas de empenhos próximas,
  garantias e vigências vencendo e ativos com retorno previsto.
- **Alertas por e-mail:** resumo diário das pendências (Administração → Alertas por e-mail).
- **Exportação:** lista de editais em Excel; cada edital em Excel (várias abas) e em PDF.
- **Várias empresas (CNPJs):** filtro no topo da tela; usuários podem ser limitados a uma empresa.
- **Usuários e perfis:** Administrador (tudo), Operador (cadastra e edita), Somente leitura (consulta).
- **Auditoria:** registro de quem criou, alterou ou excluiu cada coisa.

## Alertas por e-mail

Configure em **Administração → Alertas por e-mail** (servidor SMTP, usuário, senha e destinatários). Com o envio
automático ligado, o sistema manda o resumo uma vez por dia a partir da hora escolhida, enquanto estiver rodando.
Se preferir agendar por fora (Agendador de Tarefas do Windows ou cron), use `python app.py enviar-alertas`.
No Gmail/Outlook use uma "senha de app".

## Backup

Copie o arquivo `licitacoes.db` e a pasta `uploads/` (ou o volume `/data` no Docker).

## Configuração opcional (variáveis de ambiente)

| Variável | Para quê |
|---|---|
| `PORT` | Porta do servidor (padrão 5000) |
| `LICITACOES_DATA` | Pasta de dados (banco, anexos, chave); no Docker é `/data` |
| `LICITACOES_DB` | Caminho do banco de dados |
| `LICITACOES_UPLOADS` | Pasta dos anexos (padrão `uploads/`) |
| `SMTP_SENHA` | Senha do e-mail (em vez de guardá-la no banco) |
| `ADMIN_PASSWORD` | Senha do admin criado na primeira execução |
| `SECRET_KEY` | Chave das sessões (gerada automaticamente se não informada) |

## Colocar na internet (VPS Hostinger + Coolify)

O repositório tem um `Dockerfile` pronto. No Coolify:

1. **New Resource → Public/Private Repository**, escolha este repositório e o build pack **Dockerfile**.
2. Porta exposta: **5000**.
3. Em **Storages**, crie um volume persistente montado em **`/data`** (banco, anexos, fotos e chave de sessão ficam lá).
4. Em **Environment Variables**, defina `ADMIN_PASSWORD` (senha do primeiro acesso) e, se quiser, `SECRET_KEY` e `SMTP_SENHA`.
5. Aponte o domínio (ex.: `sistema.ellomax.com.br`) e deixe o Coolify gerar o HTTPS.

O container roda com o servidor `waitress`, já tem healthcheck em `/saude` e fuso `America/Sao_Paulo`.
Backup: copie o volume `/data`.

## Interface

Visual próprio da ELLOMAX, sem Bootstrap: menu lateral, tipografia Archivo + IBM Plex Mono (números), cores
azul-petróleo e âmbar, modo escuro automático e telas pensadas para o celular do técnico em campo (checklist com
botões grandes, câmera para fotos e quadro de assinatura). Tudo é servido localmente (sem CDN).
