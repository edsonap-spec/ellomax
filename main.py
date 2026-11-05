"""Ponto de entrada para a Shard Cloud (shardcloud.app).

A Shard Cloud roda o arquivo indicado em MAIN no .shardcloud e espera o site
na porta 80. Aqui só definimos a porta padrão e iniciamos o app.py normal
(servidor waitress + agendador de alertas por e-mail).
"""
import os
import runpy

os.environ.setdefault("PORT", "80")
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), run_name="__main__")
