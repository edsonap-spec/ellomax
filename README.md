# Controle de Licitações Ganhas

Sistema web para acompanhar editais vencidos: dados do edital, itens ganhos com quantidades e valores,
gastos, recebimentos (previsto × recebido) e controle de acesso por usuário.

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
- **Anexos:** edital, contrato, notas, comprovantes etc. (até 25 MB por envio), guardados na pasta `uploads/`.
- **Painel:** totais e listas de recebimentos atrasados, a receber em 30 dias, entregas de empenhos próximas,
  garantias e vigências vencendo.
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

Copie o arquivo `licitacoes.db` e a pasta `uploads/`.

## Configuração opcional (variáveis de ambiente)

| Variável | Para quê |
|---|---|
| `PORT` | Porta do servidor (padrão 5000) |
| `LICITACOES_DB` | Caminho do banco de dados |
| `LICITACOES_UPLOADS` | Pasta dos anexos (padrão `uploads/`) |
| `SMTP_SENHA` | Senha do e-mail (em vez de guardá-la no banco) |
| `ADMIN_PASSWORD` | Senha do admin criado na primeira execução |
| `SECRET_KEY` | Chave das sessões (gerada automaticamente se não informada) |

## Colocar na internet

Para uso por várias pessoas fora do escritório, hospede em um serviço com disco persistente
(ex.: PythonAnywhere, uma VPS, ou Render/Railway com volume persistente) e use HTTPS.
Em produção rode com um servidor WSGI, por exemplo: `pip install waitress && waitress-serve --port=5000 app:app`.
